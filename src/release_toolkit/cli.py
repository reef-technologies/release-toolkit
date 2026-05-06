"""Argparse wiring and I/O for the ``release-toolkit`` console script.

This module is the only place that prints, reads files, writes files, or
exits. Pure increment computation lives in :mod:`release_toolkit.helpers`;
pure pyproject mutation lives in :mod:`release_toolkit.installer`; pure
workflow rendering lives in :mod:`release_toolkit.workflow_installer`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError

from release_toolkit.helpers import NO_INCREMENT, find_filtered_increment, load_config
from release_toolkit.installer import (
    RELEASE_TOOLKIT_PACKAGE,
    CommitizenConfig,
    DevDepStatus,
    InstallStatus,
    compute_release_toolkit_spec,
    ensure_dev_dependency,
    install_into_document,
)
from release_toolkit.release_runner import ReleaseAborted, run_release
from release_toolkit.workflow_installer import (
    WorkflowConfig,
    is_release_workflow_caller,
    render_workflow,
)


def cmd_increment(args: argparse.Namespace) -> None:
    """Print the changelog-filtered Commitizen increment for ``args.config``."""
    increment = find_filtered_increment(load_config(args.config))
    print(increment or NO_INCREMENT)


def cmd_release(args: argparse.Namespace) -> None:
    """Run the standard release workflow; exit 1 with a stderr message on abort."""
    bump_args = list(args.bump_args)
    if bump_args and bump_args[0] == "--":
        bump_args = bump_args[1:]
    try:
        run_release(
            master_branch=args.master_branch,
            use_filter=args.use_filter,
            bump_args=tuple(bump_args),
        )
    except ReleaseAborted as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_init_single(args: argparse.Namespace) -> None:
    """Run ``init single`` for each given ``pyproject.toml`` path."""
    config = CommitizenConfig.for_single(version_provider=args.version_provider)
    spec = _resolve_release_toolkit_spec()
    exit_code = 0
    for raw_path in args.paths:
        path = _resolve_pyproject_path(raw_path)
        toml_ok = _apply_to_file(path, config, spec)
        if not toml_ok:
            exit_code = 1
            continue
        if not _apply_workflow(path, _make_single_workflow_config):
            exit_code = 1
    if exit_code:
        sys.exit(exit_code)
    _print_slack_next_steps()


def cmd_init_monorepo(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Run ``init monorepo`` for each ``(path, name)`` pair from positional args."""
    raw = args.args
    if len(raw) % 2:
        parser.error("monorepo requires PATH NAME pairs (even number of arguments)")
    pairs = [
        (_resolve_pyproject_path(Path(raw[i])), raw[i + 1])
        for i in range(0, len(raw), 2)
    ]
    spec = _resolve_release_toolkit_spec()
    version_provider = args.version_provider
    exit_code = 0
    for path, name in pairs:
        config = CommitizenConfig.for_monorepo(name, version_provider=version_provider)
        toml_ok = _apply_to_file(path, config, spec)
        if not toml_ok:
            exit_code = 1
            continue
        if not _apply_workflow(path, lambda pkg_dir, _name=name: WorkflowConfig.for_monorepo(_name, pkg_dir)):
            exit_code = 1
    if exit_code:
        sys.exit(exit_code)
    _print_slack_next_steps()


