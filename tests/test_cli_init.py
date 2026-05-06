from __future__ import annotations

import sys
from pathlib import Path

import pytest

from release_toolkit.cli import main
from release_toolkit.workflow_installer import RELEASE_WORKFLOW_USES_REF

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
        assert 'version_provider = "pep621"' in text
        assert 'tag_format = "v$version"' in text
        assert "annotated_tag = true" in text
        assert "changelog_merge_prerelease = true" in text
        assert "impacts =" not in text
        assert "bump_message" not in text

    def test_already_installed_commitizen_only_keeps_section_and_injects_dev_dep(
        self, monkeypatch, capsys, already_path
    ):
        code = _run(monkeypatch, "init", "single", str(already_path))
        captured = capsys.readouterr()
        text = already_path.read_text()

        assert code == 0
        assert "already installed, skipping" in captured.out
        # commitizen section unchanged
        assert 'name = "impacts_cz"' in text
        assert 'tag_format = "v$version"' in text
        # dev-dep was forward-filled
        assert "[dependency-groups]" in text
        assert "release-toolkit" in text
        assert "to [dependency-groups].dev" in captured.out

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

    def test_fresh_file_gets_release_toolkit_dev_dependency(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        text = fresh_path.read_text()

        assert code == 0
        assert "[dependency-groups]" in text
        assert "release-toolkit" in text
        assert "to [dependency-groups].dev" in captured.out

    def test_existing_release_toolkit_dev_entry_is_left_alone(
        self, monkeypatch, capsys, tmp_path
    ):
        p = tmp_path / "with_existing_dev.toml"
        p.write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["release-toolkit==9.9.9"]\n'
        )
        code = _run(monkeypatch, "init", "single", str(p))
        captured = capsys.readouterr()
        text = p.read_text()

        assert code == 0
        assert "release-toolkit==9.9.9" in text
        assert text.count("release-toolkit") == 1
        assert "already present in [dependency-groups].dev" in captured.out

    def test_existing_dev_group_without_release_toolkit_appends(
        self, monkeypatch, tmp_path
    ):
        p = tmp_path / "with_other_dev.toml"
        p.write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["pytest>=8"]\n'
        )
        code = _run(monkeypatch, "init", "single", str(p))
        text = p.read_text()

        assert code == 0
        assert "pytest>=8" in text
        assert "release-toolkit" in text

    def test_directory_path_is_resolved_to_pyproject_toml(
        self, monkeypatch, capsys, tmp_path
    ):
        package_dir = tmp_path / "pkg"
        package_dir.mkdir()
        pyproject = package_dir / "pyproject.toml"
        pyproject.write_text(EMPTY_PYPROJECT)

        code = _run(monkeypatch, "init", "single", str(package_dir))
        captured = capsys.readouterr()
        text = pyproject.read_text()

        assert code == 0
        assert "added default" in captured.out
        assert 'name = "impacts_cz"' in text

    def test_directory_without_pyproject_errors(self, monkeypatch, capsys, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        code = _run(monkeypatch, "init", "single", str(empty_dir))
        captured = capsys.readouterr()

        assert code == 1
        assert "file not found" in captured.err
        assert "pyproject.toml" in captured.err

    def test_version_provider_override_is_written_verbatim(
        self, monkeypatch, fresh_path
    ):
        code = _run(
            monkeypatch, "init", "single", "--version-provider", "scm", str(fresh_path)
        )
        text = fresh_path.read_text()

        assert code == 0
        assert 'version_provider = "scm"' in text
        assert 'version_provider = "pep621"' not in text

    def test_unknown_version_provider_value_is_accepted_verbatim(
        self, monkeypatch, fresh_path
    ):
        code = _run(
            monkeypatch,
            "init",
            "single",
            "--version-provider",
            "my-custom-provider",
            str(fresh_path),
        )
        text = fresh_path.read_text()

        assert code == 0
        assert 'version_provider = "my-custom-provider"' in text


class TestInitMonorepo:
    def test_fresh_file_gets_named_tag_format_and_impacts(self, monkeypatch, capsys, fresh_path):
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client")
        text = fresh_path.read_text()

        assert code == 0
        assert 'tag_format = "client-v$version"' in text
        assert 'impacts = ["client"]' in text
        assert 'bump_message = "bump: client $current_version -> $new_version"' in text
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
        assert 'bump_message = "bump: client $current_version -> $new_version"' in p1.read_text()
        assert 'tag_format = "service-v$version"' in p2.read_text()
        assert 'impacts = ["service"]' in p2.read_text()
        assert 'bump_message = "bump: service $current_version -> $new_version"' in p2.read_text()

    def test_version_provider_override_applies_to_all_pairs(
        self, monkeypatch, tmp_path
    ):
        p1 = tmp_path / "client.toml"
        p2 = tmp_path / "service.toml"
        p1.write_text(EMPTY_PYPROJECT)
        p2.write_text(EMPTY_PYPROJECT)
        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            "--version-provider",
            "scm",
            str(p1),
            "client",
            str(p2),
            "service",
        )

        assert code == 0
        assert 'version_provider = "scm"' in p1.read_text()
        assert 'version_provider = "scm"' in p2.read_text()
        assert 'version_provider = "pep621"' not in p1.read_text()
        assert 'version_provider = "pep621"' not in p2.read_text()

    def test_monorepo_injects_release_toolkit_dev_dep_into_each_pair(
        self, monkeypatch, tmp_path
    ):
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
        assert "[dependency-groups]" in p1.read_text()
        assert "release-toolkit" in p1.read_text()
        assert "[dependency-groups]" in p2.read_text()
        assert "release-toolkit" in p2.read_text()

    def test_directory_path_is_resolved_to_pyproject_toml(
        self, monkeypatch, tmp_path
    ):
        client_dir = tmp_path / "packages" / "client"
        client_dir.mkdir(parents=True)
        pyproject = client_dir / "pyproject.toml"
        pyproject.write_text(EMPTY_PYPROJECT)

        code = _run(
            monkeypatch, "init", "monorepo", str(client_dir), "client"
        )
        text = pyproject.read_text()

        assert code == 0
        assert 'tag_format = "client-v$version"' in text
        assert 'impacts = ["client"]' in text
        assert (tmp_path / ".github" / "workflows" / "release-client.yml").is_file()


