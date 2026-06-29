#!/usr/bin/env python3
"""
scripts/check-doc-freshness.py

A command-line script to analyze the repository for documentation drift when source files are modified.
It compares source code diffs against documentation, extracts updated class names, function signatures,
or configuration parameters, and checks if the referencing documentation was updated in the same change.
"""

import argparse
import contextlib
import os
import re
import subprocess
import sys

# Regex patterns to extract definitions from modified lines (starting with + or -)
CLASS_PATTERNS = [
    re.compile(r"^[+-]\s*class\s+([a-zA-Z0-9_]+)"),  # Python, JS, TS, etc.
    re.compile(r"^[+-]\s*type\s+([a-zA-Z0-9_]+)\s+struct"),  # Go structs
    re.compile(r"^[+-]\s*struct\s+([a-zA-Z0-9_]+)"),  # C, C++, Rust
    re.compile(r"^[+-]\s*interface\s+([a-zA-Z0-9_]+)"),  # TS, Go, Java
]

FUNC_PATTERNS = [
    re.compile(r"^[+-]\s*def\s+([a-zA-Z0-9_]+)"),  # Python
    re.compile(r"^[+-]\s*function\s+([a-zA-Z0-9_]+)"),  # JS, TS
    re.compile(r"^[+-]\s*fn\s+([a-zA-Z0-9_]+)"),  # Rust
    re.compile(r"^[+-]\s*func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)"),  # Go (with/without receiver)
]

# Config / Env Var patterns (ALL_CAPS variables)
ENV_VAR_PATTERN = re.compile(r"\b([A-Z_][A-Z0-9_]{3,})\b")

# For JSON, TOML, YAML config files (matching keys)
CONFIG_KEY_PATTERNS = [
    re.compile(r'^[+-]\s*["\']?([a-zA-Z0-9_-]+)["\']?\s*:'),  # JSON / YAML key
    re.compile(r"^[+-]\s*([a-zA-Z0-9_-]+)\s*="),  # TOML / INI key
]

# Standard words we ignore to avoid false positives for configuration parameters
IGNORED_WORDS = {
    "TRUE",
    "FALSE",
    "NONE",
    "NULL",
    "UTF8",
    "HTTP",
    "HTTPS",
    "JSON",
    "YAML",
    "TOML",
    "HTML",
    "UUID",
    "URL",
    "URI",
    "API",
    "IP",
    "TCP",
    "UDP",
    "CLI",
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "HEAD",
    "BASE",
    "MAIN",
    "ROOT",
    "PATH",
    "FILE",
    "DIR",
    "DATE",
    "TIME",
    "NAME",
    "TYPE",
    "DATA",
    "INFO",
    "TEST",
    "PORT",
    "HOST",
    "USER",
    "PASS",
    "AUTH",
    "MODE",
    "KEEP",
    "OPEN",
    "LOCK",
    "SAVE",
    "LOAD",
    "SYNC",
    "INIT",
    "DIFF",
    "GIT",
    "STDOUT",
    "STDERR",
    "PIPE",
    "CODE",
    "EXIT",
    "LINE",
}


def normalize_path(path: str) -> str:
    """
    Strips leading directory indicators and normalizes file paths.
    """
    p = os.path.normpath(path)
    if p.startswith("./"):
        p = p[2:]
    return p


def is_doc_file(filepath: str, docs_dir: str) -> bool:
    """
    Checks if a file path is a documentation file.
    """
    doc_extensions = {".md", ".rst", ".adoc", ".txt"}
    path_parts = filepath.split(os.sep)
    if docs_dir in path_parts:
        return True
    _, ext = os.path.splitext(filepath)
    return ext.lower() in doc_extensions


def parse_git_diff(diff_text: str) -> tuple[dict[str, list[str]], list[str]]:
    """
    Parses a git diff string.
    Returns:
      - A dictionary mapping changed source file paths to their added/modified lines.
      - A list of all changed file paths.
    """
    changed_files: list[str] = []
    file_diffs: dict[str, list[str]] = {}
    current_file: str | None = None

    for line in diff_text.splitlines():
        # Match diff header: e.g. "diff --git a/path/to/file b/path/to/file"
        match = re.match(r"^diff --git a/(.*?) b/(.*?)$", line)
        if match:
            current_file = normalize_path(match.group(2))
            changed_files.append(current_file)
            file_diffs[current_file] = []
            continue

        # Fallback file path parsing from headers
        if line.startswith("--- a/") and current_file is None:
            path = normalize_path(line[6:])
            current_file = path
            if current_file not in changed_files:
                changed_files.append(current_file)
            if current_file not in file_diffs:
                file_diffs[current_file] = []
            continue
        if line.startswith("+++ b/") and current_file is None:
            path = normalize_path(line[6:])
            current_file = path
            if current_file not in changed_files:
                changed_files.append(current_file)
            if current_file not in file_diffs:
                file_diffs[current_file] = []
            continue

        # Collect added/modified/removed lines
        if current_file and (line.startswith("+") or line.startswith("-")):
            if line.startswith("+++") or line.startswith("---"):
                continue
            file_diffs[current_file].append(line)

    return file_diffs, changed_files


