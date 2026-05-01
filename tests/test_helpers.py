from __future__ import annotations

from pathlib import Path

from release_toolkit.helpers import find_filtered_increment, load_config


def write_pyproject(repo: Path, body: str) -> Path:
    path = repo / "pyproject.toml"
    path.write_text(body)
    return path

MONOREPO_PYPROJECT = """
[project]
name = "demo-client"
version = "0.1.0"

[tool.commitizen]
name = "impacts_cz"
version = "0.1.0"
tag_format = "client-v$version"
impacts = ["client", "commons"]
"""

SINGLE_PYPROJECT = """
[project]
name = "demo"
version = "0.1.0"

[tool.commitizen]
name = "impacts_cz"
version = "0.1.0"
tag_format = "v$version"
"""


class TestFindFilteredIncrementMonorepo:
    def test_returns_none_when_only_unrelated_commits(self, git_repo):
        write_pyproject(git_repo, MONOREPO_PYPROJECT)
        git_repo.commit("chore: initial")
        git_repo.tag("client-v0.1.0")
        git_repo.commit("feat: thing\n\nImpacts: service")
        git_repo.commit("fix: thing\n\nImpacts: service")

        config = load_config(git_repo / "pyproject.toml")
        assert find_filtered_increment(config) is None

    def test_picks_up_minor_when_feat_impacts_client(self, git_repo):
        write_pyproject(git_repo, MONOREPO_PYPROJECT)
        git_repo.commit("chore: initial")
        git_repo.tag("client-v0.1.0")
        git_repo.commit("fix: bug\n\nImpacts: service")
        git_repo.commit("feat: cool\n\nImpacts: client")

        config = load_config(git_repo / "pyproject.toml")
        assert find_filtered_increment(config) == "MINOR"

    def test_breaking_change_picks_major(self, git_repo):
        write_pyproject(git_repo, MONOREPO_PYPROJECT)
        git_repo.commit("chore: initial")
        git_repo.tag("client-v1.0.0")
        git_repo.commit("feat!: rip\n\nImpacts: client")

        config = load_config(git_repo / "pyproject.toml")
        # major_version_zero defaults False here because tag is 1.x
        assert find_filtered_increment(config) == "MAJOR"

    def test_commons_tag_propagates(self, git_repo):
        write_pyproject(git_repo, MONOREPO_PYPROJECT)
        git_repo.commit("chore: initial")
        git_repo.tag("client-v0.1.0")
        git_repo.commit("fix: thing\n\nImpacts: commons")

        config = load_config(git_repo / "pyproject.toml")
        assert find_filtered_increment(config) == "PATCH"


class TestFindFilteredIncrementSinglePackage:
    def test_no_impacts_means_no_filter_applied(self, git_repo):
        write_pyproject(git_repo, SINGLE_PYPROJECT)
        git_repo.commit("chore: initial")
        git_repo.tag("v0.1.0")
        git_repo.commit("feat: regular feature without footer")

        config = load_config(git_repo / "pyproject.toml")
        # find_filtered_increment uses the upstream pattern, which matches all commits
        assert find_filtered_increment(config) == "MINOR"