def _apply_to_file(path: Path, config: CommitizenConfig, release_toolkit_spec: str) -> bool:
    """Apply ``install_into_document`` and ``ensure_dev_dependency`` to ``path``.

    Prints one status line per step (commitizen section + dev-dependency
    entry). Returns ``True`` for INSTALLED / ALREADY_INSTALLED / FOREIGN_NAME
    outcomes (warnings included). Returns ``False`` only on hard errors (file
    missing, TOML parse failure) so the caller can aggregate a non-zero exit
    code. The dev-dependency step runs only when the commitizen step did not
    return ``FOREIGN_NAME`` (we leave foreign-configured files alone).
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        print(f"ERROR: {path}: file not found", file=sys.stderr)
        return False
    try:
        doc = tomlkit.parse(text)
    except TOMLKitError as exc:
        print(f"ERROR: {path}: cannot parse TOML ({exc})", file=sys.stderr)
        return False

    cz_result = install_into_document(doc, config)
    document_changed = False
    match cz_result.status:
        case InstallStatus.INSTALLED:
            print(f"INFO: {path}: added default [tool.commitizen] section")
            document_changed = True
        case InstallStatus.ALREADY_INSTALLED:
            print(f"INFO: {path}: already installed, skipping")
        case InstallStatus.FOREIGN_NAME:
            print(
                f"WARNING: {path}: [tool.commitizen] has name='{cz_result.existing_name}' "
                f"(expected 'impacts_cz'), skipping",
                file=sys.stderr,
            )

    if cz_result.status is not InstallStatus.FOREIGN_NAME:
        dev_result = ensure_dev_dependency(doc, release_toolkit_spec, RELEASE_TOOLKIT_PACKAGE)
        if dev_result.status is DevDepStatus.ADDED:
            print(f"INFO: {path}: added '{dev_result.spec_written}' to [dependency-groups].dev")
            document_changed = True
        else:
            print(
                f"INFO: {path}: release-toolkit already present in [dependency-groups].dev, skipping"
            )

    if document_changed:
        path.write_text(tomlkit.dumps(doc))
    return True


def _resolve_release_toolkit_spec() -> str:
    """Compute the spec to inject, warning once per call when the version is unknown."""
    version = _resolve_release_toolkit_version()
    if version is None:
        print(
            "WARNING: could not detect installed release-toolkit version; "
            "writing unbounded spec — install via 'uv tool install release-toolkit' "
            "to get a version cap",
            file=sys.stderr,
        )
    return compute_release_toolkit_spec(version)


def _resolve_release_toolkit_version() -> str | None:
    """Return the installed ``release-toolkit`` version, or ``None`` when unavailable."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(RELEASE_TOOLKIT_PACKAGE)
    except PackageNotFoundError:
        return None


def _apply_workflow(
    pyproject_path: Path,
    config_factory,
) -> bool:
    """Install the release caller workflow for ``pyproject_path``.

    Locates the repo root by walking up looking for ``.git``. When no repo root
    is found, returns ``False`` (hard error). When an existing workflow already
    calls the release-toolkit reusable workflow (under any file name), skips
    with INFO. When the target file name is occupied by an unrelated workflow,
    skips with WARNING (still returns ``True`` - exit 0).
    """
    repo_root = _find_repo_root(pyproject_path.resolve().parent)
    if repo_root is None:
        print(
            f"ERROR: {pyproject_path}: could not locate repo root (no .git found)",
            file=sys.stderr,
        )
        return False

    package_dir = _relative_package_dir(repo_root, pyproject_path)
    config = config_factory(package_dir)

    workflows_dir = repo_root / ".github" / "workflows"
    existing = _find_existing_release_caller(workflows_dir, config.tag_prefix)
    if existing is not None:
        print(
            f"INFO: {existing}: release workflow for tag_prefix "
            f"'{config.tag_prefix}' already present, skipping"
        )
        return True

    target = workflows_dir / config.file_name
    if target.exists():
        print(
            f"WARNING: {target}: file exists with unrelated content, skipping",
            file=sys.stderr,
        )
        return True

    workflows_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(render_workflow(config))
    print(f"INFO: {target}: added release caller workflow")
    return True


def _make_single_workflow_config(package_dir: str) -> WorkflowConfig:
    """Factory used by ``cmd_init_single`` to bind ``package_dir`` to a config."""
    return WorkflowConfig.for_single(package_dir)


def _print_slack_next_steps() -> None:
    """Print follow-up reminders: Slack setup and version_provider customisation."""
    print()
    print("NEXT STEPS - to enable Slack notifications:")
    print("  1. Create a Slack incoming webhook URL")
    print("     (https://api.slack.com/messaging/webhooks).")
    print("  2. In your GitHub repo: Settings -> Secrets and variables -> Actions,")
    print("     add a repository secret named SLACK_WEBHOOK_URL with that URL.")
    print("Without the secret, the release workflow still succeeds; Slack is just skipped.")
    print()
    print("NEXT STEPS - version source:")
    print("  Default version_provider is 'pep621' (reads/writes [project].version in")
    print("  pyproject.toml). To version from another source (git tags, package.json,")
    print("  Cargo.toml, ...), change [tool.commitizen].version_provider — see:")
    print("  https://commitizen-tools.github.io/commitizen/config/version_provider/#built-in-providers")


