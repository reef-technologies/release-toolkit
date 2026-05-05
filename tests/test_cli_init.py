from __future__ import annotations

import sys
from pathlib import Path

import pytest

from release_toolkit.cli import main
from release_toolkit.workflow_installer import RELEASE_NOTIFY_USES_REF

EMPTY_PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\n'

ALREADY_INSTALLED_PYPROJECT = (
    '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
    '[tool.commitizen]\nname = "impacts_cz"\ntag_format = "v$version"\n'
)

FOREIGN_PYPROJECT = (
    '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
    '[tool.commitizen]\nname = "cz_conventional_commits"\n'
)


@pytest.fixture(autouse=True)
def _git_repo_marker(tmp_path: Path) -> None:
    # Mark `tmp_path` as the root of a git repo so the CLI's repo-root walk
    # (used by the workflow installer) terminates inside the test sandbox.
    (tmp_path / ".git").mkdir()


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
    monkeypatch.setattr(sys, "argv", ["release-toolkit", *argv])
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


class TestInitWorkflow:
    def test_single_creates_release_notify_at_repo_root(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        workflow = tmp_path / ".github" / "workflows" / "release-notify.yml"

        assert code == 0
        assert workflow.is_file()
        text = workflow.read_text()
        assert "name: Release notify\n" in text
        assert "      - 'v*'\n" in text
        assert "      package_dir: .\n" in text
        assert "      tag_prefix: v\n" in text
        assert RELEASE_NOTIFY_USES_REF in text
        assert "added release-notify caller workflow" in captured.out

    def test_monorepo_creates_per_package_workflows(self, monkeypatch, tmp_path):
        client_dir = tmp_path / "packages" / "client"
        service_dir = tmp_path / "packages" / "service"
        client_dir.mkdir(parents=True)
        service_dir.mkdir(parents=True)
        client_pyproject = client_dir / "pyproject.toml"
        service_pyproject = service_dir / "pyproject.toml"
        client_pyproject.write_text(EMPTY_PYPROJECT)
        service_pyproject.write_text(EMPTY_PYPROJECT)

        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            str(client_pyproject),
            "client",
            str(service_pyproject),
            "service",
        )

        assert code == 0
        client_workflow = tmp_path / ".github" / "workflows" / "release-notify-client.yml"
        service_workflow = tmp_path / ".github" / "workflows" / "release-notify-service.yml"
        assert client_workflow.is_file()
        assert service_workflow.is_file()
        client_text = client_workflow.read_text()
        service_text = service_workflow.read_text()
        assert "      - 'client-v*'\n" in client_text
        assert "      package_dir: packages/client\n" in client_text
        assert "      tag_prefix: client-v\n" in client_text
        assert "      - 'service-v*'\n" in service_text
        assert "      package_dir: packages/service\n" in service_text

    def test_existing_release_notify_under_other_filename_is_skipped(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        existing = workflows / "cd-foo.yml"
        existing.write_text(
            "jobs:\n"
            "  release:\n"
            f"    uses: {RELEASE_NOTIFY_USES_REF}\n"
            "    with:\n"
            "      tag_prefix: v\n"
        )

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert not (workflows / "release-notify.yml").exists()
        assert "already present, skipping" in captured.out
        assert str(existing) in captured.out

    def test_monorepo_does_not_treat_sibling_packages_as_already_installed(
        self, monkeypatch, tmp_path
    ):
        # Pre-create a client workflow; running `init monorepo` for service
        # must still create a separate service workflow.
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "release-notify-client.yml").write_text(
            "jobs:\n"
            "  release:\n"
            f"    uses: {RELEASE_NOTIFY_USES_REF}\n"
            "    with:\n"
            "      tag_prefix: client-v\n"
        )
        service_dir = tmp_path / "packages" / "service"
        service_dir.mkdir(parents=True)
        service_pyproject = service_dir / "pyproject.toml"
        service_pyproject.write_text(EMPTY_PYPROJECT)

        code = _run(
            monkeypatch, "init", "monorepo", str(service_pyproject), "service"
        )

        assert code == 0
        assert (workflows / "release-notify-service.yml").is_file()

    def test_unrelated_file_with_target_name_is_skipped_with_warning(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        target = workflows / "release-notify.yml"
        unrelated_content = "name: Something else\non: push\njobs:\n  noop:\n    runs-on: ubuntu-latest\n"
        target.write_text(unrelated_content)

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert target.read_text() == unrelated_content
        assert "WARNING" in captured.err
        assert "file exists with unrelated content" in captured.err

    def test_no_git_root_returns_error_exit(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        from release_toolkit import cli as cli_mod

        monkeypatch.setattr(cli_mod, "_find_repo_root", lambda _: None)

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 1
        assert "could not locate repo root" in captured.err
        # The pyproject was still updated even when the workflow step bailed.
        assert 'name = "impacts_cz"' in fresh_path.read_text()

    def test_idempotent_second_run_does_not_rewrite_workflow(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        _run(monkeypatch, "init", "single", str(fresh_path))
        capsys.readouterr()
        workflow = tmp_path / ".github" / "workflows" / "release-notify.yml"
        first_text = workflow.read_text()

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert workflow.read_text() == first_text
        assert "already present, skipping" in captured.out
