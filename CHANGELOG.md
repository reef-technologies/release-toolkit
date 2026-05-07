## v0.2.1 (2026-05-07)

### Fix

- pin reusable release-notify workflow to v0.2.0

## v0.2.0 (2026-05-07)

### BREAKING CHANGE

- `rt init single` and `rt init monorepo` now accept
project root directories instead of pyproject.toml file paths. Each
directory must contain a pyproject.toml; passing a file (or any
non-directory path) errors with `ERROR: {path}: not a directory`.
- README no longer instructs adding `release-toolkit` to
[dependency-groups].dev manually -- `rt init` now injects it (with a
major-version cap derived from the installed toolkit version) into every
pyproject it mutates. Recommended install is now `uv tool install
release-toolkit`. Generated dev-group no longer duplicates `commitizen`
(release-toolkit pulls it transitively).
- distribution renamed from `cz-release-toolkit` to `release-toolkit`;
the `cz-release-toolkit` console script is removed in favor of `release-toolkit`
(with a short alias `rt`). Consumer projects must update their dev dependency from
`cz-release-toolkit` to `release-toolkit` and any CI/scripts invoking
`cz-release-toolkit ...` to `release-toolkit ...` (or `rt ...`).
- `release_toolkit.nox_release.release_session` is gone —
remove `noxfile.py` and the `nox` dev-dep from consumer projects, then call
`uv run cz-release-toolkit release` from the package directory.

### Feat

- **cli**: add conditional major_version_zero, require directory paths
- Add release workflow for rt itself
- **cli**: add --version-provider flag and rename internal workflow helpers
- **cli**: expand default [tool.commitizen] section in `rt init`
- **cli**: accept directory paths in `rt init single` and `rt init monorepo`
- **cli**: print Slack setup hint at the end of `init`
- distribute via `uv tool install`; `rt init` injects dev dependency
- **cli**: replace `release_session` Nox helper with `release` subcommand
- **cli**: generate release-notify caller workflow on `init`
- **cli**: add `init single` and `init monorepo` subcommands

### Fix

- removed stdout capture
- **ci**: rename github/ to .github/ so GitHub picks up workflows


- rename distribution to `release-toolkit`, expose CLI as `release-toolkit` and `rt`
