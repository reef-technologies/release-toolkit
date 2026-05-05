from __future__ import annotations

from typing import cast

import pytest
import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Table

from release_toolkit.installer import (
    CommitizenConfig,
    InstallResult,
    InstallStatus,
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
