"""Automated Git Rebase and Conflict Management Engine."""

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum

from forge.utils.redaction import redact_secrets

logger = logging.getLogger(__name__)


class RebaseStatus(StrEnum):
    """Status of the automated git rebase operation."""

    SUCCESS = "success"
    CONFLICT = "conflict"
    ERROR = "error"


@dataclass
class RebaseResult:
    """Result of an automated git rebase operation.

    Attributes:
        status: The outcome status (success, conflict, error).
        message: Descriptive summary of the outcome.
        conflicting_files: List of conflicting files if status is CONFLICT, else None.
        conflict_summary: Formatted markdown summary of conflicts if status is CONFLICT, else None.
        output: Raw stdout/stderr of the git commands.
        error_message: Detailed error message if status is ERROR, else None.
    """

    status: RebaseStatus
    message: str
    conflicting_files: list[str] | None = None
    conflict_summary: str | None = None
    output: str | None = None
    error_message: str | None = None


def execute_rebase(repo_url: str, branch_name: str, target_branch: str) -> RebaseResult:
    """Executes automated git rebase operations in an isolated temporary directory.

    Clones the repository from `repo_url`, checks out `branch_name`,
    rebases it onto `target_branch`, and pushes the rebased branch back if there are no conflicts.

    If conflicts are encountered, captures the conflict details, aborts the rebase safely,
    and returns a structured result with a helpful markdown conflict summary.

    Args:
        repo_url: URL of the git repository to clone.
        branch_name: Name of the feature/source branch to rebase.
        target_branch: Name of the target branch to rebase onto (e.g. 'main').

    Returns:
        A structured RebaseResult containing status, message, and details.
    """
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Clone the repository
            clone_cmd = ["git", "clone", repo_url, temp_dir]
            try:
                clone_res = subprocess.run(
                    clone_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                return RebaseResult(
                    status=RebaseStatus.ERROR,
                    message="Git clone timed out",
                    error_message="The git clone command exceeded the timeout of 300 seconds.",
                )

            if clone_res.returncode != 0:
                return RebaseResult(
                    status=RebaseStatus.ERROR,
                    message="Git clone failed",
                    error_message=redact_secrets(
                        clone_res.stderr or clone_res.stdout or "Unknown clone failure"
                    ),
                )

            # Configure git identity in this repo to prevent identity errors during rebase
            subprocess.run(
                ["git", "config", "user.name", "Forge Rebase Engine"],
                cwd=temp_dir,
                check=False,
            )
            subprocess.run(
                ["git", "config", "user.email", "forge-rebase@noreply.anthropic.com"],
                cwd=temp_dir,
                check=False,
            )

            # 2. Fetch origin to make sure we have all remote branch references
            fetch_res = subprocess.run(
                ["git", "fetch", "origin"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if fetch_res.returncode != 0:
                return RebaseResult(
                    status=RebaseStatus.ERROR,
                    message="Git fetch failed",
                    error_message=redact_secrets(fetch_res.stderr or fetch_res.stdout),
                )

            # 3. Checkout branch_name.
            # First, try to track origin/branch_name
            checkout_res = subprocess.run(
                ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            if checkout_res.returncode != 0:
                # If tracking origin/branch_name failed (e.g. branch is already local or origin doesn't have it),
                # try checking out branch_name directly
                checkout_res = subprocess.run(
                    ["git", "checkout", branch_name],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )

            if checkout_res.returncode != 0:
                return RebaseResult(
                    status=RebaseStatus.ERROR,
                    message=f"Failed to checkout branch '{branch_name}'",
                    error_message=redact_secrets(checkout_res.stderr or checkout_res.stdout),
                )

            # 4. Fetch the target branch to ensure it exists locally or on remote
            subprocess.run(
                ["git", "fetch", "origin", target_branch],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )

            # Verify the target branch reference
            rebase_target = f"origin/{target_branch}"
            verify_res = subprocess.run(
                ["git", "rev-parse", "--verify", rebase_target],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if verify_res.returncode != 0:
                # Fallback to local or try verify as-is
                verify_local = subprocess.run(
                    ["git", "rev-parse", "--verify", target_branch],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if verify_local.returncode == 0:
                    rebase_target = target_branch
                else:
                    return RebaseResult(
                        status=RebaseStatus.ERROR,
                        message=f"Target branch '{target_branch}' not found",
                        error_message=(
                            f"Could not locate '{target_branch}' as a local branch or "
                            f"'origin/{target_branch}' on remote."
                        ),
                    )

            # 5. Execute rebase
            rebase_res = subprocess.run(
                ["git", "rebase", rebase_target],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )

            if rebase_res.returncode == 0:
                # Clean rebase! Force push back to origin
                push_res = subprocess.run(
                    ["git", "push", "origin", branch_name, "--force"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
                if push_res.returncode == 0:
                    return RebaseResult(
                        status=RebaseStatus.SUCCESS,
                        message=f"Successfully rebased '{branch_name}' onto '{target_branch}' and pushed to origin.",
                        output=redact_secrets(push_res.stdout + "\n" + push_res.stderr),
                    )
                else:
                    return RebaseResult(
                        status=RebaseStatus.ERROR,
                        message="Rebase succeeded but force-pushing to origin failed",
                        error_message=redact_secrets(push_res.stderr or push_res.stdout),
                    )

            # Rebase failed — check for unmerged paths/conflicts
            # 1. Get the list of conflicting files
            conflict_check = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            conflicting_files = [
                line.strip() for line in conflict_check.stdout.splitlines() if line.strip()
            ]

            # 2. Double check status --porcelain for other unmerged states
            status_res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            for line in status_res.stdout.splitlines():
                if len(line) >= 4:
                    prefix = line[:2]
                    # Any unmerged status starting with U, or AA, DD, etc.
                    if "U" in prefix or prefix in ("AA", "DD"):
                        file_path = line[3:].strip()
                        if file_path not in conflicting_files:
                            conflicting_files.append(file_path)

            # De-duplicate conflicts list
            seen = set()
            conflicting_files = [x for x in conflicting_files if not (x in seen or seen.add(x))]

            if conflicting_files:
                # Yes, we have merge conflicts!
                # Abort the rebase safely
                subprocess.run(
                    ["git", "rebase", "--abort"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                # Format a helpful markdown summary
                file_list_markdown = "\n".join(f"- `{f}`" for f in conflicting_files)
                raw_output = redact_secrets(rebase_res.stdout + "\n" + rebase_res.stderr)

                conflict_summary = (
                    f"### Merge Conflicts Detected\n\n"
                    f"An automated rebase of branch `{branch_name}` onto `{target_branch}` "
                    f"failed due to merge conflicts. "
                    f"The following files contain conflicts that must be resolved manually:\n\n"
                    f"{file_list_markdown}\n\n"
                    f"**To resolve these conflicts locally:**\n"
                    f"1. Fetch the latest changes:\n"
                    f"   ```bash\n"
                    f"   git fetch origin\n"
                    f"   ```\n"
                    f"2. Checkout your branch:\n"
                    f"   ```bash\n"
                    f"   git checkout {branch_name}\n"
                    f"   ```\n"
                    f"3. Run the rebase command:\n"
                    f"   ```bash\n"
                    f"   git rebase origin/{target_branch}\n"
                    f"   ```\n"
                    f"4. Open the conflicting files listed above, resolve the conflicts, and stage the changes:\n"
                    f"   ```bash\n"
                    f"   git add <file>\n"
                    f"   ```\n"
                    f"5. Continue the rebase:\n"
                    f"   ```bash\n"
                    f"   git rebase --continue\n"
                    f"   ```\n"
                    f"6. Force-push the updated branch:\n"
                    f"   ```bash\n"
                    f"   git push origin {branch_name} --force-with-lease\n"
                    f"   ```\n\n"
                    f"Note: The automated engine has safely aborted the rebase attempt on the server using `git rebase --abort`.\n\n"
                    f"<details>\n"
                    f"<summary>Raw Git Rebase Output</summary>\n\n"
                    f"```\n"
                    f"{raw_output}\n"
                    f"```\n"
                    f"</details>"
                )

                return RebaseResult(
                    status=RebaseStatus.CONFLICT,
                    message=f"Rebase failed due to merge conflicts in {len(conflicting_files)} file(s).",
                    conflicting_files=conflicting_files,
                    conflict_summary=conflict_summary,
                    output=raw_output,
                )

            # Standard rebase failure (not a merge conflict)
            # Abort the rebase safely just in case it is still in progress
            subprocess.run(["git", "rebase", "--abort"], cwd=temp_dir, check=False)

            rebase_error = (rebase_res.stderr or "") + "\n" + (rebase_res.stdout or "")
            return RebaseResult(
                status=RebaseStatus.ERROR,
                message="Git rebase failed",
                error_message=redact_secrets(rebase_error.strip() or "Unknown rebase failure"),
            )

    except Exception as e:
        logger.exception(f"Unexpected error during automated rebase: {e}")
        return RebaseResult(
            status=RebaseStatus.ERROR,
            message="An unexpected error occurred during rebase",
            error_message=redact_secrets(str(e)),
        )
