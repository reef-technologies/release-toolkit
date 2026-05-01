"""Commitizen plugin filtering changelog entries by a configurable footer.

The plugin extends ConventionalCommitsCz and rebuilds ``changelog_pattern``
based on user-supplied configuration. It supports two modes:

* monorepo: ``impacts = ["client", "commons"]`` -> only commits whose
  ``Impacts:`` footer mentions one of those tags participate in the
  changelog and version increment computation.
* single-package: ``impacts`` omitted or empty -> behaves like upstream
  ConventionalCommitsCz with no extra filtering.
"""

from __future__ import annotations

import re
from typing import Any

from commitizen.config.base_config import BaseConfig
from commitizen.cz.conventional_commits import ConventionalCommitsCz

DEFAULT_FOOTER = "Impacts"


def build_changelog_pattern(impacts: list[str] | None, footer: str = DEFAULT_FOOTER) -> str | None:
    """Return a regex selecting commits whose ``footer`` line lists any of ``impacts``.

    When ``impacts`` is empty or None, returns None which signals the caller to
    fall back to the upstream pattern (no scope filtering).
    """
    if not impacts:
        return None
    escaped_footer = re.escape(footer)
    alternatives = "|".join(re.escape(tag) for tag in impacts)
    return rf"(?ims).*^{escaped_footer}:\s*[^\n]*\b({alternatives})\b.*"


class ImpactsCz(ConventionalCommitsCz):
    """Conventional Commits plugin with optional ``Impacts:`` footer filtering.

    Configuration (in ``[tool.commitizen]``):

    * ``impacts``: list of tag names. Required for monorepo filtering.
    * ``impacts_footer``: footer name. Defaults to ``Impacts``.
    """

    def __init__(self, config: BaseConfig) -> None:
        super().__init__(config)
        settings: dict[str, Any] = dict(config.settings)
        impacts = settings.get("impacts") or []
        footer = settings.get("impacts_footer") or DEFAULT_FOOTER
        if not isinstance(impacts, list) or not all(isinstance(tag, str) for tag in impacts):
            raise ValueError("[tool.commitizen] 'impacts' must be a list of strings")
        if not isinstance(footer, str):
            raise ValueError("[tool.commitizen] 'impacts_footer' must be a string")
        custom_pattern = build_changelog_pattern(impacts, footer)
        if custom_pattern is not None:
            self.changelog_pattern = custom_pattern
