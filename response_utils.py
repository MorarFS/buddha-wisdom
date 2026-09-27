"""Helpers for interpreting and checking text generation responses."""

import re
import unicodedata


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


def _letters(text):
    """Compare wording despite PDF line breaks, ligatures, and segment numbers."""
    return "".join(
        char for char in unicodedata.normalize("NFKC", text).casefold()
        if char.isalpha()
    )


def quotations_are_grounded(answer, corpus):
    """Require each displayed quotation and source label to match retrieval."""
    passages = {
        int(number): (source, body)
        for number, source, body in re.findall(
            r"(?ms)^\[Passage (\d+)\] \(Source: (.*?), Relevance: [^)]+\):\n"
            r"(.*?)(?=^\[Passage |\Z)",
            corpus,
        )
    }
    lines = answer.splitlines()
    found = 0
    index = 0

    while index < len(lines):
        if not lines[index].startswith(">"):
            index += 1
            continue

        quote_lines = []
        while index < len(lines) and lines[index].startswith(">"):
            quote_lines.append(lines[index][1:].strip())
            index += 1

        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            return False

        citation = re.search(
            r"\*\*Source:\*\*\s*(.*?)\s*;\s*"
            r"\*\*Retrieved passage:\*\*\s*\[?Passage\s+(\d+)\]?",
            lines[index],
        )
        if not citation:
            return False

        source, number = citation.group(1), int(citation.group(2))
        passage = passages.get(number)
        quote = _letters(" ".join(quote_lines))
        if not passage or source != passage[0] or len(quote) < 40:
            return False
        if quote not in _letters(passage[1]):
            return False
        found += 1
        index += 1

    return found >= 1


def add_pdf_page_citations(answer, pages_by_passage):
    """Append page ranges recovered from source footers to citation lines."""
    output = []
    for line in answer.splitlines(keepends=True):
        match = re.search(
            r"\*\*Retrieved passage:\*\*\s*\[?Passage\s+(\d+)\]?", line
        )
        pages = pages_by_passage.get(int(match.group(1))) if match else None
        if pages and "**PDF page" not in line:
            content = line.rstrip("\r\n")
            ending = line[len(content):]
            if content.endswith("."):
                content = content[:-1]
            first, last = pages
            page_text = (
                f"; **PDF page:** {first}"
                if first == last else f"; **PDF pages:** {first}-{last}"
            )
            line = content + page_text + "." + ending
        output.append(line)
    return "".join(output)
