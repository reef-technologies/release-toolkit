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
    is_release_notify_workflow,
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
    config = CommitizenConfig.for_single()
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
    exit_code = 0
    for path, name in pairs:
        toml_ok = _apply_to_file(path, CommitizenConfig.for_monorepo(name), spec)
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
    """Install the release-notify caller workflow for ``pyproject_path``.

    Locates the repo root by walking up looking for ``.git``. When no repo root
    is found, returns ``False`` (hard error). When an existing workflow already
    references the release-notify reusable workflow (under any file name),
    skips with INFO. When the target file name is occupied by an unrelated
    workflow, skips with WARNING (still returns ``True`` - exit 0).
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
    existing = _find_existing_release_notify(workflows_dir, config.tag_prefix)
    if existing is not None:
        print(
            f"INFO: {existing}: release-notify workflow for tag_prefix "
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
    print(f"INFO: {target}: added release-notify caller workflow")
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


def _find_existing_release_notify(workflows_dir: Path, tag_prefix: str) -> Path | None:
    """Scan ``workflows_dir`` for an existing release-notify caller using ``tag_prefix``.

    A match requires both: the file references the reusable
    ``release-notify.yml`` workflow AND its rendered ``tag_prefix:`` line equals
    the requested one. This keeps per-package monorepo files independent: a
    ``release-notify-client.yml`` does not block creation of
    ``release-notify-service.yml``.
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
        if is_release_notify_workflow(content) and needle in content:
            return entry
    return None


def main() -> None:
    """Entry point for the ``release-toolkit`` console script."""
    parser = argparse.ArgumentParser(description="Release-toolkit CLI helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    increment_parser = subparsers.add_parser(
        "increment", help="Print the changelog-filtered Commitizen increment."
    )
    increment_parser.add_argument("--config", type=Path, default=Path("pyproject.toml"))
    increment_parser.set_defaults(func=cmd_increment)

    init_parser = subparsers.add_parser(
        "init",
        help=(
            "Install [tool.commitizen] into pyproject.toml files. "
            "Each PATH may point at a pyproject.toml file or at the directory containing one."
        ),
    )
    init_subparsers = init_parser.add_subparsers(dest="init_command", required=True)

    single_parser = init_subparsers.add_parser(
        "single",
        help=(
            "Install single-package config into each given pyproject.toml "
            "(PATH may be the file itself or its containing directory)."
        ),
    )
    single_parser.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    single_parser.set_defaults(func=cmd_init_single)

    monorepo_parser = init_subparsers.add_parser(
        "monorepo",
        help=(
            "Install monorepo config; arguments are PATH NAME pairs "
            "(PATH may be the pyproject.toml file or its containing directory)."
        ),
    )
    monorepo_parser.add_argument("args", nargs="+", metavar="PATH NAME")
    monorepo_parser.set_defaults(func=lambda a: cmd_init_monorepo(a, monorepo_parser))

    release_parser = subparsers.add_parser(
        "release",
        help="Run the standard release workflow (uv sync -> checks -> cz bump -> push).",
    )
    release_parser.add_argument("--master-branch", default="master")
    filter_group = release_parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        "--use-filter",
        dest="use_filter",
        action="store_true",
        default=True,
        help="(default) Use the changelog-filtered increment so monorepo packages skip "
        "increments triggered by sibling-only commits.",
    )
    filter_group.add_argument(
        "--no-filter",
        dest="use_filter",
        action="store_false",
        help="Skip the increment filter; let `cz bump` pick the increment itself "
        "(use for single-package repos without `impacts`).",
    )
    release_parser.add_argument(
        "bump_args",
        nargs=argparse.REMAINDER,
        help="Extra args forwarded to `cz bump` (separate with `--`).",
    )
    release_parser.set_defaults(func=cmd_release)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
