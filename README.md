# release-toolkit

Reusable [Commitizen](https://commitizen-tools.github.io/commitizen/) tooling
extracted from `bittensor-pylon`. Works for both **monorepos with per-package
changelogs** and **single-package** repositories. Slack notifications are
**optional** — drop the secret and they go away.

---

## Table of contents

* [What you get](#what-you-get)
* [How it works](#how-it-works)
* [Install](#install)
* [Quick start (monorepo)](#quick-start-monorepo)
* [Quick start (single-package repo)](#quick-start-single-package-repo)
* [Authoring commits with `Impacts:` footer](#authoring-commits-with-impacts-footer)
* [The `release-toolkit` CLI](#the-release-toolkit-cli)
* [GitHub building blocks](#github-building-blocks)
* [Optional Slack](#optional-slack)
* [Examples in this repo](#examples-in-this-repo)
* [Developing release-toolkit itself](#developing-release-toolkit-itself)
* [FAQ / troubleshooting](#faq--troubleshooting)

---

## What you get

* **`impacts_cz` Commitizen plugin** — filters changelog and version-increment
  computation by an `Impacts:` footer (configurable). When `impacts` is not
  configured, behaves like `cz_conventional_commits`.
* **`release-toolkit` CLI** — exposes `increment` (the missing piece that
  makes Commitizen respect `changelog_pattern` while picking the bump kind),
  `init {single,monorepo}` for bootstrapping `[tool.commitizen]` into one
  or more `pyproject.toml` files **and** generating a matching
  `release-notify` caller workflow under `.github/workflows/`, and
  `release` — a one-shot release driver that performs the dirty-tree check,
  dry-run, confirmation, bump, and push.
* **GitHub building blocks** under `github/` — a `setup-python-env` composite
  action and a `release-notify.yml` reusable workflow that creates a GitHub
  Release and (optionally) posts to Slack.

## How it works

Vanilla Commitizen reads every commit between the last matching tag and `HEAD`
when computing the next version. In a **monorepo** that is wrong: a `feat:`
landing in package `service` would still bump package `client`. Commitizen has
a `changelog_pattern` setting, but it only filters the rendered changelog — not
the increment computation.

`impacts_cz` extends `ConventionalCommitsCz` and rebuilds `changelog_pattern`
from a `impacts = [...]` list, scoped to the configurable footer
(`Impacts:` by default). The `release-toolkit increment` CLI applies the
same filter when computing the next bump (MAJOR / MINOR / PATCH / NONE), so
you can pass it to `cz bump --increment <kind>` and get monorepo-correct
behavior.

In a **single-package** repo you just leave `impacts` unset — the plugin
collapses to plain Conventional Commits, and `release-toolkit release
--no-filter` skips the increment-filter step entirely.

## Install

The toolkit is published as `release-toolkit` and ships the
`impacts_cz` Commitizen plugin via the `commitizen.plugin` entry point — no
extra wiring needed once it is installed alongside `commitizen`.

The recommended install — both for single-package repos and for monorepos
that have no root `pyproject.toml` to edit — is to put the CLI on your PATH
once with `uv tool`:

```bash
uv tool install release-toolkit
```

Then bootstrap the per-package config with `release-toolkit init` (or its
short alias `rt init`). Each `init` call also injects a
`release-toolkit>=X.Y.Z,<N+1` entry into the target's
`[dependency-groups].dev` (with a major-version cap derived from the
toolkit version that runs the command), so that `cz bump` — which needs the
`impacts_cz` plugin in the same env as `commitizen` — works in CI and in
`uv run cz bump` flows. `commitizen` itself is pulled in transitively by
`release-toolkit`, so the generated `dev` group does not duplicate it.

```bash
release-toolkit init single ./pyproject.toml
# or, for a monorepo:
release-toolkit init monorepo packages/client/pyproject.toml client \
                              packages/service/pyproject.toml service

uv sync --group dev
```

Python ≥ 3.11 is required.

If you consume from a private index / git ref instead of PyPI, point your
project's package source there — the plugin discovery logic does not care
where the wheel came from.

## Quick start (monorepo)

Bootstrap `[tool.commitizen]` into every package at once with `init monorepo`.
Each argument pair is `(PATH, NAME)` — path to the package's `pyproject.toml`
and the package name used for `tag_format` / `impacts`:

```bash
release-toolkit init monorepo \
  packages/client/pyproject.toml client \
  packages/service/pyproject.toml service
```

Result in `packages/client/pyproject.toml`:

```toml
[dependency-groups]
dev = ["release-toolkit>=X.Y.Z,<N+1"]

[tool.commitizen]
name = "impacts_cz"
tag_format = "client-v$version"
changelog_file = "CHANGELOG.md"
update_changelog_on_bump = true
impacts = ["client"]
```

The command also writes a per-package caller workflow at
`<repo-root>/.github/workflows/release-notify-client.yml` (and one for every
other pair you pass). Each file invokes the reusable
`reef-technologies/release-toolkit/.github/workflows/release-notify.yml@v1`
workflow with the right `package_dir` and `tag_prefix`, and forwards
`SLACK_WEBHOOK_URL` from the consumer repo's secrets.

Optionally tune by hand afterwards — the command stays minimal on purpose:

* add a shared tag (e.g. `commons`) to `impacts` if shared-code commits should
  bump this package: `impacts = ["client", "commons"]`.
* declare sibling tag formats so Commitizen ignores them when picking the
  current version: `ignored_tag_formats = ["service-v$version"]`.
* override the footer name: `impacts_footer = "Affects"`.

Tag a commit with `Impacts: client, commons` to flag it for the client package.
Run the release from the package directory when ready:

```bash
release-toolkit release
```

A fuller example — including `tag-pattern` and `git_describe_command` for
`hatch-vcs` — lives in `examples/monorepo/`.

## Quick start (single-package repo)

Bootstrap `[tool.commitizen]` with `init single`:

```bash
release-toolkit init single ./pyproject.toml
```

Result:

```toml
[dependency-groups]
dev = ["release-toolkit>=X.Y.Z,<N+1"]

[tool.commitizen]
name = "impacts_cz"
tag_format = "v$version"
changelog_file = "CHANGELOG.md"
update_changelog_on_bump = true
# no `impacts` -> behaves like vanilla conventional_commits
```

The command also writes `<repo-root>/.github/workflows/release-notify.yml` —
a caller for the reusable
`reef-technologies/release-toolkit/.github/workflows/release-notify.yml@v1`
workflow, wired with `package_dir: .` and `tag_prefix: v`.

Then run the release from the repo root when ready:

```bash
release-toolkit release --no-filter
```

`--no-filter` skips the `increment` step; without an `impacts` list there is
nothing to filter, and Commitizen will pick the bump itself.

## Authoring commits with `Impacts:` footer

In a monorepo, every commit that should affect a package needs to declare it:

```
feat: add streaming endpoint

Impacts: client, commons
```

Rules of the footer regex (see `tests/test_cz_plugin.py` for the full set):

* footer is matched case-insensitively, on its own line
* tags are split on commas/whitespace and matched with **word boundaries** —
  `Impacts: rapid` does **not** match `impacts = ["api"]`
* a commit with no `Impacts:` footer is invisible to the package
* footer name is configurable via `impacts_footer` (e.g. `Affects`)

Tip: if a commit changes shared code that everyone re-releases, list a tag
that every package subscribes to (e.g. `commons`) and add it to each
package's `impacts` list.

## The `release-toolkit` CLI

Three subcommand groups: `increment` (used by `release` but also runnable by
hand), `init` for bootstrapping `[tool.commitizen]` into one or more
`pyproject.toml` files, and `release` for driving the actual release.

The CLI ships under two names — the full `release-toolkit` and the short
alias `rt` — both pointing at the same entry point. Examples below use the
full name; substitute `rt` for terseness (e.g. `rt release`).

### `increment`

```bash
release-toolkit increment [--config pyproject.toml]
```

Prints one of `MAJOR` / `MINOR` / `PATCH` / `NONE`. `NONE` means no commits
since the last matching tag survived the `changelog_pattern` filter — there
is nothing to release for this package. The `release` subcommand turns that
into an abort.

You can wire this into other release pipelines (Make, just, plain CI scripts)
by capturing stdout and feeding it to `cz bump --increment "$INCREMENT"`.

### `init single`

Inserts a default `[tool.commitizen]` section into one or more
`pyproject.toml` files for **single-package** repositories, and writes a
matching caller workflow at `<repo-root>/.github/workflows/release-notify.yml`:

```bash
release-toolkit init single ./pyproject.toml
# or many at once:
release-toolkit init single packages/a/pyproject.toml packages/b/pyproject.toml
```

The inserted section (plus a `release-toolkit>=X.Y.Z,<N+1` entry appended to
`[dependency-groups].dev` — see [Behaviour rules](#behaviour-rules-both-init-variants)
below):

```toml
[tool.commitizen]
name = "impacts_cz"
tag_format = "v$version"
changelog_file = "CHANGELOG.md"
update_changelog_on_bump = true
```

### `init monorepo`

Same idea, but each target gets a per-package `tag_format` and `impacts`
list, plus a per-package caller workflow at
`<repo-root>/.github/workflows/release-notify-<name>.yml`. Arguments are
positional **(PATH NAME)** pairs — the first item of each pair is a path to a
`pyproject.toml`, the second is the package name:

```bash
release-toolkit init monorepo \
  packages/client/pyproject.toml client \
  packages/service/pyproject.toml service
```

For the `client` pair above, the inserted section is (plus a
`release-toolkit>=X.Y.Z,<N+1` entry appended to `[dependency-groups].dev` —
see [Behaviour rules](#behaviour-rules-both-init-variants) below):

```toml
[tool.commitizen]
name = "impacts_cz"
tag_format = "client-v$version"
changelog_file = "CHANGELOG.md"
update_changelog_on_bump = true
impacts = ["client"]
```

Tune `impacts` (e.g. add a shared `commons` tag) and `ignored_tag_formats`
by hand afterwards — the command stays minimal on purpose.

### Behaviour rules (both `init` variants)

Per file, the `[tool.commitizen]` step does one of:

| State of `[tool.commitizen]`            | Action                                    | Stream |
| --------------------------------------- | ----------------------------------------- | ------ |
| absent                                  | insert default section                    | stdout `INFO`    |
| present, `name = "impacts_cz"`          | leave file unchanged                      | stdout `INFO`    |
| present, different (or missing) `name`  | leave file unchanged                      | stderr `WARNING` |
| file does not exist / TOML parse error  | leave file unchanged                      | stderr `ERROR`   |

The dev-dependency step (skipped only when the `[tool.commitizen]` step
returned `WARNING` for a foreign `name` — we leave foreign-configured files
fully alone) does one of:

| State of `[dependency-groups].dev`                  | Action                                        | Stream |
| --------------------------------------------------- | --------------------------------------------- | ------ |
| no `release-toolkit` entry (or no `dev` group at all) | append `release-toolkit>=X.Y.Z,<N+1`        | stdout `INFO`    |
| `release-toolkit` already present (any constraint)  | leave unchanged                               | stdout `INFO`    |

The workflow step (skipped only when the `[tool.commitizen]` step hit a hard
error for the same path) does one of:

| State of `<repo-root>/.github/workflows/`                                       | Action                              | Stream |
| ------------------------------------------------------------------------------- | ----------------------------------- | ------ |
| no file matches both `release-notify.yml@` and the requested `tag_prefix`       | create caller file                  | stdout `INFO`    |
| an existing file references `release-notify.yml@` with the same `tag_prefix`    | leave unchanged                     | stdout `INFO`    |
| target file name is occupied by an unrelated workflow                           | leave unchanged                     | stderr `WARNING` |
| repo root not found (no `.git` walking up from the `pyproject.toml` directory)  | leave workflow tree unchanged       | stderr `ERROR`   |

All paths are processed independently. The exit code is non-zero only when
at least one path hit a hard error (missing file, parse failure, repo root
not found); warnings alone keep the exit code at 0.

### `release`

Drives the full release flow from one command. Run it from the package
directory (the one that contains the `pyproject.toml` with
`[tool.commitizen]`):

```bash
release-toolkit release [--master-branch BRANCH] [--no-filter] [-- <bump-args>]
```

What it does, in order:

1. `uv sync --group dev` so the toolchain is installed.
2. Refuses to run on a dirty worktree (`git status --porcelain`).
3. If on `--master-branch` (default: `master`), fast-forwards via
   `git pull --ff-only`. Otherwise logs a warning — useful for hotfix branches.
4. By default, computes the next increment with the changelog filter and
   aborts if it would be `NONE`. Pass `--no-filter` to skip this step (use it
   in single-package repos without `impacts`); `cz bump` then picks the
   increment itself.
5. Shows `cz bump --dry-run` output and asks for `[y/N]` confirmation.
6. Runs the real `cz bump`, then `git push --follow-tags`.

Anything after a `--` separator is forwarded to `cz bump`, so you can
override (e.g. `release-toolkit release -- --prerelease beta`).

The command exits with code 1 and an `ERROR:` line on stderr when a
precondition fails (dirty worktree, nothing to release) or the user declines
the confirmation prompt.

## GitHub building blocks

### `github/actions/setup-python-env`

Composite action that installs Python, `uv`, and `nox` at pinned versions.
Inputs: `python-version` (required), `uv-version`, `nox-version`. Use it from
your CI workflows when you need a Python+uv environment.

### `github/workflows/release-notify.yml`

Reusable workflow. Triggered when a release tag is pushed; it generates
release notes from `cz changelog`, creates a GitHub Release, and (optionally)
posts to Slack.

`release-toolkit init {single,monorepo}` generates the caller file for
you under `<repo-root>/.github/workflows/`; the example below is shown for
reference (and for the case where you want to write the caller by hand):

```yaml
name: CD Client

on:
  push:
    tags:
      - 'client-v*'

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

Inputs:

| name | required | default | meaning |
| ---- | -------- | ------- | ------- |
| `package_dir` | yes | — | Path to the package's `pyproject.toml`. |
| `tag_prefix` | yes | — | Tag prefix preceding the version (e.g. `client-v`, `v`). |
| `python_version` | no | `3.11` | Python used by `cz changelog`. |
| `slack_message_prefix` | no | `Released` | Prefix for the Slack message. |

The `SLACK_WEBHOOK_URL` secret is optional — when omitted, the Slack job logs
a `::notice::` and exits cleanly.

> ⚠️ Replace `your-org/release-toolkit` with the actual `<owner>/<repo>` path
> where this toolkit lives, and pin `@v1` (or a SHA) to a release you trust.

## Optional Slack

Already covered above; recap: provide `SLACK_WEBHOOK_URL` as a workflow secret
to enable, omit it to disable. There is no extra plugin to install.

## Examples in this repo

* `examples/monorepo/` — `pyproject.toml` and an example caller workflow
  (`.github-workflow-example.yml`) for a monorepo package using `hatch-vcs`
  versioning.
* `examples/single-package/` — same setup but for a single-package repo
  without `impacts`.

These files are intentionally minimal — copy the parts you need.

## Developing release-toolkit itself

```bash
uv sync --group dev
uv run pytest          # tests, including a tmp-git-repo fixture
uv run ruff check .
uv run pyright
```

Layout:

```
src/release_toolkit/
    __init__.py
    cz_plugin.py            # ImpactsCz, build_changelog_pattern
    helpers.py              # find_filtered_increment, load_config (pure)
    installer.py            # CommitizenConfig, install_into_document (pure)
    workflow_installer.py   # WorkflowConfig, render_workflow,
                            # is_release_notify_workflow (pure)
    cli.py                  # `release-toolkit` argparse + I/O (main entry point)
    release_runner.py       # run_release (subprocess orchestration)
tests/
    conftest.py             # GitRepo fixture
    test_cz_plugin.py
    test_helpers.py
    test_installer.py
    test_workflow_installer.py
    test_cli_init.py
github/
    actions/setup-python-env/
    workflows/release-notify.yml
```

The plugin is registered through the `commitizen.plugin` entry point in
`pyproject.toml`; do **not** import it from `release_toolkit/__init__.py` —
that would re-enter the package during Commitizen's entry-point discovery and
deadlock.

## FAQ / troubleshooting

**`release-toolkit increment` prints `NONE` but I just merged something.**
There are no commits matching the package's `Impacts:` filter since the last
package tag. Either your commit is missing the footer, or it lists tags this
package does not subscribe to.

**`cz bump` wants to bump but `increment` says `NONE`.**
That is the bug this toolkit fixes: vanilla `cz bump` ignores
`changelog_pattern` for increment computation. Use `release-toolkit release`
(or feed `--increment` to `cz bump` yourself) so the filter is honored.

**Can I use a footer name other than `Impacts`?**
Yes — set `impacts_footer = "Affects"` (or anything) under `[tool.commitizen]`.
The regex escapes special characters, so even unusual names work.

**Is the plugin compatible with `bump_pattern` / breaking-change detection?**
Yes — it is a thin subclass of `ConventionalCommitsCz` that only rewrites
`changelog_pattern`. `bump_pattern`, `bump_map`, `change_type_map`, etc. are
inherited as-is.
