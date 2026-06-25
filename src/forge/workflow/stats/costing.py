"""LLM cost calculation helpers for workflow statistics.

This module provides utilities for computing per-stage LLM costs from token
counts using a configurable pricing table.
"""


def calculate_stage_cost(
    model_name: str | None,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, dict[str, float]],
) -> tuple[float | None, float | None]:
    """Compute the input and output cost for a single stage.

    Performs a substring/prefix match of *model_name* against the keys in
    *pricing* (longest matching key wins for disambiguation).  Rates are
    expressed in dollars per million tokens ($/MTok).

    Args:
        model_name: The LLM model name recorded for the stage, or ``None``
            when the stage did not invoke an LLM.
        input_tokens: Total prompt tokens consumed by the stage.
        output_tokens: Total completion tokens produced by the stage.
        pricing: Mapping of model-name substrings to
            ``{"input": <$/MTok>, "output": <$/MTok>}`` rate entries.

    Returns:
        A ``(input_cost, output_cost)`` tuple in dollars.  Both values are
        ``None`` when *model_name* is ``None`` or when no pricing key matches.
    """
    if model_name is None:
        return (None, None)

    name_lower = model_name.lower()

    # Find the longest pricing key that is a substring of the model name.
    best_key: str | None = None
    for key in pricing:
        if key.lower() in name_lower and (best_key is None or len(key) > len(best_key)):
            best_key = key

    if best_key is None:
        return (None, None)

    rates = pricing[best_key]
    input_rate: float = rates.get("input", 0.0)
    output_rate: float = rates.get("output", 0.0)

    input_cost = input_tokens / 1_000_000 * input_rate
    output_cost = output_tokens / 1_000_000 * output_rate

    return (input_cost, output_cost)
