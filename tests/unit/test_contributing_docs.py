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
