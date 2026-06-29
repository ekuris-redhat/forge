"""Comment classification for Forge Q&A mode."""

import re
from enum import StrEnum


class CommentType(StrEnum):
    """Type of comment detected in Jira comments."""

    QUESTION = "question"
    FEEDBACK = "feedback"
    INFORMATIONAL = "informational"


# Pattern for @forge ask (case insensitive)
_FORGE_ASK_PATTERN = re.compile(r"^\s*@forge\s+ask", re.IGNORECASE)

# Pattern for question mark at start (allowing leading whitespace)
_QUESTION_MARK_PATTERN = re.compile(r"^\s*\?")

# Pattern for revision prefix (allowing leading whitespace)
_REVISION_PATTERN = re.compile(r"^\s*!")


def strip_comment_prefix(comment_text: str) -> str:
    """Strip prefix characters from a comment if it starts with '!'.

    This function strips the leading '!' (and any additional sequential '!'
    or surrounding/following whitespace) from comments classified as FEEDBACK.

    Args:
        comment_text: The text of the comment to strip.

    Returns:
        The stripped comment text.
    """
    if not comment_text:
        return ""
    if _REVISION_PATTERN.match(comment_text):
        return re.sub(r"^\s*!+\s*", "", comment_text)
    return comment_text


def extract_prefix_character(comment_text: str) -> str | None:
    """Extract the prefix character or string from the comment text if present.

    Recognized prefixes are '!', '?', or '@forge ask'.

    Args:
        comment_text: The comment text to inspect.

    Returns:
        The matched prefix string (e.g. '!', '?', or '@forge ask') or None.
    """
    if not comment_text:
        return None
    if _REVISION_PATTERN.match(comment_text):
        return "!"
    if _QUESTION_MARK_PATTERN.match(comment_text):
        return "?"
    match = _FORGE_ASK_PATTERN.match(comment_text)
    if match:
        return match.group(0).strip()
    return None


def classify_comment(comment_text: str) -> CommentType:
    """Classify a comment into question, feedback, or informational.

    Classification rules:
    - Questions: Comments starting with '?' or '@forge ask' (case-insensitive)
    - Feedback (revision request): Comments starting with '!'
    - Informational: Everything else — ignored by the workflow

    Approvals are handled exclusively via label changes (forge:*-approved),
    not via comment text.

    Args:
        comment_text: The text of the comment to classify.

    Returns:
        The classified comment type.
    """
    if not comment_text or not comment_text.strip():
        return CommentType.INFORMATIONAL

    if _QUESTION_MARK_PATTERN.match(comment_text):
        return CommentType.QUESTION

    if _FORGE_ASK_PATTERN.match(comment_text):
        return CommentType.QUESTION

    if _REVISION_PATTERN.match(comment_text):
        return CommentType.FEEDBACK

    return CommentType.INFORMATIONAL
