"""Reusable Nox session implementing the release flow used in pylon.

Usage in a per-package ``noxfile.py``::

    import nox
    from release_toolkit.nox_release import release_session

    @nox.session(name="release", python=False, default=False)
    def release(session):
        release_session(session)

The session:

1. ``uv sync --group dev`` to make sure tooling is installed.
2. Refuses to run on a dirty worktree.
3. Pulls ``master`` (warning if you are on another branch).
4. Computes the next increment respecting the ``impacts`` filter (monorepo-safe).
5. Shows ``cz bump --dry-run``, asks for confirmation, then bumps and pushes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import nox


def release_session(
    session: nox.Session,
    *,
    master_branch: str = "master",
    use_filter: bool = True,
    sync_args: tuple[str, ...] = ("--group", "dev"),
) -> None:
    """Run the standard release workflow inside a Nox session.

    Args:
        session: The active Nox session.
        master_branch: Branch expected to host releases.
        use_filter: When True, use ``cz-release-toolkit increment`` so that
            monorepo packages skip increments triggered by sibling-only commits.
            Set to False for single-package repos that do not configure
            ``impacts``.
        sync_args: Extra args for ``uv sync``. Defaults to ``("--group", "dev")``.
    """
    session.run("uv", "sync", *sync_args)

    dirty = session.run("git", "status", "--porcelain", silent=True, external=True).strip()
    if dirty:
        session.error("Release requires a clean worktree.")

    branch = session.run("git", "branch", "--show-current", silent=True, external=True).strip()
    if branch == master_branch:
        session.run("git", "pull", "--ff-only", "origin", master_branch, external=True)
    else:
        session.log(f"WARNING: releasing from {branch or 'detached HEAD'} instead of {master_branch}.")

    bump_args: list[str] = list(session.posargs)
    if use_filter:
        increment = session.run(
            "uv", "run", "cz-release-toolkit", "increment", silent=True
        ).strip()
        if increment == "NONE":
            session.error("No releasable commits found for this package.")
        session.log(f"Detected filtered increment: {increment}")
        bump_args = ["--increment", increment, *bump_args]

    dry_run_output = session.run("uv", "run", "cz", "bump", "--dry-run", *bump_args, silent=True)
    print(dry_run_output)

    confirmation_prompt = "Create release commit and tag, then push them? [y/N] "
    if branch != master_branch:
        confirmation_prompt = (
            f"WARNING: releasing from {branch or 'detached HEAD'} instead of {master_branch}.\n{confirmation_prompt}"
        )
    if input(confirmation_prompt).lower() != "y":
        session.error("Aborted by user")

    session.run("uv", "run", "cz", "bump", *bump_args)
    session.run("git", "push", "origin", "HEAD", "--follow-tags", external=True)
