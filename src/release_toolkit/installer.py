"""Pure logic for installing a commitizen configuration section into pyproject.toml.

This module is intentionally I/O- and CLI-free: callers (the CLI layer) read the
file, hand the parsed ``tomlkit`` document to ``install_into_document``, inspect
the returned ``InstallResult``, and decide what to print and whether to write
the document back to disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Table

IMPACTS_CZ_NAME = "impacts_cz"


@dataclass(frozen=True)
class CommitizenConfig:
    """Desired contents of the ``[tool.commitizen]`` section to install.

    Attributes:
        name: Plugin name; always ``"impacts_cz"`` in this toolkit.
        tag_format: Commitizen ``tag_format`` value (e.g. ``"v$version"`` or
            ``"client-v$version"``).
        changelog_file: Path to the changelog file.
        update_changelog_on_bump: Whether commitizen should rewrite the
            changelog on bump.
        impacts: Optional tuple of impact tags. When non-empty, the key is
            emitted; when empty, omitted entirely.
    """

    name: str = IMPACTS_CZ_NAME
    tag_format: str = "v$version"
    changelog_file: str = "CHANGELOG.md"
    update_changelog_on_bump: bool = True
    impacts: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def for_single(cls) -> CommitizenConfig:
        """Return the default config for a single-package project."""
        return cls()

    @classmethod
    def for_monorepo(cls, project_name: str) -> CommitizenConfig:
        """Return the default config for a monorepo package owned by ``project_name``."""
        return cls(
            tag_format=f"{project_name}-v$version",
            impacts=(project_name,),
        )


class InstallStatus(Enum):
    """Outcome of attempting to install a ``CommitizenConfig`` into a pyproject document."""

    INSTALLED = "installed"
    ALREADY_INSTALLED = "already_installed"
    FOREIGN_NAME = "foreign_name"


@dataclass(frozen=True)
class InstallResult:
    """Result of :func:`install_into_document`.

    Attributes:
        status: What happened (insert / skip / warn).
        existing_name: Value of ``[tool.commitizen].name`` when the existing
            section blocks installation (``status == FOREIGN_NAME``); ``None``
            otherwise, including when the existing section has no ``name`` key.
    """

    status: InstallStatus
    existing_name: str | None = None


def render_section(config: CommitizenConfig) -> Table:
    """Build the tomlkit ``Table`` for ``[tool.commitizen]`` from ``config``.

    Keys are emitted in a fixed, readable order: ``name``, ``tag_format``,
    ``changelog_file``, ``update_changelog_on_bump``, then ``impacts`` only
    when non-empty.
    """
    table = tomlkit.table()
    table["name"] = config.name
    table["tag_format"] = config.tag_format
    table["changelog_file"] = config.changelog_file
    table["update_changelog_on_bump"] = config.update_changelog_on_bump
    if config.impacts:
        impacts_array = tomlkit.array()
        impacts_array.extend(config.impacts)
        table["impacts"] = impacts_array
    return table


def install_into_document(doc: TOMLDocument, config: CommitizenConfig) -> InstallResult:
    """Mutate ``doc`` in place, inserting ``[tool.commitizen]`` when appropriate.

    Decision matrix on the existing ``[tool.commitizen]`` table:
      - absent -> insert section, return ``INSTALLED``.
      - present, ``name == "impacts_cz"`` -> no change, return ``ALREADY_INSTALLED``.
      - present, ``name`` differs or is missing -> no change, return
        ``FOREIGN_NAME`` (with ``existing_name`` set when a string ``name``
        is present).

    The document is mutated only when the status is ``INSTALLED``.
    """
    existing = _existing_commitizen_table(doc)
    if existing is not None:
        existing_name = existing.get("name")
        if isinstance(existing_name, str) and existing_name == config.name:
            return InstallResult(status=InstallStatus.ALREADY_INSTALLED)
        return InstallResult(
            status=InstallStatus.FOREIGN_NAME,
            existing_name=existing_name if isinstance(existing_name, str) else None,
        )

    tool_table = doc.get("tool")
    if tool_table is None:
        tool_table = tomlkit.table()
        doc["tool"] = tool_table
    tool_table["commitizen"] = render_section(config)
    return InstallResult(status=InstallStatus.INSTALLED)


def _existing_commitizen_table(doc: TOMLDocument) -> Table | None:
    """Return the existing ``[tool.commitizen]`` table when present, else ``None``."""
    tool = doc.get("tool")
    if tool is None:
        return None
    commitizen = tool.get("commitizen") if hasattr(tool, "get") else None
    if commitizen is None:
        return None
    return commitizen
