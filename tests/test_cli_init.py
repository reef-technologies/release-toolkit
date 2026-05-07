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


def _make_project_dir(parent: Path, name: str, content: str) -> Path:
    # Create an isolated project root with its own .git marker so that the
    # workflow installer's repo-root walk terminates at this directory and
    # `package_dir` renders as "." (relative to the project root itself).
    d = parent / name
    d.mkdir()
    (d / ".git").mkdir()
    (d / "pyproject.toml").write_text(content)
    return d


@pytest.fixture
def fresh_path(tmp_path: Path) -> Path:
    return _make_project_dir(tmp_path, "fresh", EMPTY_PYPROJECT)


@pytest.fixture
def already_path(tmp_path: Path) -> Path:
    return _make_project_dir(tmp_path, "already", ALREADY_INSTALLED_PYPROJECT)


@pytest.fixture
def foreign_path(tmp_path: Path) -> Path:
    return _make_project_dir(tmp_path, "foreign", FOREIGN_PYPROJECT)


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
        text = (fresh_path / "pyproject.toml").read_text()

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
        assert "major_version_zero = true" in text

    def test_already_installed_commitizen_only_keeps_section_and_injects_dev_dep(
        self, monkeypatch, capsys, already_path
    ):
        code = _run(monkeypatch, "init", "single", str(already_path))
        captured = capsys.readouterr()
        text = (already_path / "pyproject.toml").read_text()

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
        pyproject = foreign_path / "pyproject.toml"
        before = pyproject.read_text()
        code = _run(monkeypatch, "init", "single", str(foreign_path))
        captured = capsys.readouterr()

        assert code == 0
        assert pyproject.read_text() == before
        assert "WARNING" in captured.err
        assert "cz_conventional_commits" in captured.err

    def test_missing_path_errors_with_nonzero_exit(self, monkeypatch, capsys, tmp_path):
        missing = tmp_path / "nope"
        code = _run(monkeypatch, "init", "single", str(missing))
        captured = capsys.readouterr()

        assert code == 1
        assert "ERROR" in captured.err
        assert "not a directory" in captured.err

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
        missing = tmp_path / "nope"
        code = _run(monkeypatch, "init", "single", str(missing), str(fresh_path))
        captured = capsys.readouterr()

        assert code == 1
        assert "added default" in captured.out
        assert "not a directory" in captured.err
        assert 'name = "impacts_cz"' in (fresh_path / "pyproject.toml").read_text()

    def test_fresh_file_gets_release_toolkit_dev_dependency(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        text = (fresh_path / "pyproject.toml").read_text()

        assert code == 0
        assert "[dependency-groups]" in text
        assert "release-toolkit" in text
        assert "to [dependency-groups].dev" in captured.out

    def test_existing_release_toolkit_dev_entry_is_left_alone(
        self, monkeypatch, capsys, tmp_path
    ):
        d = tmp_path / "with_existing_dev"
        d.mkdir()
        pyproject = d / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["release-toolkit==9.9.9"]\n'
        )
        code = _run(monkeypatch, "init", "single", str(d))
        captured = capsys.readouterr()
        text = pyproject.read_text()

        assert code == 0
        assert "release-toolkit==9.9.9" in text
        assert text.count("release-toolkit") == 1
        assert "already present in [dependency-groups].dev" in captured.out

    def test_existing_dev_group_without_release_toolkit_appends(
        self, monkeypatch, tmp_path
    ):
        d = tmp_path / "with_other_dev"
        d.mkdir()
        pyproject = d / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[dependency-groups]\ndev = ["pytest>=8"]\n'
        )
        code = _run(monkeypatch, "init", "single", str(d))
        text = pyproject.read_text()

        assert code == 0
        assert "pytest>=8" in text
        assert "release-toolkit" in text

    def test_directory_without_pyproject_errors(self, monkeypatch, capsys, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        code = _run(monkeypatch, "init", "single", str(empty_dir))
        captured = capsys.readouterr()

        assert code == 1
        assert "file not found" in captured.err
        assert "pyproject.toml" in captured.err

    def test_path_to_a_file_errors_as_not_a_directory(
        self, monkeypatch, capsys, tmp_path
    ):
        # Passing a file path (e.g. directly to pyproject.toml) is no longer
        # supported; CLI must reject it with a clear "not a directory" error.
        f = tmp_path / "pyproject.toml"
        f.write_text(EMPTY_PYPROJECT)

        code = _run(monkeypatch, "init", "single", str(f))
        captured = capsys.readouterr()

        assert code == 1
        assert "not a directory" in captured.err

    def test_version_provider_override_is_written_verbatim(
        self, monkeypatch, fresh_path
    ):
        code = _run(
            monkeypatch, "init", "single", "--version-provider", "scm", str(fresh_path)
        )
        text = (fresh_path / "pyproject.toml").read_text()

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
        text = (fresh_path / "pyproject.toml").read_text()

        assert code == 0
        assert 'version_provider = "my-custom-provider"' in text


class TestInitMonorepo:
    def test_fresh_file_gets_named_tag_format_and_impacts(self, monkeypatch, capsys, fresh_path):
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client")
        text = (fresh_path / "pyproject.toml").read_text()

        assert code == 0
        assert 'tag_format = "client-v$version"' in text
        assert 'impacts = ["client"]' in text
        assert 'bump_message = "bump: client $current_version -> $new_version"' in text
        assert "ignored_tag_formats" not in text

    def test_odd_number_of_args_is_argparse_error(
        self, monkeypatch, capsys, fresh_path, tmp_path
    ):
        other = tmp_path / "other"
        other.mkdir()
        (other / "pyproject.toml").write_text(EMPTY_PYPROJECT)
        code = _run(monkeypatch, "init", "monorepo", str(fresh_path), "client", str(other))
        # argparse parser.error exits with code 2
        assert code == 2

    def test_foreign_name_warns_and_keeps_file(self, monkeypatch, capsys, foreign_path):
        pyproject = foreign_path / "pyproject.toml"
        before = pyproject.read_text()
        code = _run(monkeypatch, "init", "monorepo", str(foreign_path), "client")
        captured = capsys.readouterr()

        assert code == 0
        assert pyproject.read_text() == before
        assert "WARNING" in captured.err

    def test_two_pairs_each_get_their_own_name(self, monkeypatch, capsys, tmp_path):
        d1 = tmp_path / "client"
        d2 = tmp_path / "service"
        d1.mkdir()
        d2.mkdir()
        p1 = d1 / "pyproject.toml"
        p2 = d2 / "pyproject.toml"
        p1.write_text(EMPTY_PYPROJECT)
        p2.write_text(EMPTY_PYPROJECT)
        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            str(d1),
            "client",
            str(d2),
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
        d1 = tmp_path / "client"
        d2 = tmp_path / "service"
        d1.mkdir()
        d2.mkdir()
        p1 = d1 / "pyproject.toml"
        p2 = d2 / "pyproject.toml"
        p1.write_text(EMPTY_PYPROJECT)
        p2.write_text(EMPTY_PYPROJECT)
        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            "--version-provider",
            "scm",
            str(d1),
            "client",
            str(d2),
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
        d1 = tmp_path / "client"
        d2 = tmp_path / "service"
        d1.mkdir()
        d2.mkdir()
        p1 = d1 / "pyproject.toml"
        p2 = d2 / "pyproject.toml"
        p1.write_text(EMPTY_PYPROJECT)
        p2.write_text(EMPTY_PYPROJECT)
        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            str(d1),
            "client",
            str(d2),
            "service",
        )

        assert code == 0
        assert "[dependency-groups]" in p1.read_text()
        assert "release-toolkit" in p1.read_text()
        assert "[dependency-groups]" in p2.read_text()
        assert "release-toolkit" in p2.read_text()


