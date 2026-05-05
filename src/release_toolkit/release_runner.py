"""Standalone release workflow used by the ``cz-release-toolkit release`` CLI.

Steps: ``uv sync``, dirty-tree check, master fast-forward, optional filtered
increment, ``cz bump --dry-run`` preview, confirmation, real bump, push.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from release_toolkit.helpers import find_filtered_increment, load_config


class ReleaseAborted(Exception):
    """Raised when the release workflow stops on purpose (precondition failed or user said no)."""


def run_release(
    *,
    master_branch: str = "master",
    use_filter: bool = True,
    sync_args: Sequence[str] = ("--group", "dev"),
    bump_args: Sequence[str] = (),
) -> None:
    """Run the standard release workflow.

    Args:
        master_branch: Branch expected to host releases.
        use_filter: When True, compute the next increment with the
            ``impacts`` filter so that monorepo packages skip increments
            triggered by sibling-only commits. Set to False for
            single-package repos that do not configure ``impacts``.
        sync_args: Extra args for ``uv sync``. Defaults to ``("--group", "dev")``.
        bump_args: Extra args forwarded to ``cz bump`` (and its dry-run preview).

    Raises:
        ReleaseAborted: When a precondition fails (dirty worktree, nothing to
            release) or the user declines the confirmation prompt.
    """
    subprocess.run(["uv", "sync", *sync_args], check=True)

    dirty = subprocess.run(
        ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        raise ReleaseAborted("Release requires a clean worktree.")

    branch = subprocess.run(
        ["git", "branch", "--show-current"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if branch == master_branch:
        subprocess.run(["git", "pull", "--ff-only", "origin", master_branch], check=True)
    else:
        print(
            f"WARNING: releasing from {branch or 'detached HEAD'} instead of {master_branch}.",
            file=sys.stderr,
        )

    extra_bump_args: list[str] = list(bump_args)
    if use_filter:
        increment = find_filtered_increment(load_config(Path("pyproject.toml")))
        if increment is None:
            raise ReleaseAborted("No releasable commits found for this package.")
        print(f"Detected filtered increment: {increment}", file=sys.stderr)
        extra_bump_args = ["--increment", increment, *extra_bump_args]

    dry_run = subprocess.run(
        ["uv", "run", "cz", "bump", "--dry-run", *extra_bump_args],
        check=True,
        capture_output=True,
        text=True,
    )
    print(dry_run.stdout)

    confirmation_prompt = "Create release commit and tag, then push them? [y/N] "
    if branch != master_branch:
        confirmation_prompt = (
            f"WARNING: releasing from {branch or 'detached HEAD'} instead of {master_branch}.\n"
            f"{confirmation_prompt}"
        )
    if input(confirmation_prompt).lower() != "y":
        raise ReleaseAborted("Aborted by user")

    subprocess.run(["uv", "run", "cz", "bump", *extra_bump_args], check=True)
    subprocess.run(["git", "push", "origin", "HEAD", "--follow-tags"], check=True)


__all__ = ["ReleaseAborted", "run_release"]
