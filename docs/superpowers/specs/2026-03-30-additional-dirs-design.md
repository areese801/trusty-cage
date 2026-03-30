# Additional Directories Support — Design Spec

**Date:** 2026-03-30
**Status:** Draft
**Branch:** feature/additional-dirs

## Context

trusty-cage environments are scoped to a single project directory at `/home/trustycage/project`. In practice, agents often need access to additional repositories — shared libraries, frontend/backend siblings, reference codebases. Today the only option is to destroy and recreate the cage with different source material.

This feature adds the ability to ship additional local directories into a cage, each volume-backed and writable, with full export/sync/diff support. The mental model mirrors Claude Code's `/add-dir` — point at a directory on the host, and it appears inside the cage as a sibling to the main project.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| When to add | Both create-time and post-create | Orchestrator workflow may discover needed repos mid-task |
| Mutability | Fully writable | Supports full-stack scenarios; cage isolation limits blast radius |
| Persistence | Volume-backed (survives stop/start) | Consistent with main project behavior |
| Volume strategy | Separate volume per dir | No breaking changes; independent lifecycles; clean separation |
| Container layout | Siblings to project/ | Flat, simple, matches /add-dir mental model |
| Source types | Local paths only (no git URLs) | Keeps it simple; git URL support can be added later |
| Backwards compat | Not a concern | Cages are short-lived; users run from venvs |
| CLI pattern | Flat top-level commands | Matches existing CLI style (no subcommand groups) |

## Data Model

### New Dataclass: `AdditionalDir`

```python
@dataclass
class AdditionalDir:
    name: str              # e.g. "shared-lib" (derived from basename or --name)
    host_source_path: str  # original path: "/Users/areese/projects/shared-lib"
    host_clone_path: str   # staging: "~/.trusty-cage/envs/<cage>/dirs/shared-lib/"
    volume_name: str       # "isolated-dev-<cage>-shared-lib"
    container_path: str    # "/home/trustycage/shared-lib"
    added_at: str          # ISO 8601 UTC
```

### Updated `MetaJson`

```python
@dataclass
class MetaJson:
    name: str
    repo_url: str
    created_at: str
    volume_name: str
    container_name: str
    host_clone_path: str
    auth_mode: str
    api_key_env: str = "ANTHROPIC_API_KEY"
    additional_dirs: list[dict] = field(default_factory=list)  # NEW
```

`additional_dirs` stores serialized `AdditionalDir` dicts. Volume naming convention: `isolated-dev-{cage_name}-{dir_name}`.

## Host Layout

```
~/.trusty-cage/envs/<cage>/
  meta.json              # includes additional_dirs array
  repo/                  # main project host clone (unchanged)
  dirs/                  # NEW
    shared-lib/          # host clone for export/sync
    frontend/            # host clone for export/sync
```

## Container Layout

```
/home/trustycage/
  project/               # main project (volume: isolated-dev-<cage>)
  shared-lib/            # added dir (volume: isolated-dev-<cage>-shared-lib)
  frontend/              # added dir (volume: isolated-dev-<cage>-frontend)
```

Each additional dir is a sibling to `project/`, mounted on its own Docker named volume.

## CLI Commands

### New: `tc add-dir <cage-name> <path> [--name]`

Adds a local directory to an existing cage.

**Flow:**
1. Validate cage exists, resolve path, derive name from basename (or use `--name`)
2. Validate no name collision with existing additional dirs or "project"
3. Create Docker volume `isolated-dev-{cage}-{dir_name}`
4. Rsync source dir → host clone at `~/.trusty-cage/envs/{cage}/dirs/{dir_name}/`
5. Stop container
6. Remove container (`docker rm` — volumes survive)
7. Recreate container with all existing mounts + new volume mount
8. Start container
9. `docker cp` files into the new volume path
10. `chown -R trustycage:trustycage` the new dir
11. `git init` + initial commit inside the new dir in the container
12. Update `meta.json` with new `AdditionalDir` entry

### New: `tc remove-dir <cage-name> <dir-name>`

Removes an additional directory from a cage.

**Flow:**
1. Validate cage and dir exist in meta
2. Warn if unexported changes detected (quick diff check)
3. Stop container
4. Remove container
5. Recreate container without the removed dir's volume mount
6. Start container
7. Remove Docker volume (`docker volume rm`)
8. Remove host clone at `dirs/{dir_name}/`
9. Update `meta.json`

### Modified: `tc create` — new `--add-dir` flag

```
tc create <url-or-dir> --add-dir ~/projects/frontend --add-dir ~/projects/shared-lib
```

Repeatable flag. After the main project is set up, runs `add-dir` logic for each path. Since the container is freshly created, all volume mounts are included in the initial `docker create` — no recreation needed.

### Modified: `tc export`, `tc sync`, `tc diff` — new `--dir` and `--all` flags

```
tc export my-cage                          # main project only (unchanged default)
tc export my-cage --dir shared-lib         # one additional dir
tc export my-cage --dir fe --dir lib       # multiple additional dirs
tc export my-cage --all                    # main project + all additional dirs
```

- `--dir` is repeatable, targets specific additional dirs by name
- `--all` targets the main project first, then all additional dirs
- No flags = main project only (fully backwards-compatible)
- Output grouped by dir name with headers when operating on multiple dirs

**Export `--dir` flow:**
1. Load meta, look up `AdditionalDir` entry by name
2. `docker cp` container path → temp staging
3. Rsync staging → host clone path for that dir
4. Repeat per `--dir`

**Sync `--dir` flow:**
1. Load meta, look up `AdditionalDir` entry
2. Rsync host clone → staging
3. `docker cp` staging → container path
4. Repeat per `--dir`

