"""Tests for the skills CLI subcommands."""

import sys
from unittest.mock import patch

import pytest

from forge.cli import (
    cmd_skills_install,
    cmd_skills_list,
    cmd_skills_update,
    main,
)

# ---------------------------------------------------------------------------
# Helper: build a minimal argparse.Namespace for install
# ---------------------------------------------------------------------------


def _install_args(
    source="https://github.com/example/skill.git", project=None, default=False, ref=None
):
    import argparse

    return argparse.Namespace(
        source=source,
        project=project,
        default=default,
        ref=ref,
    )


def _update_args(project=None):
    import argparse

    return argparse.Namespace(project=project)


# ---------------------------------------------------------------------------
# cmd_skills_install
# ---------------------------------------------------------------------------


class TestCmdSkillsInstall:
    """Unit tests for cmd_skills_install handler."""

    @pytest.mark.asyncio
    async def test_install_with_project_returns_0(self):
        args = _install_args(project="MYPROJ")
        result = await cmd_skills_install(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_install_with_default_flag_returns_0(self):
        args = _install_args(default=True)
        result = await cmd_skills_install(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_install_missing_both_returns_2(self, capsys):
        args = _install_args()  # neither project nor default
        result = await cmd_skills_install(args)
        assert result == 2
        captured = capsys.readouterr()
        assert "exactly one of --project or --default" in captured.err

    @pytest.mark.asyncio
    async def test_install_both_project_and_default_returns_2(self, capsys):
        args = _install_args(project="MYPROJ", default=True)
        result = await cmd_skills_install(args)
        assert result == 2
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err

    @pytest.mark.asyncio
    async def test_install_with_ref_and_project_returns_0(self):
        args = _install_args(project="MYPROJ", ref="v1.2.3")
        result = await cmd_skills_install(args)
        assert result == 0


# ---------------------------------------------------------------------------
# cmd_skills_list
# ---------------------------------------------------------------------------


class TestCmdSkillsList:
    """Unit tests for cmd_skills_list handler."""

    @pytest.mark.asyncio
    async def test_list_returns_0(self):
        import argparse

        args = argparse.Namespace()
        result = await cmd_skills_list(args)
        assert result == 0


# ---------------------------------------------------------------------------
# cmd_skills_update
# ---------------------------------------------------------------------------


class TestCmdSkillsUpdate:
    """Unit tests for cmd_skills_update handler."""

    @pytest.mark.asyncio
    async def test_update_no_project_returns_0(self):
        args = _update_args()
        result = await cmd_skills_update(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_update_with_project_returns_0(self):
        args = _update_args(project="MYPROJ")
        result = await cmd_skills_update(args)
        assert result == 0


# ---------------------------------------------------------------------------
# Integration: main() dispatch
# ---------------------------------------------------------------------------


class TestMainSkillsDispatch:
    """Integration tests exercising main() argument parsing for skills."""

    def _run_main(self, argv):
        with patch.object(sys, "argv", ["forge"] + argv):
            return main()

    def test_skills_install_with_project(self):
        result = self._run_main(
            ["skills", "install", "https://github.com/example/skill.git", "--project", "MYPROJ"]
        )
        assert result == 0

    def test_skills_install_with_default(self):
        result = self._run_main(
            ["skills", "install", "https://github.com/example/skill.git", "--default"]
        )
        assert result == 0

    def test_skills_install_missing_target_returns_2(self):
        result = self._run_main(["skills", "install", "https://github.com/example/skill.git"])
        assert result == 2

    def test_skills_install_both_project_and_default_returns_2(self):
        result = self._run_main(
            [
                "skills",
                "install",
                "https://github.com/example/skill.git",
                "--project",
                "MYPROJ",
                "--default",
            ]
        )
        assert result == 2

    def test_skills_install_with_ref(self):
        result = self._run_main(
            [
                "skills",
                "install",
                "https://github.com/example/skill.git",
                "--project",
                "MYPROJ",
                "--ref",
                "v1.0.0",
            ]
        )
        assert result == 0

    def test_skills_list(self):
        result = self._run_main(["skills", "list"])
        assert result == 0

    def test_skills_update_no_project(self):
        result = self._run_main(["skills", "update"])
        assert result == 0

    def test_skills_update_with_project(self):
        result = self._run_main(["skills", "update", "--project", "MYPROJ"])
        assert result == 0
