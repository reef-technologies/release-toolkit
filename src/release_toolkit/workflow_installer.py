"""Pure logic for rendering and identifying the release caller workflow.

This module is intentionally I/O- and CLI-free: callers (the CLI layer) discover
the repo root, scan ``.github/workflows`` themselves, hand the file content to
:func:`is_release_workflow_caller`, and write whatever :func:`render_workflow`
returns. The same separation as :mod:`release_toolkit.installer`.

The reusable workflow upstream is still named ``release-notify.yml@v1`` for
backwards compatibility (it is a versioned external resource), even though the
locally-generated caller files are named ``release.yml`` /
``release-{name}.yml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

RELEASE_WORKFLOW_USES_PREFIX = (
    "reef-technologies/release-toolkit/.github/workflows/release-notify.yml@"
)
RELEASE_WORKFLOW_USES_REF = f"{RELEASE_WORKFLOW_USES_PREFIX}v0.2.0"


@dataclass(frozen=True)
class WorkflowConfig:
    """Desired contents of a release caller workflow.

    Attributes:
        package_dir: Value passed as ``with.package_dir`` (path to the package
            directory containing ``pyproject.toml``, relative to repo root).
        tag_prefix: Value passed as ``with.tag_prefix`` (e.g. ``"v"`` or
            ``"client-v"``). Also used to build the ``on.push.tags`` glob.
        workflow_name: Top-level ``name:`` of the workflow.
        file_name: File name to write under ``.github/workflows/``.
    """

    package_dir: str
    tag_prefix: str
    workflow_name: str
    file_name: str

    @classmethod
    def for_single(cls, package_dir: str = ".") -> WorkflowConfig:
        """Return the config for a single-package repo (tag_prefix ``v``)."""
        return cls(
            package_dir=package_dir,
            tag_prefix="v",
            workflow_name="Release",
            file_name="release.yml",
        )

    @classmethod
    def for_monorepo(cls, project_name: str, package_dir: str) -> WorkflowConfig:
        """Return the config for a monorepo package owned by ``project_name``."""
        return cls(
            package_dir=package_dir,
            tag_prefix=f"{project_name}-v",
            workflow_name=f"Release ({project_name})",
            file_name=f"release-{project_name}.yml",
        )


class WorkflowInstallStatus(Enum):
    """Outcome of attempting to install a release caller workflow."""

    INSTALLED = "installed"
    ALREADY_INSTALLED = "already_installed"
    FILE_NAME_CONFLICT = "file_name_conflict"


def render_workflow(config: WorkflowConfig) -> str:
    """Render a release caller workflow as YAML text.

    The output mirrors ``examples/monorepo/.github-workflow-example.yml`` but
    with values filled in from ``config``. The result ends with a trailing
    newline so writing it produces a POSIX-friendly file.
    """
    return f"""\
name: {config.workflow_name}

on:
  push:
    tags:
      - '{config.tag_prefix}*'

permissions:
  contents: read

jobs:
  release:
    uses: {RELEASE_WORKFLOW_USES_REF}
    with:
      package_dir: {config.package_dir}
      tag_prefix: {config.tag_prefix}
      python_version: '3.11'
    secrets:
      SLACK_WEBHOOK_URL: ${{{{ secrets.SLACK_WEBHOOK_URL }}}}
    permissions:
      contents: write
"""


def is_release_workflow_caller(yaml_text: str) -> bool:
    """Return True when ``yaml_text`` calls the release-toolkit reusable workflow.

    Detection is a substring match on :data:`RELEASE_WORKFLOW_USES_PREFIX`. The
    prefix is specific enough (full ``owner/repo/.github/workflows/file.yml@``
    path) that no parsing is needed.
    """
    return RELEASE_WORKFLOW_USES_PREFIX in yaml_text
