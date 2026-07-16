#!/usr/bin/env python
"""
Tests for tools/detect_bump_type.py — branch-aware version-bump detection.
"""
from __future__ import annotations

from tools.detect_bump_type import detect_bump_type, extract_branch_name, main


class TestExtractBranchName:
    def test_merge_commit_fix_branch(self):
        msg = "Merge pull request #25 from tombo92/fix-release-testing"
        assert extract_branch_name(msg) == "fix-release-testing"

    def test_merge_commit_with_slash_prefix(self):
        msg = "Merge pull request #7 from tombo92/feat/support-links"
        assert extract_branch_name(msg) == "feat/support-links"

    def test_merge_commit_bugfix_prefix(self):
        msg = "Merge pull request #9 from tombo92/bugfix/smart-version-bump"
        assert extract_branch_name(msg) == "bugfix/smart-version-bump"

    def test_uses_only_first_line(self):
        msg = (
            "Merge pull request #3 from tombo92/feat/recipes\n"
            "\n"
            "feat: add recipes module"
        )
        assert extract_branch_name(msg) == "feat/recipes"

    def test_squash_merge_returns_none(self):
        msg = "feat: add recipes module (#3)"
        assert extract_branch_name(msg) is None

    def test_direct_push_returns_none(self):
        msg = "fix(installer): invalid Tkinter color crashes GUI on launch"
        assert extract_branch_name(msg) is None

    def test_empty_message_returns_none(self):
        assert extract_branch_name("") is None
        assert extract_branch_name("   \n  ") is None

    def test_chore_bump_commit_returns_none(self):
        msg = "chore(version): bump to 1.8.0 [skip ci]"
        assert extract_branch_name(msg) is None


class TestDetectBumpType:
    def test_fix_prefix_is_patch(self):
        msg = "Merge pull request #1 from tombo92/fix/some-bug"
        assert detect_bump_type(msg) == "patch"

    def test_bugfix_prefix_is_patch(self):
        msg = "Merge pull request #2 from tombo92/bugfix/some-bug"
        assert detect_bump_type(msg) == "patch"

    def test_hotfix_prefix_is_patch(self):
        msg = "Merge pull request #3 from tombo92/hotfix/urgent-fix"
        assert detect_bump_type(msg) == "patch"

    def test_nested_fix_path_is_patch(self):
        """Prefix match must work even with extra path segments."""
        msg = "Merge pull request #4 from tombo92/fix/installer/color-crash"
        assert detect_bump_type(msg) == "patch"

    def test_feat_prefix_is_minor(self):
        msg = "Merge pull request #5 from tombo92/feat/recipes"
        assert detect_bump_type(msg) == "minor"

    def test_feature_prefix_is_minor(self):
        msg = "Merge pull request #6 from tombo92/feature/dark-mode"
        assert detect_bump_type(msg) == "minor"

    def test_unrecognized_prefix_defaults_to_minor(self):
        msg = "Merge pull request #7 from tombo92/improve-search-function"
        assert detect_bump_type(msg) == "minor"

    def test_no_merge_commit_defaults_to_minor(self):
        msg = "fix(installer): invalid Tkinter color crashes GUI on launch"
        assert detect_bump_type(msg) == "minor"

    def test_empty_message_defaults_to_minor(self):
        assert detect_bump_type("") == "minor"

    def test_squash_merge_defaults_to_minor(self):
        msg = "fix: correct off-by-one error in position generator (#42)"
        assert detect_bump_type(msg) == "minor"

    def test_case_sensitive_prefix_match(self):
        """Prefixes are matched literally; unconventional casing is not
        specially handled and falls back to the safe minor default."""
        msg = "Merge pull request #8 from tombo92/Fix/typo"
        assert detect_bump_type(msg) == "minor"


class TestMainCli:
    def test_prints_patch_for_bugfix_branch(self, capsys):
        rc = main(["Merge pull request #1 from tombo92/fix/crash"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "patch"

    def test_prints_minor_for_feature_branch(self, capsys):
        rc = main(["Merge pull request #2 from tombo92/feat/recipes"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "minor"

    def test_no_args_defaults_to_minor(self, capsys):
        rc = main([])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "minor"
