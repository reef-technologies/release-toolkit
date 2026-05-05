"""Pure logic for installing release-toolkit pieces into a ``pyproject.toml`` document.

This module is intentionally I/O- and CLI-free. Two independent pieces are
exposed:

* ``install_into_document`` — inserts the ``[tool.commitizen]`` section.
* ``ensure_dev_dependency`` — inserts (or skips) a ``release-toolkit`` entry
  in ``[dependency-groups].dev`` so that ``cz bump`` runs with the
  ``impacts_cz`` plugin available in the same environment as ``commitizen``.

Callers (the CLI layer) read the file, hand the parsed ``tomlkit`` document to
the relevant function, inspect the returned result, and decide what to print
and whether to write the document back to disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Array, Table

IMPACTS_CZ_NAME = "impacts_cz"
RELEASE_TOOLKIT_PACKAGE = "release-toolkit"

_LEADING_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_LEADING_MAJOR_RE = re.compile(r"^(\d+)")


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


class DevDepStatus(Enum):
    """Outcome of attempting to insert a dev-dependency entry into a pyproject document."""

    ADDED = "added"
    ALREADY_PRESENT = "already_present"


@dataclass(frozen=True)
class DevDepResult:
    """Result of :func:`ensure_dev_dependency`.

    Attributes:
        status: ``ADDED`` when the spec was inserted; ``ALREADY_PRESENT`` when
            an entry whose canonical project name matches ``package_name`` was
            already there (regardless of the existing constraint).
        spec_written: The exact spec string that ended up in (or matched
            within) the ``dev`` array.
    """

    status: DevDepStatus
    spec_written: str


def compute_release_toolkit_spec(installed_version: str | None) -> str:
    """Return the dependency spec to inject for ``release-toolkit``.

    When ``installed_version`` is a parseable PEP 440 version (a leading
    integer followed by ``.``), returns
    ``"release-toolkit>={installed_version},<{major+1}"``. When the version
    is ``None`` or its leading component is not parseable, returns the bare
    ``"release-toolkit"`` so the caller still produces a usable (if
    unbounded) entry.
    """
    if installed_version is None:
        return RELEASE_TOOLKIT_PACKAGE
    match = _LEADING_MAJOR_RE.match(installed_version)
    if match is None:
        return RELEASE_TOOLKIT_PACKAGE
    next_major = int(match.group(1)) + 1
    return f"{RELEASE_TOOLKIT_PACKAGE}>={installed_version},<{next_major}"


def ensure_dev_dependency(doc: TOMLDocument, spec: str, package_name: str) -> DevDepResult:
    """Insert ``spec`` into ``[dependency-groups].dev`` when ``package_name`` is absent.

    ``package_name`` is the canonical (PEP 503-normalized) project name used
    to detect an existing entry. Existing constraint suffixes (``>=...``,
    ``[extras]``, ``@ url``, etc.) on that name are honored as
    ``ALREADY_PRESENT`` without any rewrite. Creates ``[dependency-groups]``
    and the ``dev`` array when missing.
    """
    canonical_target = _normalize_distribution_name(package_name)

    groups = doc.get("dependency-groups")
    if groups is None:
        groups = tomlkit.table()
        doc["dependency-groups"] = groups

    dev = groups.get("dev") if hasattr(groups, "get") else None
    if dev is None:
        new_array = tomlkit.array()
        new_array.append(spec)
        groups["dev"] = new_array
        return DevDepResult(status=DevDepStatus.ADDED, spec_written=spec)

    for entry in dev:
        if not isinstance(entry, str):
            continue
        existing_canonical = _canonical_name(entry)
        if existing_canonical == canonical_target:
            return DevDepResult(status=DevDepStatus.ALREADY_PRESENT, spec_written=entry)

    _append_to_array(dev, spec)
    return DevDepResult(status=DevDepStatus.ADDED, spec_written=spec)


def _canonical_name(spec: str) -> str | None:
    """Extract and PEP 503-normalize the project name from a PEP 508-ish dep spec."""
    match = _LEADING_NAME_RE.match(spec)
    if match is None:
        return None
    return _normalize_distribution_name(match.group(1))


def _normalize_distribution_name(name: str) -> str:
    """Lower-case and collapse ``_``/``.``/``-`` runs to a single ``-`` (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _append_to_array(array: Array, spec: str) -> None:
    """Append ``spec`` to a tomlkit array, preserving multiline layout when present."""
    is_multiline = "\n" in array.as_string()
    if is_multiline:
        array.add_line(spec)
    else:
        array.append(spec)