def extract_elements(lines: list[str], filename: str) -> dict[str, set[str]]:
    """
    Extracts modified classes, functions, and configuration parameters from diff lines.
    """
    elements: dict[str, set[str]] = {"classes": set(), "functions": set(), "configs": set()}

    for line in lines:
        # Check class patterns
        class_matched = False
        for pattern in CLASS_PATTERNS:
            match = pattern.match(line)
            if match:
                elements["classes"].add(match.group(1))
                class_matched = True
                break
        if class_matched:
            continue

        # Check function patterns
        func_matched = False
        for pattern in FUNC_PATTERNS:
            match = pattern.match(line)
            if match:
                func_name = match.group(1)
                # Ignore dunder methods
                if not (func_name.startswith("__") and func_name.endswith("__")):
                    elements["functions"].add(func_name)
                    func_matched = True
                    break
        if func_matched:
            continue

        # Check json/toml/yaml config keys
        config_matched = False
        if filename.endswith((".json", ".toml", ".yaml", ".yml")):
            for pattern in CONFIG_KEY_PATTERNS:
                match = pattern.match(line)
                if match:
                    key = match.group(1)
                    if key.upper() not in IGNORED_WORDS and len(key) >= 3:
                        elements["configs"].add(key)
                        config_matched = True
                        break
        if config_matched:
            continue

        # Extract environment variables / configuration constants (ALL_CAPS) from source lines
        content = line[1:]
        for match in ENV_VAR_PATTERN.finditer(content):
            word = match.group(1)
            if word not in IGNORED_WORDS and len(word) >= 4:
                elements["configs"].add(word)

    return elements


def discover_docs(docs_dir: str, ignore_patterns: list[str]) -> list[str]:
    """
    Discovers all documentation files in the repository.
    """
    doc_files: list[str] = []

    # 1. Walk the docs_dir if it exists
    if os.path.exists(docs_dir):
        for root, _, files in os.walk(docs_dir):
            for file in files:
                filepath = normalize_path(os.path.join(root, file))
                if any(ignored in filepath for ignored in ignore_patterns):
                    continue
                _, ext = os.path.splitext(filepath)
                if ext.lower() in {".md", ".rst", ".adoc", ".txt"}:
                    doc_files.append(filepath)

    # 2. Look for main doc files in other parts of the repository (excluding ignored dirs)
    for root, dirs, files in os.walk("."):
        # Prune ignored directories in place
        dirs[:] = [
            d
            for d in dirs
            if not any(
                ignored in normalize_path(os.path.join(root, d)) for ignored in ignore_patterns
            )
        ]
        for file in files:
            filepath = normalize_path(os.path.join(root, file))
            if filepath in doc_files:
                continue
            if any(ignored in filepath for ignored in ignore_patterns):
                continue
            if file.upper() in {"README.MD", "CLAUDE.MD", "CONTRIBUTING.MD", "DOCS.MD"}:
                doc_files.append(filepath)

    return doc_files


