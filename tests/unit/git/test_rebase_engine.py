"""Unit tests for the Automated Git Rebase and Conflict Management Engine."""

import subprocess
from unittest.mock import patch

from forge.git.rebase_engine import RebaseStatus, execute_rebase


def test_execute_rebase_success():
    """Test a completely clean and successful rebase and push."""
    called_commands = []

    def mock_run(cmd, *_args, **_kwargs):
        called_commands.append(cmd)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

        if "clone" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Cloning done", stderr="")
        if "config" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Fetched", stderr="")
        if "checkout" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Checked out", stderr="")
        if "rev-parse" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="sha123", stderr="")
        if "rebase" in cmd_str:
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout="Rebase applied successfully", stderr=""
            )
        if "push" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Push done", stderr="")

        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="feature/cool-stuff",
            target_branch="main",
        )

        assert result.status == RebaseStatus.SUCCESS
        assert "Successfully rebased" in result.message
        assert result.conflicting_files is None
        assert result.conflict_summary is None
        assert "Push done" in result.output

        # Verify that expected key commands were run
        flat_cmds = [" ".join(c) for c in called_commands]
        assert any("git clone https://github.com/owner/repo.git" in c for c in flat_cmds)
        assert any("git checkout -b feature/cool-stuff" in c for c in flat_cmds)
        assert any("git fetch origin main" in c for c in flat_cmds)
        assert any("git rebase origin/main" in c for c in flat_cmds)
        assert any("git push origin feature/cool-stuff --force" in c for c in flat_cmds)


def test_execute_rebase_clone_failure():
    """Test that git clone failure is handled and returns an ERROR status."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="fatal: Repository not found",
        )

        result = execute_rebase(
            repo_url="https://github.com/owner/not-found.git",
            branch_name="feature",
            target_branch="main",
        )

        assert result.status == RebaseStatus.ERROR
        assert result.message == "Git clone failed"
        assert result.error_message == "fatal: Repository not found"


def test_execute_rebase_clone_timeout():
    """Test that git clone timing out returns an ERROR status."""
    with patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=300)
    ):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="feature",
            target_branch="main",
        )

        assert result.status == RebaseStatus.ERROR
        assert result.message == "Git clone timed out"
        assert "exceeded the timeout" in result.error_message


def test_execute_rebase_checkout_failure():
    """Test that checkout failure returns an ERROR status."""

    def mock_run(cmd, *_args, **_kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "clone" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "config" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "checkout" in cmd_str:
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="fatal: Cannot find branch"
            )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="missing-branch",
            target_branch="main",
        )

        assert result.status == RebaseStatus.ERROR
        assert "Failed to checkout branch" in result.message
        assert "fatal: Cannot find branch" in result.error_message


def test_execute_rebase_target_not_found():
    """Test that target branch not found on remote or local returns an ERROR status."""

    def mock_run(cmd, *_args, **_kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "clone" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "config" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "checkout" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "rev-parse" in cmd_str:
            # All rev-parse (remote and local verify) fail
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="not found")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="feature",
            target_branch="ghost-branch",
        )

        assert result.status == RebaseStatus.ERROR
        assert "Target branch 'ghost-branch' not found" in result.message
        assert "Could not locate 'ghost-branch'" in result.error_message


def test_execute_rebase_merge_conflict():
    """Test rebase failing with merge conflicts."""
    called_commands = []

    def mock_run(cmd, *_args, **_kwargs):
        called_commands.append(cmd)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

        if "clone" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "config" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "checkout" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "rev-parse" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="sha", stderr="")
        if "rebase" in cmd_str:
            if "abort" in cmd_str:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="Aborted", stderr="")
            # The actual rebase fails with conflicts
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="Conflict content...", stderr="error: Failed to merge"
            )
        if "diff" in cmd_str and "--diff-filter=U" in cmd_str:
            # Return some conflicting files
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout="src/main.py\nsrc/utils.py\n", stderr=""
            )
        if "status" in cmd_str and "--porcelain" in cmd_str:
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout="UU src/main.py\nUU src/utils.py\n", stderr=""
            )

        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="feature",
            target_branch="main",
        )

        assert result.status == RebaseStatus.CONFLICT
        assert "Rebase failed due to merge conflicts" in result.message
        assert result.conflicting_files == ["src/main.py", "src/utils.py"]
        assert "src/main.py" in result.conflict_summary
        assert "src/utils.py" in result.conflict_summary
        assert "git rebase --abort" in result.conflict_summary
        assert "git rebase --continue" in result.conflict_summary

        # Verify abort was called
        flat_cmds = [" ".join(c) for c in called_commands]
        assert any("git rebase --abort" in c for c in flat_cmds)


def test_execute_rebase_general_failure():
    """Test rebase failing without merge conflicts (e.g. general rebase error)."""

    def mock_run(cmd, *_args, **_kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

        if "clone" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "config" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "checkout" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "rev-parse" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="sha", stderr="")
        if "rebase" in cmd_str:
            if "abort" in cmd_str:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            # Rebase fails
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="Some non-conflict error", stderr="error: some bad state"
            )
        if "diff" in cmd_str:
            # No unmerged files
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "status" in cmd_str:
            # No unmerged files
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="feature",
            target_branch="main",
        )

        assert result.status == RebaseStatus.ERROR
        assert result.message == "Git rebase failed"
        assert "Some non-conflict error" in result.error_message


def test_execute_rebase_push_failure():
    """Test rebase succeeding but force pushing fails."""

    def mock_run(cmd, *_args, **_kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

        if "clone" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "config" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "fetch" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "checkout" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        if "rev-parse" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="sha", stderr="")
        if "rebase" in cmd_str:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="success", stderr="")
        if "push" in cmd_str:
            # Force push fails due to permission
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="fatal: Permission denied to push"
            )

        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        result = execute_rebase(
            repo_url="https://github.com/owner/repo.git",
            branch_name="feature",
            target_branch="main",
        )

        assert result.status == RebaseStatus.ERROR
        assert "force-pushing to origin failed" in result.message
        assert "Permission denied to push" in result.error_message


def test_execute_rebase_token_redaction():
    """Test that secrets in git error messages are redacted."""
    with patch("subprocess.run") as mock_run:
        # Clone fails and mentions the URL containing a sensitive github token
        token = "ghp_sensitivegithubtoken1234567890abcdef"
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr=f"fatal: Authentication failed for 'https://x-access-token:{token}@github.com/org/repo.git'",
        )

        result = execute_rebase(
            repo_url=f"https://x-access-token:{token}@github.com/org/repo.git",
            branch_name="feature",
            target_branch="main",
        )

        assert result.status == RebaseStatus.ERROR
        assert token not in result.error_message
        assert "[REDACTED]" in result.error_message
        assert "https://[REDACTED]@github.com/org/repo.git" in result.error_message
