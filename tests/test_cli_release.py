from __future__ import annotations

import sys

import pytest

from release_toolkit import cli as cli_mod
from release_toolkit.release_runner import ReleaseAborted


@pytest.fixture
def capture_run_release(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(cli_mod, "run_release", fake)
    return calls


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["release-toolkit", *argv])
    try:
        cli_mod.main()
    except SystemExit as exc:
        code = exc.code
        return int(code) if code is not None else 0
    return 0


class TestReleaseFlags:
    def test_defaults(self, monkeypatch, capture_run_release):
        code = _run(monkeypatch, "release")

        assert code == 0
        assert capture_run_release == [
            {"master_branch": "master", "use_filter": True, "bump_args": ()}
        ]

    def test_no_filter(self, monkeypatch, capture_run_release):
        code = _run(monkeypatch, "release", "--no-filter")

        assert code == 0
        assert capture_run_release == [
            {"master_branch": "master", "use_filter": False, "bump_args": ()}
        ]

    def test_master_branch_override(self, monkeypatch, capture_run_release):
        code = _run(monkeypatch, "release", "--master-branch", "main")

        assert code == 0
        assert capture_run_release == [
            {"master_branch": "main", "use_filter": True, "bump_args": ()}
        ]

    def test_forwards_bump_args_after_separator(self, monkeypatch, capture_run_release):
        code = _run(monkeypatch, "release", "--", "--prerelease", "beta")

        assert code == 0
        assert capture_run_release == [
            {
                "master_branch": "master",
                "use_filter": True,
                "bump_args": ("--prerelease", "beta"),
            }
        ]


class TestReleaseAborted:
    def test_aborted_exits_one_with_stderr_message(self, monkeypatch, capsys):
        def fake(**_kwargs):
            raise ReleaseAborted("Release requires a clean worktree.")

        monkeypatch.setattr(cli_mod, "run_release", fake)

        code = _run(monkeypatch, "release")
        captured = capsys.readouterr()

        assert code == 1
        assert "ERROR: Release requires a clean worktree." in captured.err
