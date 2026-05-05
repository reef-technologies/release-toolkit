from __future__ import annotations

from typing import cast

import pytest
import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Table

from release_toolkit.installer import (
    CommitizenConfig,
    DevDepResult,
    DevDepStatus,
    InstallResult,
    InstallStatus,
    compute_release_toolkit_spec,
    ensure_dev_dependency,
    install_into_document,
)


def _commitizen(doc: TOMLDocument) -> Table:
    return cast(Table, cast(Table, doc["tool"])["commitizen"])


def _tool_ruff(doc: TOMLDocument) -> Table:
    return cast(Table, cast(Table, doc["tool"])["ruff"])


@pytest.fixture
def empty_pyproject() -> str:
    return '[project]\nname = "demo"\nversion = "0.1.0"\n'


@pytest.fixture
def already_installed_pyproject() -> str:
    return (
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
        '[tool.commitizen]\nname = "impacts_cz"\ntag_format = "v$version"\n'
    )


@pytest.fixture
def foreign_pyproject() -> str:
    return (
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
        '[tool.commitizen]\nname = "cz_conventional_commits"\n'
    )


@pytest.fixture
def commitizen_no_name_pyproject() -> str:
    return (
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
        '[tool.commitizen]\ntag_format = "v$version"\n'
    )


@pytest.fixture
def existing_tool_other_pyproject() -> str:
    return (
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
        '[tool.ruff]\nline-length = 120\n'
    )


@pytest.fixture
def commented_pyproject() -> str:
    return (
        "# top comment\n"
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
    )


class TestCommitizenConfigFactories:
    def test_for_single_returns_default_single_package_config(self):
        assert CommitizenConfig.for_single() == CommitizenConfig(
            name="impacts_cz",
            tag_format="v$version",
            changelog_file="CHANGELOG.md",
            update_changelog_on_bump=True,
            impacts=(),
        )

    def test_for_monorepo_uses_project_name_in_tag_format_and_impacts(self):
        assert CommitizenConfig.for_monorepo("client") == CommitizenConfig(
            name="impacts_cz",
            tag_format="client-v$version",
            changelog_file="CHANGELOG.md",
            update_changelog_on_bump=True,
            impacts=("client",),
        )


class TestInstallIntoDocument:
    def test_inserts_section_into_fresh_document_for_single(self, empty_pyproject):
        doc = tomlkit.parse(empty_pyproject)
        result = install_into_document(doc, CommitizenConfig.for_single())
        dumped = tomlkit.dumps(doc)

        assert result == InstallResult(status=InstallStatus.INSTALLED)
        section = _commitizen(doc)
        assert dict(section) == {
            "name": "impacts_cz",
            "tag_format": "v$version",
            "changelog_file": "CHANGELOG.md",
            "update_changelog_on_bump": True,
        }
        assert "impacts" not in section
        assert "impacts =" not in dumped

    def test_inserts_monorepo_section_with_impacts_and_no_ignored_tag_formats(self, empty_pyproject):
        doc = tomlkit.parse(empty_pyproject)
        result = install_into_document(doc, CommitizenConfig.for_monorepo("client"))
        dumped = tomlkit.dumps(doc)

        assert result == InstallResult(status=InstallStatus.INSTALLED)
        section = _commitizen(doc)
        assert section["tag_format"] == "client-v$version"
        assert list(cast(list[str], section["impacts"])) == ["client"]
        assert "ignored_tag_formats" not in section
        assert "ignored_tag_formats" not in dumped

    def test_already_installed_returns_skip_and_does_not_modify(self, already_installed_pyproject):
        doc = tomlkit.parse(already_installed_pyproject)
        result = install_into_document(doc, CommitizenConfig.for_single())

        assert result == InstallResult(status=InstallStatus.ALREADY_INSTALLED)
        assert tomlkit.dumps(doc) == already_installed_pyproject

    def test_foreign_name_returns_warning_and_does_not_modify(self, foreign_pyproject):
        doc = tomlkit.parse(foreign_pyproject)
        result = install_into_document(doc, CommitizenConfig.for_single())

        assert result == InstallResult(
            status=InstallStatus.FOREIGN_NAME,
            existing_name="cz_conventional_commits",
        )
        assert tomlkit.dumps(doc) == foreign_pyproject

    def test_existing_section_without_name_is_treated_as_foreign(self, commitizen_no_name_pyproject):
        doc = tomlkit.parse(commitizen_no_name_pyproject)
        result = install_into_document(doc, CommitizenConfig.for_single())

        assert result == InstallResult(status=InstallStatus.FOREIGN_NAME, existing_name=None)
        assert tomlkit.dumps(doc) == commitizen_no_name_pyproject

    def test_attaches_under_existing_tool_table_without_clobbering_siblings(
        self, existing_tool_other_pyproject
    ):
        doc = tomlkit.parse(existing_tool_other_pyproject)
        result = install_into_document(doc, CommitizenConfig.for_single())
        dumped = tomlkit.dumps(doc)

        assert result == InstallResult(status=InstallStatus.INSTALLED)
        assert _tool_ruff(doc)["line-length"] == 120
        assert _commitizen(doc)["name"] == "impacts_cz"
        assert "[tool.ruff]" in dumped
        assert "[tool.commitizen]" in dumped

    def test_preserves_top_level_comment(self, commented_pyproject):
        doc = tomlkit.parse(commented_pyproject)
        install_into_document(doc, CommitizenConfig.for_single())

        assert "# top comment" in tomlkit.dumps(doc)


