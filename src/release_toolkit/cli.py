"""Argparse wiring and I/O for the ``cz-release-toolkit`` console script.

This module is the only place that prints, reads files, writes files, or
exits. Pure increment computation lives in :mod:`release_toolkit.helpers`;
pure pyproject mutation lives in :mod:`release_toolkit.installer`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError

from release_toolkit.helpers import NO_INCREMENT, find_filtered_increment, load_config
from release_toolkit.installer import (
    CommitizenConfig,
    InstallStatus,
    install_into_document,
)


def cmd_increment(args: argparse.Namespace) -> None:
    """Print the changelog-filtered Commitizen increment for ``args.config``."""
    increment = find_filtered_increment(load_config(args.config))
    print(increment or NO_INCREMENT)


def cmd_init_single(args: argparse.Namespace) -> None:
    """Run ``init single`` for each given ``pyproject.toml`` path."""
    config = CommitizenConfig.for_single()
    exit_code = 0
    for path in args.paths:
        if not _apply_to_file(path, config):
            exit_code = 1
    if exit_code:
        sys.exit(exit_code)


def cmd_init_monorepo(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Run ``init monorepo`` for each ``(path, name)`` pair from positional args."""
    raw = args.args
    if len(raw) % 2:
        parser.error("monorepo requires PATH NAME pairs (even number of arguments)")
    pairs = [(Path(raw[i]), raw[i + 1]) for i in range(0, len(raw), 2)]
    exit_code = 0
    for path, name in pairs:
        if not _apply_to_file(path, CommitizenConfig.for_monorepo(name)):
            exit_code = 1
    if exit_code:
        sys.exit(exit_code)


def _apply_to_file(path: Path, config: CommitizenConfig) -> bool:
    """Apply ``install_into_document`` to ``path``, printing a status line.

    Returns ``True`` for INSTALLED / ALREADY_INSTALLED / FOREIGN_NAME outcomes
    (warnings included). Returns ``False`` only on hard errors (file missing,
    TOML parse failure) so the caller can aggregate a non-zero exit code.
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

    result = install_into_document(doc, config)
    match result.status:
        case InstallStatus.INSTALLED:
            path.write_text(tomlkit.dumps(doc))
            print(f"INFO: {path}: added default [tool.commitizen] section")
        case InstallStatus.ALREADY_INSTALLED:
            print(f"INFO: {path}: already installed, skipping")
        case InstallStatus.FOREIGN_NAME:
            print(
                f"WARNING: {path}: [tool.commitizen] has name='{result.existing_name}' "
                f"(expected 'impacts_cz'), skipping",
                file=sys.stderr,
            )
    return True


def main() -> None:
    """Entry point for the ``cz-release-toolkit`` console script."""
    parser = argparse.ArgumentParser(description="Release-toolkit CLI helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    increment_parser = subparsers.add_parser(
        "increment", help="Print the changelog-filtered Commitizen increment."
    )
    increment_parser.add_argument("--config", type=Path, default=Path("pyproject.toml"))
    increment_parser.set_defaults(func=cmd_increment)

    init_parser = subparsers.add_parser(
        "init", help="Install [tool.commitizen] into pyproject.toml files."
    )
    init_subparsers = init_parser.add_subparsers(dest="init_command", required=True)

    single_parser = init_subparsers.add_parser(
        "single", help="Install single-package config into each given pyproject.toml."
    )
    single_parser.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    single_parser.set_defaults(func=cmd_init_single)

    monorepo_parser = init_subparsers.add_parser(
        "monorepo",
        help="Install monorepo config; arguments are PATH NAME pairs.",
    )
    monorepo_parser.add_argument("args", nargs="+", metavar="PATH NAME")
    monorepo_parser.set_defaults(func=lambda a: cmd_init_monorepo(a, monorepo_parser))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
