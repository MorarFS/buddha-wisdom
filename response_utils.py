"""Helpers for interpreting responses from the text generation service."""


def extract_response_text(response):
    """Return nonempty text from a model response, if one was generated."""
    try:
        text = response.text
    except (AttributeError, ValueError):
        text = None
    if isinstance(text, str) and text.strip():
        return text.strip()

    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        text = "\n".join(
            part_text
            for part in parts
            if isinstance(part_text := getattr(part, "text", None), str)
            and part_text.strip()
        )
        if text:
            return text

    return None