**Diff `--dir` flow:**
Same as export but with `rsync --dry-run`. Shows changes per dir.

### Modified: `tc destroy`

In addition to existing cleanup (container + main volume + keeps `repo/`):
- Remove all additional dir volumes (`docker volume rm` each)
- Remove `dirs/` subdirectory from host env dir
- Warn if any additional dirs have unexported changes before proceeding

### Modified: `tc list`

- Table output: show additional dir count or names
- `--json` output: include `additional_dirs` array from meta

## Container Recreation Strategy

Adding or removing a volume mount requires recreating the container (Docker limitation). The sequence:

**Add:**
1. Stop container
2. Record existing container config (mounts, hostname, caps)
3. `docker rm` (volumes preserved — separate Docker objects)
4. `docker create` with all previous mounts + new mount
5. `docker cp` files into new volume
6. `git init` in new dir
7. Start container
8. Update `meta.json`

**Remove:**
1. Stop container
2. `docker rm`
3. `docker create` without the removed mount
4. Start container
5. `docker volume rm` the removed volume
6. Clean up host clone
7. Update `meta.json`

**Key property:** The main project volume and other additional dir volumes survive the `docker rm`/`docker create` cycle. Only container-layer writes (non-volume) are lost. Dotfiles are reapplied at attach time, so this is acceptable.

**At create time:** No recreation needed — all mounts are known upfront and passed to the initial `docker create`.

## Implementation Notes

### `container_create` signature change

The current `container_create` in `docker.py` accepts a single `volume_mount: str | None`. This must be updated to accept `volume_mounts: list[str] | None` to support multiple mounts in a single `docker create` call. All existing callers (in `cli.py`'s `create` command) must be updated to pass a list.

### Container recreation: no Docker inspect dependency

The recreation flow must NOT read container config from `docker inspect`. All arguments for `docker create` are deterministic from `meta.json`:
- `container_name` and `hostname` = `meta.name`
- `volume_mounts` = main project mount + all `additional_dirs[].volume_name:additional_dirs[].container_path` mounts
- `cap_add` = always `["NET_ADMIN"]`
- `image` = always `trusty-cage:latest`

This keeps `meta.json` as the sole source of truth, consistent with the project's design constraint.

### Failure recovery during container recreation

There is a failure window between `docker rm` (old container gone) and completing the new `docker create` + `meta.json` update. Recovery strategy:
- `add-dir` and `remove-dir` should be **idempotent**. If re-run after a partial failure, they should detect existing state (volume already created, container already removed) and continue from where they left off.
- Volume creation is safe to retry (`docker volume create` is idempotent).
- If `docker create` fails after `docker rm`, `meta.json` still has the old state — a subsequent `add-dir` or even `tc attach` can detect the missing container and recreate it from meta.

### `--dir` flag name on `create`

`tc create` already uses `--dir` for specifying the main source directory (local path mode). The additional dirs flag on `create` is `--add-dir` to avoid collision. On export/sync/diff, `--dir` is available since those commands have no existing flag by that name.

### Path storage

All paths in `AdditionalDir` (`host_source_path`, `host_clone_path`) are stored as fully-resolved absolute paths, consistent with how `MetaJson.host_clone_path` is stored today. The `~` notation in comments is illustrative shorthand only.

### Name collision handling

Name collision checks use the sanitized name (same regex as `derive_name_from_path`). When the derived name differs from the directory basename due to sanitization, the CLI shows the derived name to the user so they can override with `--name` if needed. Collisions with existing additional dir names or "project" are rejected with a clear error.

## Modules Modified

| File | Changes |
|---|---|
| `environment.py` | Add `AdditionalDir` dataclass; add `additional_dirs` field to `MetaJson`; add helper to derive dir name |
| `cli.py` | Add `add-dir` and `remove-dir` commands; add `--add-dir` to `create`; add `--dir`/`--all` to export/sync/diff; update `destroy` cleanup; update `list` output |
| `docker.py` | Update `container_create` to accept `volume_mounts: list[str]`; add helper to recreate container with updated volume mounts |

## Modules Unchanged

auth, networking, dotfiles, messaging, launch, logs, attach, Dockerfile, image building, config resolution.

## Verification Plan

1. **Unit tests:** Test `AdditionalDir` serialization, name derivation, meta round-trip with additional dirs
2. **Integration tests (manual):**
   - `tc create <url> --add-dir ~/some/dir` — verify both dirs present in container
   - `tc add-dir` on running cage — verify container recreation, files accessible
   - `tc remove-dir` — verify volume removed, container still works
   - `tc export --dir <name>` — verify files land in host clone
   - `tc sync --dir <name>` — verify files pushed into container
   - `tc diff --dir <name>` — verify dry-run output
   - `tc export --all` — verify all dirs exported
   - `tc destroy` — verify all volumes cleaned up, dirs/ removed, repo/ kept
   - `tc list` — verify additional dirs shown
   - Stop/start cycle — verify additional dir volumes persist
3. **Edge cases:**
   - Add dir with name collision (should error)
   - Add dir named "project" (should error)
   - Remove last additional dir
   - Export dir that inner Claude hasn't modified
   - Destroy cage with unexported additional dir changes
   - Two source paths that sanitize to the same name (e.g. `my.lib` and `my_lib`)
   - `tc attach` after `add-dir` (verify tmux session, network policy still work on recreated container)
   - `tc sync --dir` when host clone exists but is empty
   - Partial failure recovery: kill `add-dir` mid-flight, then re-run (should be idempotent)
   - `add-dir` when container is stopped vs running
