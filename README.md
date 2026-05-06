# release-toolkit

Opinionated [Commitizen](https://commitizen-tools.github.io/commitizen/)
release tooling for Python projects — works for **single-package repos** and
**monorepos with per-package changelogs**, with optional Slack notifications
on tag pushes.

The headline feature is the `impacts_cz` Commitizen plugin: in a monorepo,
only commits tagged with `Impacts: <package>` count toward a package's
version bump and changelog. In a single-package repo it collapses to plain
Conventional Commits.

Requires Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) — `rt release`
runs `uv sync` / `uv run cz bump`, `rt init` writes `[dependency-groups].dev`
(PEP 735), and the generated GitHub workflow uses `astral-sh/setup-uv`. Other
package managers (Poetry, plain pip) are not supported out of the box.

## Quick start

Install the CLI once on your PATH:

```bash
uv tool install release-toolkit
```

Bootstrap a repo (the CLI also writes a matching GitHub workflow under
`.github/workflows/` and adds `release-toolkit` to `[dependency-groups].dev`
so `cz bump` has the plugin available in CI):

```bash
# single-package repo
rt init single ./pyproject.toml

# monorepo: PATH NAME pairs
rt init monorepo \
  packages/client/pyproject.toml client \
  packages/service/pyproject.toml service

uv sync --group dev
```

Cut a release from the package directory:

```bash
rt release              # monorepo (uses the Impacts: filter)
rt release --no-filter  # single-package repo
```

`rt` is a short alias for `release-toolkit`; both names work everywhere.

## Authoring commits

In a monorepo, declare which packages a commit affects via an `Impacts:`
footer:

```
feat: add streaming endpoint

Impacts: client, commons
```

* the footer is matched case-insensitively, on its own line
* tags split on commas/whitespace, matched with word boundaries
* a commit without `Impacts:` is invisible to every package
* if you want shared-code commits to bump everyone, add a tag like `commons`
  to every package's `impacts` list
* the footer name is configurable via `impacts_footer` (e.g. `Affects`)

In a single-package repo, just write Conventional Commits — the plugin has
nothing to filter and behaves like `cz_conventional_commits`.

## Why this exists

Vanilla `cz bump` reads every commit between the last matching tag and
`HEAD` when computing the next version. In a monorepo that is wrong — a
`feat:` for `service` would still bump `client`. Commitizen's
`changelog_pattern` only filters the *rendered* changelog, not the
increment.

`impacts_cz` rebuilds `changelog_pattern` from the package's `impacts`
list, and `rt release` applies the same filter when picking
MAJOR / MINOR / PATCH / NONE before invoking `cz bump --increment`.

## CLI reference

### `rt release`

Drives the full flow from one command, run from the package directory:

1. `uv sync --group dev`
2. refuses a dirty worktree
3. fast-forwards `--master-branch` (default `master`); warns on other branches
4. computes the filtered increment, aborts if `NONE` (skip with `--no-filter`)
5. shows `cz bump --dry-run` and asks `[y/N]`
6. runs `cz bump`, then `git push --follow-tags`

Anything after `--` is forwarded to `cz bump`
(e.g. `rt release -- --prerelease beta`). Exit 1 with a stderr `ERROR:` on
abort.

### `rt init {single,monorepo}`

Inserts a default `[tool.commitizen]` section, appends `release-toolkit` to
`[dependency-groups].dev` (with a major-version cap derived from the
running CLI), and writes a caller workflow at
`<repo-root>/.github/workflows/release[-<name>].yml`.

PATH may be a `pyproject.toml` file or the directory containing one. Each
file is processed independently — warnings keep exit 0, hard errors
(missing file, TOML parse failure, no `.git` found) flip to exit 1.

If `[tool.commitizen]` is already present with `name = "impacts_cz"` or
`release-toolkit` is already in `dev`, the step is a no-op. If the section
exists with a different `name`, the file is left untouched with a warning.