class TestInitParentRequired:
    def test_init_alone_is_argparse_error(self, monkeypatch):
        code = _run(monkeypatch, "init")
        assert code == 2


class TestInitWorkflow:
    def test_single_creates_release_caller_at_repo_root(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        workflow = tmp_path / ".github" / "workflows" / "release.yml"

        assert code == 0
        assert workflow.is_file()
        text = workflow.read_text()
        assert "name: Release\n" in text
        assert "      - 'v*'\n" in text
        assert "      package_dir: .\n" in text
        assert "      tag_prefix: v\n" in text
        assert RELEASE_WORKFLOW_USES_REF in text
        assert "added release caller workflow" in captured.out

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
        client_workflow = tmp_path / ".github" / "workflows" / "release-client.yml"
        service_workflow = tmp_path / ".github" / "workflows" / "release-service.yml"
        assert client_workflow.is_file()
        assert service_workflow.is_file()
        client_text = client_workflow.read_text()
        service_text = service_workflow.read_text()
        assert "      - 'client-v*'\n" in client_text
        assert "      package_dir: packages/client\n" in client_text
        assert "      tag_prefix: client-v\n" in client_text
        assert "      - 'service-v*'\n" in service_text
        assert "      package_dir: packages/service\n" in service_text

    def test_existing_release_caller_under_other_filename_is_skipped(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        existing = workflows / "cd-foo.yml"
        existing.write_text(
            "jobs:\n"
            "  release:\n"
            f"    uses: {RELEASE_WORKFLOW_USES_REF}\n"
            "    with:\n"
            "      tag_prefix: v\n"
        )

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert not (workflows / "release.yml").exists()
        assert "already present, skipping" in captured.out
        assert str(existing) in captured.out

    def test_monorepo_does_not_treat_sibling_packages_as_already_installed(
        self, monkeypatch, tmp_path
    ):
        # Pre-create a client workflow; running `init monorepo` for service
        # must still create a separate service workflow.
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "release-client.yml").write_text(
            "jobs:\n"
            "  release:\n"
            f"    uses: {RELEASE_WORKFLOW_USES_REF}\n"
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
        assert (workflows / "release-service.yml").is_file()

    def test_unrelated_file_with_target_name_is_skipped_with_warning(
        self, monkeypatch, capsys, tmp_path, fresh_path
    ):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        target = workflows / "release.yml"
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
        workflow = tmp_path / ".github" / "workflows" / "release.yml"
        first_text = workflow.read_text()

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert workflow.read_text() == first_text
        assert "already present, skipping" in captured.out


class TestInitNextSteps:
    def test_single_prints_slack_next_steps_on_success(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert "NEXT STEPS" in captured.out
        assert "SLACK_WEBHOOK_URL" in captured.out

    def test_monorepo_prints_slack_next_steps_on_success(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client")
        captured = capsys.readouterr()

        assert code == 0
        assert "NEXT STEPS" in captured.out
        assert "SLACK_WEBHOOK_URL" in captured.out

    def test_single_prints_version_provider_next_steps_on_success(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert "version_provider" in captured.out
        assert "pep621" in captured.out
        assert (
            "https://commitizen-tools.github.io/commitizen/config/version_provider/"
            in captured.out
        )

    def test_monorepo_prints_version_provider_next_steps_on_success(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client")
        captured = capsys.readouterr()

        assert code == 0
        assert "version_provider" in captured.out
        assert (
            "https://commitizen-tools.github.io/commitizen/config/version_provider/"
            in captured.out
        )

    def test_no_next_steps_on_error_exit(self, monkeypatch, capsys, tmp_path):
        missing = tmp_path / "nope.toml"
        code = _run(monkeypatch, "init", "single", str(missing))
        captured = capsys.readouterr()

        assert code == 1
        assert "NEXT STEPS" not in captured.out

    def test_next_steps_printed_on_idempotent_rerun(
        self, monkeypatch, capsys, fresh_path
    ):
        _run(monkeypatch, "init", "single", str(fresh_path))
        capsys.readouterr()

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 0
        assert "NEXT STEPS" in captured.out