def _find_repo_root(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a ``.git`` entry; return parent dir or None."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _resolve_pyproject_path(path: Path) -> Path:
    """Return the ``pyproject.toml`` file path for a user-supplied ``path``.

    When ``path`` is an existing directory, append ``pyproject.toml``. Otherwise
    return ``path`` unchanged so existing error messages (file not found, TOML
    parse failure) are emitted by the downstream apply step.
    """
    if path.is_dir():
        return path / "pyproject.toml"
    return path


def _relative_package_dir(repo_root: Path, pyproject_path: Path) -> str:
    """Return ``pyproject_path``'s parent directory relative to ``repo_root`` as a POSIX string."""
    package_dir = pyproject_path.resolve().parent
    rel = package_dir.relative_to(repo_root.resolve())
    rel_str = rel.as_posix()
    return rel_str if rel_str != "" else "."


def _find_existing_release_caller(workflows_dir: Path, tag_prefix: str) -> Path | None:
    """Scan ``workflows_dir`` for an existing release caller using ``tag_prefix``.

    A match requires both: the file calls the release-toolkit reusable workflow
    AND its rendered ``tag_prefix:`` line equals the requested one. This keeps
    per-package monorepo files independent: a ``release-client.yml`` does not
    block creation of ``release-service.yml``.
    """
    if not workflows_dir.is_dir():
        return None
    needle = f"tag_prefix: {tag_prefix}"
    for entry in sorted(workflows_dir.iterdir()):
        if entry.suffix not in (".yml", ".yaml") or not entry.is_file():
            continue
        try:
            content = entry.read_text()
        except OSError:
            continue
        if is_release_workflow_caller(content) and needle in content:
            return entry
    return None


def main() -> None:
    """Entry point for the ``release-toolkit`` console script."""
    parser = argparse.ArgumentParser(
        description=(
            "rt - Commitizen-based release automation: compute changelog-filtered "
            "version increments, bootstrap [tool.commitizen] config and GitHub release "
            "workflows in single- and multi-package repos, and run the bump-and-push "
            "release flow."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    increment_parser = subparsers.add_parser(
        "increment",
        help="Print the changelog-filtered Commitizen increment, or NO_INCREMENT if none applies.",
        description=(
            "Compute the next Commitizen increment for the project at --config and print "
            "it on stdout. The result is filtered by [tool.commitizen.changelog_pattern] "
            "/ [tool.commitizen.impacts]: commits that don't match are discarded before "
            "Commitizen picks an increment, so monorepo packages ignore sibling-only "
            "commits. When nothing remains, prints the literal token NO_INCREMENT - CI "
            "hooks consume that to decide whether to skip a release."
        ),
    )
    increment_parser.add_argument(
        "--config",
        type=Path,
        default=Path("pyproject.toml"),
        metavar="PATH",
        help="Path to a pyproject.toml containing a [tool.commitizen] section (default: ./pyproject.toml).",
    )
    increment_parser.set_defaults(func=cmd_increment)

    init_parser = subparsers.add_parser(
        "init",
        help="Bootstrap [tool.commitizen] config, dev-dependency entry, and GitHub release workflow.",
        description=(
            "Configure a repository for release-toolkit. For each target pyproject.toml, "
            "init (1) writes a default [tool.commitizen] block with name='impacts_cz', "
            "(2) adds release-toolkit to the [dependency-groups].dev list, and (3) "
            "installs a GitHub release-caller workflow under .github/workflows/. Use "
            "'single' for one-package repos and 'monorepo' for multi-package repos where "
            "each package needs its own tag prefix and workflow file. All steps are "
            "idempotent - re-running on an already-configured project skips with INFO."
        ),
    )
    init_subparsers = init_parser.add_subparsers(dest="init_command", required=True)

    single_parser = init_subparsers.add_parser(
        "single",
        help="Configure a single-package repo (one pyproject.toml, one workflow).",
        description=(
            "Configure one or more single-package projects. Each PATH may be a "
            "pyproject.toml file or a directory containing one. For each target, writes "
            "[tool.commitizen] (name='impacts_cz', tag_prefix='v'), adds release-toolkit "
            "to [dependency-groups].dev, and installs .github/workflows/release.yml. "
            "Idempotent: already-configured targets are reported with INFO and skipped; "
            "a foreign [tool.commitizen] section (different name) triggers a WARNING and "
            "is left untouched."
        ),
    )
    single_parser.add_argument(
        "--version-provider",
        dest="version_provider",
        default=None,
        metavar="PROVIDER",
        help=(
            "Override [tool.commitizen].version_provider; written verbatim "
            "(default: pep621). See https://commitizen-tools.github.io/commitizen/config/version_provider/."
        ),
    )
    single_parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="One or more pyproject.toml files, or directories containing one.",
    )
    single_parser.set_defaults(func=cmd_init_single)

    monorepo_parser = init_subparsers.add_parser(
        "monorepo",
        help="Configure a multi-package repo: one PATH NAME pair per package.",
        description=(
            "Configure each package in a monorepo. Arguments come in PATH NAME pairs: "
            "PATH points at a package's pyproject.toml (or its directory); NAME is the "
            "package identifier used as the Commitizen name and the tag prefix (e.g. "
            "NAME=backend yields tags 'backend-vX.Y.Z' and workflow file "
            "release-backend.yml). For each pair, writes [tool.commitizen], adds "
            "release-toolkit to [dependency-groups].dev, and installs a per-package "
            "release-caller workflow. Idempotent: existing matching configurations are "
            "skipped with INFO."
        ),
    )
    monorepo_parser.add_argument(
        "--version-provider",
        dest="version_provider",
        default=None,
        metavar="PROVIDER",
        help=(
            "Override [tool.commitizen].version_provider; written verbatim "
            "(default: pep621). See https://commitizen-tools.github.io/commitizen/config/version_provider/."
        ),
    )
    monorepo_parser.add_argument(
        "args",
        nargs="+",
        metavar="PATH NAME",
        help=(
            "PATH NAME pairs: each PATH is a pyproject.toml (or its directory); each "
            "NAME is the package identifier used for the tag prefix and workflow file name."
        ),
    )
    monorepo_parser.set_defaults(func=lambda a: cmd_init_monorepo(a, monorepo_parser))

    release_parser = subparsers.add_parser(
        "release",
        help="Run the standard release: uv sync, project checks, cz bump, push commit + tag.",
        description=(
            "Run the standard release flow end-to-end: sync the environment with uv,\n"
            "run the project's checks, invoke 'cz bump' with the changelog-filtered\n"
            "increment, then push the bump commit and the new tag to --master-branch.\n"
            "Aborts (exit 1) if the working tree is dirty or there are no releasable\n"
            "commits. When run from a branch other than --master-branch, prints a\n"
            "warning and prompts for confirmation rather than aborting."
        ),
        epilog=(
            "Examples:\n"
            "  rt release                              # default flow on master\n"
            "  rt release -- --dry-run                 # forward --dry-run to cz bump\n"
            "  rt release --master-branch main --no-filter\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    release_parser.add_argument(
        "--master-branch",
        default="master",
        metavar="BRANCH",
        help="Branch to push the bump commit and tag to (default: master).",
    )
    filter_group = release_parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        "--use-filter",
        dest="use_filter",
        action="store_true",
        default=True,
        help=(
            "Use the changelog-filtered increment so monorepo packages skip increments "
            "triggered by sibling-only commits (default)."
        ),
    )
    filter_group.add_argument(
        "--no-filter",
        dest="use_filter",
        action="store_false",
        help=(
            "Skip the increment filter and let 'cz bump' pick the increment itself; "
            "intended for single-package repos without [tool.commitizen.impacts]."
        ),
    )
    release_parser.add_argument(
        "bump_args",
        nargs=argparse.REMAINDER,
        help=(
            "Extra arguments forwarded to 'cz bump'; separate from rt's own flags with "
            "'--' (e.g. 'rt release -- --dry-run')."
        ),
    )
    release_parser.set_defaults(func=cmd_release)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
