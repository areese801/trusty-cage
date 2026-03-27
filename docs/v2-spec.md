# trusty-cage — v2 Roadmap

Planned enhancements beyond the feature-complete v1. Each item is a candidate for a future release — details will be filled in as we plan each feature.

---

## Planned Enhancements

### ~~PyPI Distribution~~ (Done)

Published as `trusty-cage` on PyPI. Install via `pip install trusty-cage` or `pipx install trusty-cage`. Includes `trusty-cage init` command for first-run configuration.

### Multi-Language Runtime Support

Add configurable runtimes beyond Python: Node.js (as a user runtime, not just for Claude Code internals), Go, Rust, etc. Likely via a `--runtime` flag on `create` or a config option.

### Optional Opt-In Git Write Access

A configuration option allowing a developer who understands the implications to supply credentials and configure a remote inside the environment. Enables a full in-container workflow without the export step.

### Snapshot / Clone Commands

- `trusty-cage snapshot <name>` — checkpoint a volume to a tarball
- `trusty-cage clone <name> <new-name>` — fork an environment from an existing one

### Linux Host Support

The architecture already supports it (OrbStack is just not installed; Docker Engine is used directly). Add detection, testing, and documentation for bare-metal Linux and WSL2.

### Other Agent Support

Add support for coding agents beyond Claude Code: Aider, Goose, Codex, etc. The architecture is already agent-agnostic — this is primarily about configuring the right tools and entry points per agent.