class TestComputeReleaseToolkitSpec:
    @pytest.mark.parametrize(
        "installed,expected",
        [
            ("0.2.0", "release-toolkit>=0.2.0,<1"),
            ("1.4.2", "release-toolkit>=1.4.2,<2"),
            ("12.0.0", "release-toolkit>=12.0.0,<13"),
            ("2.0.0a1", "release-toolkit>=2.0.0a1,<3"),
            ("3.1.0.dev1", "release-toolkit>=3.1.0.dev1,<4"),
        ],
    )
    def test_caps_on_next_major(self, installed, expected):
        assert compute_release_toolkit_spec(installed) == expected

    def test_unknown_version_returns_bare_name(self):
        assert compute_release_toolkit_spec(None) == "release-toolkit"

    def test_unparseable_version_returns_bare_name(self):
        assert compute_release_toolkit_spec("garbage") == "release-toolkit"


class TestEnsureDevDependency:
    def test_creates_section_on_empty_doc(self, empty_pyproject):
        doc = tomlkit.parse(empty_pyproject)
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")
        dumped = tomlkit.dumps(doc)

        assert result == DevDepResult(
            status=DevDepStatus.ADDED,
            spec_written="release-toolkit>=0.2.0,<1",
        )
        assert "[dependency-groups]" in dumped
        assert '"release-toolkit>=0.2.0,<1"' in dumped

    def test_creates_dev_group_when_only_other_groups_exist(self):
        doc = tomlkit.parse(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\nci = ["nox"]\n'
        )
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")
        dumped = tomlkit.dumps(doc)

        assert result == DevDepResult(
            status=DevDepStatus.ADDED,
            spec_written="release-toolkit>=0.2.0,<1",
        )
        assert '"nox"' in dumped
        assert '"release-toolkit>=0.2.0,<1"' in dumped

    def test_appends_to_existing_dev_group(self):
        doc = tomlkit.parse(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["pytest>=8"]\n'
        )
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")
        dumped = tomlkit.dumps(doc)

        assert result.status == DevDepStatus.ADDED
        assert '"pytest>=8"' in dumped
        assert '"release-toolkit>=0.2.0,<1"' in dumped

    def test_already_present_with_same_constraint_is_skip(self):
        original = (
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["release-toolkit>=0.2.0,<1"]\n'
        )
        doc = tomlkit.parse(original)
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")

        assert result == DevDepResult(
            status=DevDepStatus.ALREADY_PRESENT,
            spec_written="release-toolkit>=0.2.0,<1",
        )
        assert tomlkit.dumps(doc) == original

    def test_already_present_with_different_constraint_is_skip(self):
        original = (
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["release-toolkit==9.9.9"]\n'
        )
        doc = tomlkit.parse(original)
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")

        assert result == DevDepResult(
            status=DevDepStatus.ALREADY_PRESENT,
            spec_written="release-toolkit==9.9.9",
        )
        assert tomlkit.dumps(doc) == original

    def test_bare_name_already_present_is_skip(self):
        original = (
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["release-toolkit"]\n'
        )
        doc = tomlkit.parse(original)
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")

        assert result == DevDepResult(
            status=DevDepStatus.ALREADY_PRESENT,
            spec_written="release-toolkit",
        )
        assert tomlkit.dumps(doc) == original

    def test_normalizes_underscore_vs_hyphen(self):
        original = (
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["release_toolkit>=0.1"]\n'
        )
        doc = tomlkit.parse(original)
        result = ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")

        assert result.status == DevDepStatus.ALREADY_PRESENT
        assert tomlkit.dumps(doc) == original

    def test_preserves_top_level_comment(self, commented_pyproject):
        doc = tomlkit.parse(commented_pyproject)
        ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")

        assert "# top comment" in tomlkit.dumps(doc)

    def test_preserves_multiline_array_layout_when_appending(self):
        original = (
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\n'
            'dev = [\n'
            '    "pytest>=8",\n'
            ']\n'
        )
        doc = tomlkit.parse(original)
        ensure_dev_dependency(doc, "release-toolkit>=0.2.0,<1", "release-toolkit")
        dumped = tomlkit.dumps(doc)

        assert '"pytest>=8",' in dumped
        assert '"release-toolkit>=0.2.0,<1"' in dumped
        assert "dev = [\n" in dumped