Override the version source with `--version-provider <name>` (default
`pep621`); any [built-in or third-party
provider](https://commitizen-tools.github.io/commitizen/config/version_provider/#built-in-providers)
name is written verbatim.

### `rt increment`

```bash
rt increment [--config pyproject.toml]
```

Prints `MAJOR` / `MINOR` / `PATCH` / `NONE`. Useful for wiring into other
release pipelines: capture stdout, feed to `cz bump --increment`.

## Generated configs

`init single` writes:

```toml
[tool.commitizen]
name = "impacts_cz"
version_provider = "pep621"
tag_format = "v$version"
annotated_tag = true
changelog_file = "CHANGELOG.md"
update_changelog_on_bump = true
changelog_merge_prerelease = true
```

`init monorepo` adds per-package fields:

```toml
tag_format = "client-v$version"
bump_message = "bump: client $current_version -> $new_version"
impacts = ["client"]
```

Tune by hand afterwards if needed:

* add a shared tag (e.g. `commons`) to `impacts` if shared-code commits
  should bump this package
* override the footer name: `impacts_footer = "Affects"`

## GitHub building blocks

### `.github/workflows/release-notify.yml`

Reusable workflow. Triggered on a release tag push; generates notes from
`cz changelog`, creates a GitHub Release, optionally posts to Slack. The
caller is generated by `rt init`; the example below is for reference:

```yaml
name: CD Client

on:
  push:
    tags: ['client-v*']

permissions:
  contents: read

jobs:
  release:
    uses: your-org/release-toolkit/.github/workflows/release-notify.yml@v1
    with:
      package_dir: pylon_client
      tag_prefix: client-v
      python_version: '3.11'
    secrets:
      SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}  # omit to disable
    permissions:
      contents: write
```

| input | required | default | meaning |
| ----- | -------- | ------- | ------- |
| `package_dir` | yes | — | path to the package's `pyproject.toml` |
| `tag_prefix` | yes | — | tag prefix preceding the version (e.g. `client-v`, `v`) |
| `python_version` | no | `3.11` | Python used by `cz changelog` |
| `slack_message_prefix` | no | `Released` | prefix for the Slack message |

Slack is fully optional: provide `SLACK_WEBHOOK_URL` to enable, omit to
disable. No extra plugin to install.

### `.github/actions/setup-python-env`

Composite action that installs Python, `uv`, and `nox` at pinned versions.
Inputs: `python-version` (required), `uv-version`, `nox-version`.

## Examples

* `examples/monorepo/` — `pyproject.toml` and caller workflow for a
  monorepo package using `hatch-vcs`.
* `examples/single-package/` — same idea, no `impacts`.

Copy what you need; they are intentionally minimal.

## Developing release-toolkit itself

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run pyright
```

Layout:

```
src/release_toolkit/
    cz_plugin.py            # ImpactsCz, build_changelog_pattern
    helpers.py              # find_filtered_increment, load_config
    installer.py            # CommitizenConfig, install_into_document
    workflow_installer.py   # WorkflowConfig, render_workflow
    cli.py                  # argparse + I/O (entry point)
    release_runner.py       # run_release (subprocess orchestration)
github/
    actions/setup-python-env/
    workflows/release-notify.yml
```

The plugin is registered through the `commitizen.plugin` entry point in
`pyproject.toml`; do **not** import it from `release_toolkit/__init__.py` —
that would re-enter the package during Commitizen's entry-point discovery
and deadlock.

## FAQ

**`rt increment` prints `NONE` but I just merged something.** No commits
match the package's `Impacts:` filter since the last package tag. Either
the commit is missing the footer, or it lists tags this package does not
subscribe to.

**`cz bump` wants to bump but `increment` says `NONE`.** That is the bug
this toolkit fixes — vanilla `cz bump` ignores `changelog_pattern` for
increment computation. Use `rt release` (or feed `--increment` to `cz bump`
yourself) so the filter is honored.

**Is the plugin compatible with `bump_pattern` / breaking-change detection?**
Yes — `ImpactsCz` is a thin subclass of `ConventionalCommitsCz` that only
rewrites `changelog_pattern`. Everything else is inherited as-is.
