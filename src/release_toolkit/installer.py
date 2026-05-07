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

import contextlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

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
        version_provider: Source from which commitizen reads (and writes) the
            project version. Defaults to ``"pep621"`` so the version lives in
            ``[project].version`` of ``pyproject.toml``.
        tag_format: Commitizen ``tag_format`` value (e.g. ``"v$version"`` or
            ``"client-v$version"``).
        annotated_tag: When ``True``, ``cz bump`` creates annotated git tags
            (``git tag -a``) instead of lightweight tags.
        changelog_file: Path to the changelog file.
        update_changelog_on_bump: Whether commitizen should rewrite the
            changelog on bump.
        changelog_merge_prerelease: When ``True``, prerelease entries are
            merged into the next stable release section in the changelog.
        bump_message: Optional override for the bump commit message. When
            ``None``, commitizen uses its built-in default. Only the
            ``$current_version`` and ``$new_version`` placeholders are
            supported by commitizen.
        impacts: Optional tuple of impact tags. When non-empty, the key is
            emitted; when empty, omitted entirely.
        major_version_zero: When ``True``, ``major_version_zero = true`` is
            written into the section so commitizen treats BREAKING CHANGEs
            as minor bumps (``0.1.0 -> 0.2.0``) instead of major bumps
            (``0.1.0 -> 1.0.0``). When ``None``, the key is omitted entirely
            (commitizen default applies). Set by the CLI after detecting the
            current project version.
    """

    name: str = IMPACTS_CZ_NAME
    version_provider: str = "pep621"
    tag_format: str = "v$version"
    annotated_tag: bool = True
    changelog_file: str = "CHANGELOG.md"
    update_changelog_on_bump: bool = True
    changelog_merge_prerelease: bool = True
    bump_message: str | None = None
    impacts: tuple[str, ...] = field(default_factory=tuple)
    major_version_zero: bool | None = None

    @classmethod
    def for_single(cls, version_provider: str | None = None) -> CommitizenConfig:
        """Return the default config for a single-package project.

        ``version_provider`` overrides the default (``"pep621"``) when given;
        the value is written verbatim to ``[tool.commitizen].version_provider``.
        """
        if version_provider is None:
            return cls()
        return cls(version_provider=version_provider)

    @classmethod
    def for_monorepo(
        cls, project_name: str, version_provider: str | None = None
    ) -> CommitizenConfig:
        """Return the default config for a monorepo package owned by ``project_name``.

        ``version_provider`` overrides the default (``"pep621"``) when given.
        """
        defaults = cls()
        return cls(
            version_provider=version_provider or defaults.version_provider,
            tag_format=f"{project_name}-v$version",
            bump_message=f"bump: {project_name} $current_version -> $new_version",
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

    Keys are emitted in a fixed, readable order: ``name``, ``version_provider``,
    ``tag_format``, ``annotated_tag``, ``changelog_file``,
    ``update_changelog_on_bump``, ``changelog_merge_prerelease``, then
    ``major_version_zero`` only when set, ``bump_message`` only when set, and
    ``impacts`` only when non-empty.
    """
    table = tomlkit.table()
    table["name"] = config.name
    table["version_provider"] = config.version_provider
    table["tag_format"] = config.tag_format
    table["annotated_tag"] = config.annotated_tag
    table["changelog_file"] = config.changelog_file
    table["update_changelog_on_bump"] = config.update_changelog_on_bump
    table["changelog_merge_prerelease"] = config.changelog_merge_prerelease
    if config.major_version_zero is not None:
        table["major_version_zero"] = config.major_version_zero
    if config.bump_message is not None:
        table["bump_message"] = config.bump_message
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


class VersionZeroState(Enum):
    """Classification of a project's current version against the ``0.Y.Z`` pre-stable range.

    Drives the decision to insert ``major_version_zero = true`` into the
    ``[tool.commitizen]`` section and the wording of the matching NEXT STEPS
    block printed by the CLI.
    """

    ZERO = "zero"
    NON_ZERO = "non_zero"
    UNKNOWN = "unknown"


def classify_version_zero(pyproject_path: Path) -> VersionZeroState:
    """Classify the current project version against the ``0.Y.Z`` range.

    ``pyproject_path`` MUST point at a file whose basename is exactly
    ``pyproject.toml`` - file-based commitizen providers (``pep621``,
    ``npm``, ``cargo``, ...) look up their files via ``Path() /
    "pyproject.toml"`` relative to cwd, so any other name yields
    :attr:`VersionZeroState.UNKNOWN`. The lookup runs with cwd temporarily
    switched to ``pyproject_path.parent`` so context-based providers
    (``scm``) inspect the surrounding git repository.

    Returns ``ZERO`` when the version's leading numeric component is ``0``,
    ``NON_ZERO`` when it is a positive integer, and ``UNKNOWN`` for any
    failure (provider raised, version string has no leading integer, etc.).
    """
    try:
        from commitizen.config.factory import create_config
        from commitizen.providers import get_provider
    except Exception:
        return VersionZeroState.UNKNOWN

    try:
        data = pyproject_path.read_bytes()
    except OSError:
        return VersionZeroState.UNKNOWN

    try:
        config = create_config(data=data, path=pyproject_path)
    except Exception:
        return VersionZeroState.UNKNOWN

    try:
        with contextlib.chdir(pyproject_path.parent):
            provider = get_provider(config)
            version = provider.get_version()
    except Exception:
        return VersionZeroState.UNKNOWN

    if not isinstance(version, str):
        return VersionZeroState.UNKNOWN
    match = _LEADING_MAJOR_RE.match(version)
    if match is None:
        return VersionZeroState.UNKNOWN
    return VersionZeroState.ZERO if int(match.group(1)) == 0 else VersionZeroState.NON_ZERO
