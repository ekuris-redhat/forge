import argparse
import importlib.util
import os
import sys
from pathlib import Path

# Load check-doc-freshness.py module dynamically since it has a hyphen in its filename
script_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../scripts/check-doc-freshness.py")
)
spec = importlib.util.spec_from_file_location("check_doc_freshness", script_path)
assert spec is not None
assert spec.loader is not None
cdf = importlib.util.module_from_spec(spec)
sys.modules["check_doc_freshness"] = cdf
spec.loader.exec_module(cdf)


def test_normalize_path() -> None:
    assert cdf.normalize_path("./src/file.py") == "src/file.py"
    assert cdf.normalize_path("src/file.py") == "src/file.py"
    assert (
        cdf.normalize_path("/workspace/src/file.py") == "/workspace/src/file.py"
        if os.name == "nt"
        else "workspace/src/file.py"
    )


def test_is_doc_file() -> None:
    assert cdf.is_doc_file("docs/workflows.md", "docs") is True
    assert cdf.is_doc_file("src/forge/config.py", "docs") is False
    assert cdf.is_doc_file("README.md", "docs") is True
    assert cdf.is_doc_file("CONTRIBUTING.md", "docs") is True


def test_parse_git_diff() -> None:
    diff_text = """diff --git a/src/forge/workflow/nodes/triage.py b/src/forge/workflow/nodes/triage.py
index 123456..789101 100644
--- a/src/forge/workflow/nodes/triage.py
+++ b/src/forge/workflow/nodes/triage.py
@@ -10,3 +10,4 @@
+class FeatureWorkflow:
-def parse_option_comment():
+def parse_option_comment_new():
"""
    file_diffs, changed_files = cdf.parse_git_diff(diff_text)

    assert "src/forge/workflow/nodes/triage.py" in changed_files
    assert len(changed_files) == 1

    lines = file_diffs["src/forge/workflow/nodes/triage.py"]
    assert "+class FeatureWorkflow:" in lines
    assert "-def parse_option_comment():" in lines
    assert "+def parse_option_comment_new():" in lines


def test_extract_elements() -> None:
    lines = [
        "+class FeatureWorkflow:",
        "-def parse_option_comment():",
        "+def parse_option_comment_new():",
        "+    FORGE_CONTAINER_KEEP = True",
        "+    dummy_variable = 1",
        "+    # ignored words: NONE, TRUE",
    ]
    elements = cdf.extract_elements(lines, "src/forge/workflow/nodes/triage.py")

    assert "FeatureWorkflow" in elements["classes"]
    assert "parse_option_comment" in elements["functions"]
    assert "parse_option_comment_new" in elements["functions"]
    assert "FORGE_CONTAINER_KEEP" in elements["configs"]

    # Assert ignored words/variables are not collected
    assert "NONE" not in elements["configs"]
    assert "TRUE" not in elements["configs"]
    assert "dummy_variable" not in elements["configs"]


def test_extract_elements_go_and_config() -> None:
    # Test Go elements
    go_lines = [
        "+type MyStruct struct {",
        "+func (r *MyReceiver) RunTask() {",
    ]
    go_elements = cdf.extract_elements(go_lines, "src/main.go")
    assert "MyStruct" in go_elements["classes"]
    assert "RunTask" in go_elements["functions"]

    # Test JSON config elements
    json_lines = [
        '+"custom_dir": "docs/assets/templates",',
        '+"timeout": 30,',
    ]
    json_elements = cdf.extract_elements(json_lines, "config.json")
    assert "custom_dir" in json_elements["configs"]
    assert "timeout" in json_elements["configs"]


def test_discover_docs(tmp_path: Path) -> None:
    # Setup mock file structure using tmp_path
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    doc1 = docs_dir / "architecture.md"
    doc1.write_text("architecture docs")

    doc2 = docs_dir / "sub" / "workflows.md"
    os.makedirs(doc2.parent, exist_ok=True)
    doc2.write_text("workflow docs")

    readme = tmp_path / "README.md"
    readme.write_text("readme")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    doc_in_tests = tests_dir / "ignored_doc.md"
    doc_in_tests.write_text("ignored test docs")

    # Change CWD to tmp_path to test discover_docs
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        doc_files = cdf.discover_docs("docs", [".git", ".forge", "tests"])
        normalized_doc_files = [os.path.normpath(f) for f in doc_files]

        assert os.path.normpath("docs/architecture.md") in normalized_doc_files
        assert os.path.normpath("docs/sub/workflows.md") in normalized_doc_files
        assert os.path.normpath("README.md") in normalized_doc_files
        assert os.path.normpath("tests/ignored_doc.md") not in normalized_doc_files
    finally:
        os.chdir(original_cwd)


