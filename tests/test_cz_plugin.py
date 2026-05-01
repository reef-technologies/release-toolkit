from __future__ import annotations

import re

import pytest
from commitizen.config.base_config import BaseConfig
from commitizen.cz.conventional_commits import ConventionalCommitsCz

from release_toolkit.cz_plugin import DEFAULT_FOOTER, ImpactsCz, build_changelog_pattern


def _config(**settings: object) -> BaseConfig:
    cfg = BaseConfig()
    cfg.settings.update(settings)
    return cfg


class TestBuildChangelogPattern:
    def test_returns_none_when_impacts_empty(self):
        assert build_changelog_pattern([]) is None
        assert build_changelog_pattern(None) is None

    def test_pattern_matches_listed_tag(self):
        pattern = build_changelog_pattern(["client", "commons"])
        assert pattern is not None
        regex = re.compile(pattern)
        assert regex.match("feat: thing\n\nImpacts: client\n")
        assert regex.match("feat: thing\n\nImpacts: client, commons\n")
        assert regex.match("feat!: thing\n\nImpacts:    commons   \n")

    def test_pattern_rejects_unrelated_tags(self):
        pattern = build_changelog_pattern(["client"])
        regex = re.compile(pattern)
        assert not regex.match("feat: thing\n\nImpacts: service\n")
        assert not regex.match("feat: thing\n\n(no impacts footer)\n")

    def test_pattern_uses_word_boundary(self):
        pattern = build_changelog_pattern(["api"])
        regex = re.compile(pattern)
        assert not regex.match("feat: thing\n\nImpacts: rapid\n")
        assert regex.match("feat: thing\n\nImpacts: api\n")

    def test_custom_footer(self):
        pattern = build_changelog_pattern(["client"], footer="Affects")
        regex = re.compile(pattern)
        assert regex.match("feat: thing\n\nAffects: client\n")
        assert not regex.match("feat: thing\n\nImpacts: client\n")

    def test_special_chars_in_footer_are_escaped(self):
        pattern = build_changelog_pattern(["x"], footer="Im.pacts")
        regex = re.compile(pattern)
        assert regex.match("feat\n\nIm.pacts: x\n")
        assert not regex.match("feat\n\nImXpacts: x\n")


class TestImpactsCz:
    def test_no_impacts_falls_back_to_default_pattern(self):
        cz = ImpactsCz(_config())
        assert cz.changelog_pattern == ConventionalCommitsCz.changelog_pattern

    def test_with_impacts_overrides_pattern(self):
        cz = ImpactsCz(_config(impacts=["client", "commons"]))
        assert cz.changelog_pattern is not None
        assert cz.changelog_pattern != ConventionalCommitsCz.changelog_pattern
        regex = re.compile(cz.changelog_pattern)
        assert regex.match("feat: thing\n\nImpacts: client\n")
        assert not regex.match("feat: thing\n\nImpacts: service\n")

    def test_default_footer_used_when_unset(self):
        cz = ImpactsCz(_config(impacts=["x"]))
        assert DEFAULT_FOOTER in cz.changelog_pattern

    def test_custom_footer_honored(self):
        cz = ImpactsCz(_config(impacts=["x"], impacts_footer="Affects"))
        assert "Affects" in cz.changelog_pattern
        assert "Impacts" not in cz.changelog_pattern

    def test_invalid_impacts_type_raises(self):
        with pytest.raises(ValueError, match="impacts"):
            ImpactsCz(_config(impacts="client"))

    def test_invalid_impacts_member_raises(self):
        with pytest.raises(ValueError, match="impacts"):
            ImpactsCz(_config(impacts=["client", 1]))

    def test_invalid_footer_type_raises(self):
        with pytest.raises(ValueError, match="impacts_footer"):
            ImpactsCz(_config(impacts=["client"], impacts_footer=123))
