from __future__ import annotations

import sys
from pathlib import Path

import pytest

from release_toolkit.cli import main

EMPTY_PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\n'

ALREADY_INSTALLED_PYPROJECT = (
    '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
    '[tool.commitizen]\nname = "impacts_cz"\ntag_format = "v$version"\n'
)

FOREIGN_PYPROJECT = (
    '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
    '[tool.commitizen]\nname = "cz_conventional_commits"\n'
)


@pytest.fixture
def fresh_path(tmp_path: Path) -> Path:
    p = tmp_path / "fresh.toml"
    p.write_text(EMPTY_PYPROJECT)
    return p


@pytest.fixture
def already_path(tmp_path: Path) -> Path:
    p = tmp_path / "already.toml"
    p.write_text(ALREADY_INSTALLED_PYPROJECT)
    return p


@pytest.fixture
def foreign_path(tmp_path: Path) -> Path:
    p = tmp_path / "foreign.toml"
    p.write_text(FOREIGN_PYPROJECT)
    return p


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["cz-release-toolkit", *argv])
    try:
        main()
    except SystemExit as exc:
        code = exc.code
        return int(code) if code is not None else 0
    return 0


class TestInitSingle:
    def test_fresh_file_gets_default_section(self, monkeypatch, capsys, fresh_path):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        text = fresh_path.read_text()

        assert code == 0
        assert "INFO:" in captured.out
        assert "added default" in captured.out
        assert 'name = "impacts_cz"' in text
        assert 'tag_format = "v$version"' in text
        assert "impacts =" not in text

    def test_already_installed_file_unchanged(self, monkeypatch, capsys, already_path):
        before = already_path.read_text()
        code = _run(monkeypatch, "init", "single", str(already_path))
        captured = capsys.readouterr()

        assert code == 0
        assert already_path.read_text() == before
        assert "already installed, skipping" in captured.out

    def test_foreign_name_warns_and_keeps_file(self, monkeypatch, capsys, foreign_path):
        before = foreign_path.read_text()
        code = _run(monkeypatch, "init", "single", str(foreign_path))
        captured = capsys.readouterr()

        assert code == 0
        assert foreign_path.read_text() == before
        assert "WARNING" in captured.err
        assert "cz_conventional_commits" in captured.err

    def test_missing_path_errors_with_nonzero_exit(self, monkeypatch, capsys, tmp_path):
        missing = tmp_path / "nope.toml"
        code = _run(monkeypatch, "init", "single", str(missing))
        captured = capsys.readouterr()

        assert code == 1
        assert "ERROR" in captured.err
        assert "file not found" in captured.err

    def test_mixed_paths_each_reported_independently(
        self, monkeypatch, capsys, fresh_path, already_path, foreign_path
    ):
        code = _run(
            monkeypatch,
            "init",
            "single",
            str(fresh_path),
            str(already_path),
            str(foreign_path),
        )
        captured = capsys.readouterr()

        assert code == 0
        assert "added default" in captured.out
        assert "already installed" in captured.out
        assert "WARNING" in captured.err

    def test_mixed_with_missing_returns_one_but_processes_others(
        self, monkeypatch, capsys, fresh_path, tmp_path
    ):
        missing = tmp_path / "nope.toml"
        code = _run(monkeypatch, "init", "single", str(missing), str(fresh_path))
        captured = capsys.readouterr()

        assert code == 1
        assert "added default" in captured.out
        assert "file not found" in captured.err
        assert 'name = "impacts_cz"' in fresh_path.read_text()


class TestInitMonorepo:
    def test_fresh_file_gets_named_tag_format_and_impacts(self, monkeypatch, capsys, fresh_path):
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client")
        text = fresh_path.read_text()

        assert code == 0
        assert 'tag_format = "client-v$version"' in text
        assert 'impacts = ["client"]' in text
        assert "ignored_tag_formats" not in text

    def test_odd_number_of_args_is_argparse_error(
        self, monkeypatch, capsys, fresh_path, tmp_path
    ):
        other = tmp_path / "other.toml"
        other.write_text(EMPTY_PYPROJECT)
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client", str(other))
        # argparse parser.error exits with code 2
        assert code == 2

    def test_foreign_name_warns_and_keeps_file(self, monkeypatch, capsys, foreign_path):
        before = foreign_path.read_text()
        code = _run(monkeypatch, "init", "monorepo", str(foreign_path), "client")
        captured = capsys.readouterr()

        assert code == 0
        assert foreign_path.read_text() == before
        assert "WARNING" in captured.err

    def test_two_pairs_each_get_their_own_name(self, monkeypatch, capsys, tmp_path):
        p1 = tmp_path / "client.toml"
        p2 = tmp_path / "service.toml"
        p1.write_text(EMPTY_PYPROJECT)
        p2.write_text(EMPTY_PYPROJECT)
        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            str(p1),
            "client",
            str(p2),
            "service",
        )

        assert code == 0
        assert 'tag_format = "client-v$version"' in p1.read_text()
        assert 'impacts = ["client"]' in p1.read_text()
        assert 'tag_format = "service-v$version"' in p2.read_text()
        assert 'impacts = ["service"]' in p2.read_text()


class TestInitParentRequired:
    def test_init_alone_is_argparse_error(self, monkeypatch):
        code = _run(monkeypatch, "init")
        assert code == 2