class TestInitParentRequired:
    def test_init_alone_is_argparse_error(self, monkeypatch):
        code = _run(monkeypatch, "init")
        assert code == 2


class TestInitWorkflow:
    def test_single_creates_release_caller_at_repo_root(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        # fresh_path has its own .git marker, so it acts as the repo root
        # and the workflow lands under <fresh_path>/.github/workflows/.
        workflow = fresh_path / ".github" / "workflows" / "release.yml"

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
        (client_dir / "pyproject.toml").write_text(EMPTY_PYPROJECT)
        (service_dir / "pyproject.toml").write_text(EMPTY_PYPROJECT)

        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            str(client_dir),
            "client",
            str(service_dir),
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
        self, monkeypatch, capsys, fresh_path
    ):
        workflows = fresh_path / ".github" / "workflows"
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
        (service_dir / "pyproject.toml").write_text(EMPTY_PYPROJECT)

        code = _run(
            monkeypatch, "init", "monorepo", str(service_dir), "service"
        )

        assert code == 0
        assert (workflows / "release-service.yml").is_file()

    def test_unrelated_file_with_target_name_is_skipped_with_warning(
        self, monkeypatch, capsys, fresh_path
    ):
        workflows = fresh_path / ".github" / "workflows"
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
        self, monkeypatch, capsys, fresh_path
    ):
        from release_toolkit import cli as cli_mod

        monkeypatch.setattr(cli_mod, "_find_repo_root", lambda _: None)

        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()

        assert code == 1
        assert "could not locate repo root" in captured.err
        # The pyproject was still updated even when the workflow step bailed.
        assert 'name = "impacts_cz"' in (fresh_path / "pyproject.toml").read_text()

    def test_idempotent_second_run_does_not_rewrite_workflow(
        self, monkeypatch, capsys, fresh_path
    ):
        _run(monkeypatch, "init", "single", str(fresh_path))
        capsys.readouterr()
        workflow = fresh_path / ".github" / "workflows" / "release.yml"
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


