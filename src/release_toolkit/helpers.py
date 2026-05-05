"""Pure helpers for computing the Commitizen increment respecting changelog filters."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from commitizen import bump, factory, git
from commitizen.config.base_config import BaseConfig
from commitizen.config.factory import create_config
from commitizen.defaults import Settings
from commitizen.providers import get_provider
from commitizen.tags import TagRules
from commitizen.version_schemes import Increment

NO_INCREMENT = "NONE"


def load_config(config_path: Path = Path("pyproject.toml")) -> BaseConfig:
    """Load a Commitizen config from an explicit path."""
    return create_config(data=config_path.read_bytes(), path=config_path)


def find_filtered_increment(config: BaseConfig) -> Increment | None:
    """Return the Commitizen increment after applying the configured changelog filter.

    Commitizen does not natively respect ``changelog_pattern`` when computing the
    next version increment (it only uses it for changelog rendering). Monorepo
    setups need that filtering to land on the increment computation as well.
    """
    cz = factory.committer_factory(config)
    if not cz.changelog_pattern or not cz.bump_pattern or not cz.bump_map:
        return None

    current_version = get_provider(config).get_version()
    rules = TagRules.from_settings(cast(Settings, config.settings))
    current_tag = rules.find_tag_for(git.get_tags(), current_version)
    commits = git.get_commits(current_tag.name if current_tag else None)

    changelog_pattern = re.compile(cz.changelog_pattern)
    filtered = [commit for commit in commits if changelog_pattern.match(commit.message)]
    increments_map = cz.bump_map_major_version_zero if config.settings["major_version_zero"] else cz.bump_map
    return bump.find_increment(filtered, regex=cz.bump_pattern, increments_map=increments_map)
