from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


class GitRepo:
    """Test helper exposing a tmp git repo with conventional-commit helpers."""

    def __init__(self, path: Path):
        self.path = path
        self._env = {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            **os.environ,
        }

    def __truediv__(self, other: str) -> Path:
        return self.path / other

    def run(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.path, env=self._env, text=True)

    def commit(self, message: str) -> None:
        f = self.path / "f"
        f.write_text((f.read_text() + "x") if f.exists() else "x")
        self.run("add", "f")
        self.run("commit", "-m", message)

    def tag(self, name: str) -> None:
        self.run("tag", "-a", name, "-m", name)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    path = tmp_path / "repo"
    path.mkdir()
    monkeypatch.chdir(path)
    repo = GitRepo(path)
    repo.run("init", "-q", "-b", "main")
    repo.run("config", "user.email", "test@example.com")
    repo.run("config", "user.name", "test")
    return repo
