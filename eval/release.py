"""A live WhatsApp number waits for three passing runs of that business's set."""

PASSES_REQUIRED = 3


def consecutive_passes(results: list[bool]) -> int:
    count = 0
    for passed in reversed(results):
        if not passed:
            break
        count += 1
    return count


def live_number_allowed(results: list[bool]) -> bool:
    """True only after three passing runs in a row. Anything shorter stays dark."""
    return consecutive_passes(results) >= PASSES_REQUIRED
