# Custom Dockerfile Support

## Summary

Allow users to supply their own Dockerfile to fully replace the bundled one. The custom Dockerfile is resolved via a priority chain: `--dockerfile` CLI flag > `~/.trusty-cage/Dockerfile` > bundled default.

## Motivation

Developers may need different base images, additional system packages, alternate runtimes, or non-standard configurations. Rather than maintaining an extension/layering mechanism, let users own the full Dockerfile and accept responsibility for the result.

## Design

### Resolution Order

1. **`--dockerfile <path>` CLI flag** on `create` and `rebuild-image` commands (highest priority)
2. **`~/.trusty-cage/Dockerfile`** convention path (checked if no CLI flag)
3. **Bundled Dockerfile** at `src/trusty_cage/assets/Dockerfile` (fallback)

### Replacement Semantics

The resolved Dockerfile fully replaces the bundled one. There is no extension or layering. The image is tagged `trusty-cage:latest` regardless of source.

### Warning Messages

When a custom Dockerfile is used (sources 1 or 2), print a Rich-formatted warning to stderr before building:

```
WARNING: Using custom Dockerfile: /path/to/Dockerfile
This replaces the default trusty-cage image entirely. You are responsible for
ensuring the image includes the trustycage user (UID 1000), required tools, and
any security constraints your workflow requires.
```

### SHA Tracking

`~/.trusty-cage/image.sha` tracks whichever Dockerfile was actually used. Switching between custom and bundled (or changing the custom file) produces a SHA mismatch and triggers a rebuild via `build_if_needed()`.

### meta.json

No changes. The Dockerfile choice is an image-level concern, not per-environment.

## File Changes

| File | Change |
|---|---|
| `constants.py` | Add `CUSTOM_DOCKERFILE` path constant (`~/.trusty-cage/Dockerfile`) |
| `image.py` | Add `resolve_dockerfile(cli_path)` returning `(path, is_custom)`. Update `compute_dockerfile_sha()`, `needs_rebuild()`, `rebuild()`, `build_if_needed()` to accept and forward the resolved path. |
| `cli.py` | Add `--dockerfile` option to `create` and `rebuild-image`. Pass resolved path to image functions. Print warning when custom Dockerfile is detected. |

## Out of Scope

- Two-stage / extension builds (`FROM trusty-cage:latest`)
- Validation of custom Dockerfile contents
- `TRUSTY_CAGE_DOCKERFILE` environment variable
- Per-environment Dockerfile tracking
