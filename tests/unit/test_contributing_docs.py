import os
import pathlib

def test_contributing_md_exists():
    """Verify contributing.md exists and contains standard markdown elements."""
    contributing_path = pathlib.Path(__file__).parent.parent.parent / "docs" / "dev" / "contributing.md"
    assert contributing_path.exists(), f"contributing.md not found at {contributing_path}"
    
    with open(contributing_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Verify we removed typical en-dashes/em-dashes used in bullet descriptions or conversational styling
    assert " — " not in content
    
    # Check that basic expected headers are present
    assert "# Contributing to Forge" in content
    assert "## Pull request guidelines" in content
    assert "## Questions" in content
    
    # Check code block formatting
    assert "```bash" in content
    assert "uv run pytest tests/unit/ -v" in content

def test_contributing_md_no_periods_in_bullet_headers():
    """Verify contributing.md has standard colon phrasing rather than periods/AI structures in bullet lists."""
    contributing_path = pathlib.Path(__file__).parent.parent.parent / "docs" / "dev" / "contributing.md"
    with open(contributing_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "- **One thing per PR**:" in content
    assert "- **Tests for code changes**:" in content
    assert "- **No unrelated cleanup**:" in content
    assert "- **Short description**:" in content