def test_run_analysis_no_drift(tmp_path: Path) -> None:
    # Create mock documentation and source files on disk
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    doc_file = docs_dir / "architecture.md"
    doc_file.write_text("This mentions FeatureWorkflow class.")

    # Create diff file where FeatureWorkflow is modified, and the doc file is ALSO modified
    diff_text = """diff --git a/src/forge/workflow/nodes/triage.py b/src/forge/workflow/nodes/triage.py
index 123456..789101 100644
--- a/src/forge/workflow/nodes/triage.py
+++ b/src/forge/workflow/nodes/triage.py
@@ -10,3 +10,4 @@
+class FeatureWorkflow:

diff --git a/docs/architecture.md b/docs/architecture.md
index 111111..222222 100644
--- a/docs/architecture.md
+++ b/docs/architecture.md
@@ -1,1 +1,2 @@
 This mentions FeatureWorkflow class.
+Additional update.
"""
    diff_file = tmp_path / "test.diff"
    diff_file.write_text(diff_text)

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        args = argparse.Namespace(
            base=None,
            head="HEAD",
            diff_file=str(diff_file),
            docs_dir="docs",
            ignore_patterns=[".git", ".forge", "tests"],
            warn_only=False,
            verbose=True,
        )

        exit_code = cdf.run_analysis(args)
        assert exit_code == 0
    finally:
        os.chdir(original_cwd)


def test_run_analysis_with_drift(tmp_path: Path) -> None:
    # Create mock documentation on disk
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    doc_file = docs_dir / "architecture.md"
    doc_file.write_text("This mentions FeatureWorkflow class.")

    # Create diff file where FeatureWorkflow is modified, but doc file is NOT modified
    diff_text = """diff --git a/src/forge/workflow/nodes/triage.py b/src/forge/workflow/nodes/triage.py
index 123456..789101 100644
--- a/src/forge/workflow/nodes/triage.py
+++ b/src/forge/workflow/nodes/triage.py
@@ -10,3 +10,4 @@
+class FeatureWorkflow:
"""
    diff_file = tmp_path / "test.diff"
    diff_file.write_text(diff_text)

    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # 1. Run with warn_only = False (should fail / exit 1)
        args_fail = argparse.Namespace(
            base=None,
            head="HEAD",
            diff_file=str(diff_file),
            docs_dir="docs",
            ignore_patterns=[".git", ".forge", "tests"],
            warn_only=False,
            verbose=True,
        )

        exit_code = cdf.run_analysis(args_fail)
        assert exit_code == 1

        # 2. Run with warn_only = True (should pass / exit 0)
        args_warn = argparse.Namespace(
            base=None,
            head="HEAD",
            diff_file=str(diff_file),
            docs_dir="docs",
            ignore_patterns=[".git", ".forge", "tests"],
            warn_only=True,
            verbose=True,
        )

        exit_code = cdf.run_analysis(args_warn)
        assert exit_code == 0
    finally:
        os.chdir(original_cwd)


def test_check_bypass_conditions(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    # Test 1: env var bypass
    with patch.dict(os.environ, {"SKIP_DOC_FRESHNESS": "true"}):
        args = argparse.Namespace(verbose=True)
        assert cdf.check_bypass_conditions(args) is True

    # When SKIP_DOC_FRESHNESS is "false" and there is no git commit bypass, it should be False
    with (
        patch.dict(os.environ, {"SKIP_DOC_FRESHNESS": "false"}),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="A standard commit message")
        args = argparse.Namespace(verbose=True)
        assert cdf.check_bypass_conditions(args) is False

    # Test 2: commit message bypass
    with (
        patch.dict(os.environ, {"SKIP_DOC_FRESHNESS": "false"}),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="[skip doc-freshness]\nSome comment")
        args = argparse.Namespace(verbose=True)
        assert cdf.check_bypass_conditions(args) is True

    # Test 3: GITHUB_EVENT_PATH bypass with label
    event_file = tmp_path / "event.json"
    import json

    event_data = {
        "pull_request": {
            "labels": [{"name": "skip-doc-freshness"}],
            "title": "A standard PR title",
            "body": "No skip inside body",
        }
    }
    event_file.write_text(json.dumps(event_data))

    with (
        patch.dict(
            os.environ, {"SKIP_DOC_FRESHNESS": "false", "GITHUB_EVENT_PATH": str(event_file)}
        ),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="A standard commit")
        args = argparse.Namespace(verbose=True)
        assert cdf.check_bypass_conditions(args) is True

    # Test 4: GITHUB_EVENT_PATH bypass with title skip
    event_data_title = {
        "pull_request": {
            "labels": [],
            "title": "[skip docs] Update main entrypoint",
            "body": "No skip inside body",
        }
    }
    event_file.write_text(json.dumps(event_data_title))
    with (
        patch.dict(
            os.environ, {"SKIP_DOC_FRESHNESS": "false", "GITHUB_EVENT_PATH": str(event_file)}
        ),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="A standard commit")
        args = argparse.Namespace(verbose=True)
        assert cdf.check_bypass_conditions(args) is True