STABLE_PYPROJECT = '[project]\nname = "demo"\nversion = "1.2.3"\n'
NO_VERSION_PYPROJECT = '[project]\nname = "demo"\n'


class TestInitMajorVersionZero:
    def test_fresh_zero_y_z_inserts_flag_and_prints_zero_next_steps(
        self, monkeypatch, capsys, fresh_path
    ):
        code = _run(monkeypatch, "init", "single", str(fresh_path))
        captured = capsys.readouterr()
        text = (fresh_path / "pyproject.toml").read_text()

        assert code == 0
        assert "major_version_zero = true" in text
        assert "detected 0.Y.Z version" in captured.out
        assert "NEXT STEPS - major_version_zero" in captured.out
        assert "Detected a 0.Y.Z version" in captured.out
        assert "1.0.0" in captured.out

    def test_fresh_one_y_z_omits_flag_and_prints_non_zero_next_steps(
        self, monkeypatch, capsys, tmp_path
    ):
        d = tmp_path / "stable"
        d.mkdir()
        pyproject = d / "pyproject.toml"
        pyproject.write_text(STABLE_PYPROJECT)

        code = _run(monkeypatch, "init", "single", str(d))
        captured = capsys.readouterr()
        text = pyproject.read_text()

        assert code == 0
        assert "major_version_zero" not in text
        assert "detected 0.Y.Z version" not in captured.out
        assert "NEXT STEPS - major_version_zero" in captured.out
        assert "Project is already >= 1.0.0" in captured.out

    def test_fresh_without_project_version_warns_and_prints_unknown_next_steps(
        self, monkeypatch, capsys, tmp_path
    ):
        d = tmp_path / "noversion"
        d.mkdir()
        pyproject = d / "pyproject.toml"
        pyproject.write_text(NO_VERSION_PYPROJECT)

        code = _run(monkeypatch, "init", "single", str(d))
        captured = capsys.readouterr()
        text = pyproject.read_text()

        assert code == 0
        assert "major_version_zero" not in text
        assert "could not determine current project version" in captured.err
        assert "NEXT STEPS - major_version_zero" in captured.out
        assert "Could not determine the current project version" in captured.out

    def test_monorepo_mixed_versions_zero_priority_wins_in_next_steps(
        self, monkeypatch, capsys, tmp_path
    ):
        zero_dir = tmp_path / "zero"
        stable_dir = tmp_path / "stable"
        zero_dir.mkdir()
        stable_dir.mkdir()
        zero_pyproject = zero_dir / "pyproject.toml"
        stable_pyproject = stable_dir / "pyproject.toml"
        zero_pyproject.write_text(EMPTY_PYPROJECT)
        stable_pyproject.write_text(STABLE_PYPROJECT)

        code = _run(
            monkeypatch,
            "init",
            "monorepo",
            str(zero_dir),
            "client",
            str(stable_dir),
            "service",
        )
        captured = capsys.readouterr()

        assert code == 0
        assert "major_version_zero = true" in zero_pyproject.read_text()
        assert "major_version_zero" not in stable_pyproject.read_text()
        assert "Detected a 0.Y.Z version" in captured.out
        assert "Project is already >= 1.0.0" not in captured.out

    def test_scm_provider_in_real_repo_without_tags_classifies_zero(
        self, monkeypatch, capsys, git_repo
    ):
        # In a real git repo with no tags, ScmProvider returns "0.0.0" - so
        # the classifier should report ZERO and the flag should be inserted.
        # Verifying this exercises the real-file path (not a sandbox copy):
        # if the classifier worked off a tempdir without .git, scm would have
        # raised and UNKNOWN would slip through.
        pyproject = git_repo / "pyproject.toml"
        pyproject.write_text(EMPTY_PYPROJECT)

        code = _run(
            monkeypatch,
            "init",
            "single",
            "--version-provider",
            "scm",
            str(git_repo.path),
        )
        captured = capsys.readouterr()
        text = pyproject.read_text()

        assert code == 0
        assert 'version_provider = "scm"' in text
        assert "major_version_zero = true" in text
        assert "Detected a 0.Y.Z version" in captured.out

    def test_scm_provider_in_real_repo_with_one_tag_classifies_non_zero(
        self, monkeypatch, capsys, git_repo
    ):
        # Real git repo with a v1.x tag visible to ScmProvider: classifier
        # must report NON_ZERO and the flag must NOT be inserted.
        pyproject = git_repo / "pyproject.toml"
        pyproject.write_text('[project]\nname = "demo"\nversion = "1.2.3"\n')
        git_repo.commit("feat: initial")
        git_repo.tag("v1.2.3")

        code = _run(
            monkeypatch,
            "init",
            "single",
            "--version-provider",
            "scm",
            str(git_repo.path),
        )
        captured = capsys.readouterr()
        text = pyproject.read_text()

        assert code == 0
        assert 'version_provider = "scm"' in text
        assert "major_version_zero" not in text
        assert "Project is already >= 1.0.0" in captured.out

    def test_already_installed_with_pep621_does_not_rewrite_flag_but_drives_next_steps(
        self, monkeypatch, capsys, tmp_path
    ):
        # Existing impacts_cz section with version_provider=pep621 and a 0.Y.Z
        # project version. install_into_document returns ALREADY_INSTALLED, so
        # we must not mutate the section, but classification still reports
        # ZERO and NEXT STEPS surfaces the graduation-to-1.0.0 wording.
        d = tmp_path / "already_pep621"
        d.mkdir()
        pyproject = d / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[tool.commitizen]\nname = "impacts_cz"\n'
            'version_provider = "pep621"\ntag_format = "v$version"\n'
        )
        before_section = (
            '[tool.commitizen]\nname = "impacts_cz"\n'
            'version_provider = "pep621"\ntag_format = "v$version"\n'
        )

        code = _run(monkeypatch, "init", "single", str(d))
        captured = capsys.readouterr()
        after = pyproject.read_text()

        assert code == 0
        assert before_section in after
        assert "major_version_zero" not in after.split("[tool.commitizen]", 1)[1].split("[dependency-groups]")[0]
        assert "Detected a 0.Y.Z version" in captured.out