def get_git_diff(base: str | None, head: str | None) -> str:
    """
    Executes a git diff command to retrieve the diff string.
    """
    cmd = ["git", "diff"]
    if base and head:
        cmd.append(f"{base}..{head}")
    elif base:
        cmd.append(base)
    else:
        cmd.append("HEAD")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Fallback to HEAD~1 if diff is empty and no base was specified
        if not result.stdout.strip() and not base:
            cmd = ["git", "diff", "HEAD~1..HEAD"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(
            f"Warning: Git diff command execution failed or git is not initialized: {e}",
            file=sys.stderr,
        )
        return ""


def run_analysis(args: argparse.Namespace) -> int:
    """
    Main analysis orchestrator.
    Returns 0 on success (no drift), and 1 if drift is detected (and not warned only).
    """
    # 1. Retrieve the git diff
    if args.diff_file:
        try:
            with open(args.diff_file, encoding="utf-8") as f:
                diff_text = f.read()
        except Exception as e:
            print(f"Error reading diff file {args.diff_file}: {e}", file=sys.stderr)
            return 1
    else:
        diff_text = get_git_diff(args.base, args.head)

    if not diff_text.strip():
        print("No changes detected in git diff. Documentation is fresh.")
        return 0

    # 2. Parse the diff to get changed files and lines
    file_diffs, changed_files = parse_git_diff(diff_text)

    # 3. Categorize changed files
    changed_docs: set[str] = set()
    changed_sources: dict[str, list[str]] = {}

    # Standard ignore patterns
    ignore_patterns = args.ignore_patterns or [
        ".git",
        ".forge",
        ".venv",
        "tests",
        "__pycache__",
        "node_modules",
        "vendor",
    ]

    for filepath in changed_files:
        if any(ignored in filepath for ignored in ignore_patterns):
            continue
        if is_doc_file(filepath, args.docs_dir):
            changed_docs.add(filepath)
        else:
            if filepath in file_diffs:
                changed_sources[filepath] = file_diffs[filepath]

    if args.verbose:
        print(f"Parsed changed source files: {list(changed_sources.keys())}")
        print(f"Parsed changed documentation files: {list(changed_docs)}")

    # 4. Extract modified elements
    extracted_elements: dict[str, dict[str, str]] = {}  # element_name -> {"type": ..., "file": ...}

    for filepath, lines in changed_sources.items():
        elements = extract_elements(lines, filepath)
        for element_type, names in elements.items():
            for name in names:
                # Map standard plural keys to singular representation for display
                singular_type = (
                    "Class"
                    if element_type == "classes"
                    else "Function"
                    if element_type == "functions"
                    else "Config"
                )
                extracted_elements[name] = {"type": singular_type, "file": filepath}

    if args.verbose:
        print(f"Extracted modified elements: {extracted_elements}")

    if not extracted_elements:
        print("No modified classes, functions, or config parameters found in the source diff.")
        return 0

    # 5. Discover all documentation files
    doc_files = discover_docs(args.docs_dir, ignore_patterns)
    if args.verbose:
        print(f"Discovered documentation files to scan: {doc_files}")

    # 6. Read and cache doc contents
    doc_contents: dict[str, str] = {}
    for doc_path in doc_files:
        with contextlib.suppress(Exception), open(doc_path, encoding="utf-8") as f:
            doc_contents[doc_path] = f.read()

    # 7. Check for documentation drift
    drifts: list[dict[str, str]] = []

    for element_name, info in extracted_elements.items():
        # Match using word boundaries to ensure we match the exact element name
        pattern = rf"\b{re.escape(element_name)}\b"

        for doc_path, content in doc_contents.items():
            if re.search(pattern, content) and doc_path not in changed_docs:
                drifts.append(
                    {
                        "element": element_name,
                        "type": info["type"],
                        "source_file": info["file"],
                        "doc_file": doc_path,
                    }
                )

    # 8. Print Results
    print(f"Analysis complete. Found {len(extracted_elements)} modified source elements.")

    if not drifts:
        print("✅ Documentation is fresh! No documentation drift detected.")
        return 0

    print(f"\n❌ Detected {len(drifts)} documentation drift(s):")
    for drift in drifts:
        print(
            f"  - [{drift['type']}] '{drift['element']}' modified in '{drift['source_file']}' "
            f"but referencing doc '{drift['doc_file']}' was not updated."
        )

    if args.warn_only:
        print("\nWarning: Drift detected, but exit code 0 because --warn-only was specified.")
        return 0

    print(
        "\nError: Documentation drift detected. Please update the stale documentation files in the same commit."
    )
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify documentation freshness and detect documentation drift."
    )
    parser.add_argument(
        "--base", help="Base git reference to compare against (e.g. main, origin/main)."
    )
    parser.add_argument(
        "--head", default="HEAD", help="Head git reference to compare (defaults to HEAD)."
    )
    parser.add_argument(
        "--diff-file",
        help="Path to a file containing a pre-generated git diff (bypasses git command run).",
    )
    parser.add_argument(
        "--docs-dir",
        default="docs",
        help="Directory containing documentation (defaults to 'docs').",
    )
    parser.add_argument(
        "--ignore-patterns",
        nargs="+",
        help="List of path patterns or substrings to ignore (e.g. tests, node_modules).",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Print warnings instead of returning a non-zero exit code on drift.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Print verbose execution and debug logs."
    )

    args = parser.parse_args()
    sys.exit(run_analysis(args))


if __name__ == "__main__":
    main()
