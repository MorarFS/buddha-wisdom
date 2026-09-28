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


def _letter_positions(text):
    """Keep source offsets while comparing text across PDF line breaks."""
    letters = []
    positions = []
    for offset, char in enumerate(text):
        for normalized in unicodedata.normalize("NFKC", char).casefold():
            if normalized.isalpha():
                letters.append(normalized)
                positions.append(offset)
    return "".join(letters), positions


def _quote_offset(quote, body):
    """Locate verbatim words, allowing one short PDF running header midword."""
    wanted = _letters(quote)
    if len(wanted) < 40:
        return None
    source, positions = _letter_positions(body)
    exact = source.find(wanted)
    if exact >= 0:
        return positions[exact]

    # PDF extraction sometimes inserts a page heading into a hyphenated word.
    # The displayed quote must still contain every source letter in order.
    anchor = wanted[:20]
    start = source.find(anchor)
    while start >= 0:
        prefix = 0
        while (prefix < len(wanted) and start + prefix < len(source)
               and wanted[prefix] == source[start + prefix]):
            prefix += 1
        if (start + prefix >= len(positions)
                or not body[:positions[start + prefix]].endswith("-\n")):
            start = source.find(anchor, start + 1)
            continue
        for skipped in range(1, 25):
            remainder = source[start + prefix + skipped:
                               start + len(wanted) + skipped]
            if wanted[prefix:] == remainder:
                return positions[start]
        start = source.find(anchor, start + 1)
    return None


def grounded_answer(answer, corpus):
    """Keep the quotations that match the retrieved sutta wording.

    Citation labels and sutta links are rebuilt from the matching passages,
    since the model can abbreviate a source or guess a link.
    """
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
    output = []

    while index < len(lines):
        if not lines[index].startswith(">"):
            output.append(lines[index])
            index += 1
            continue

        quote_lines = []
        block_lines = []
        while index < len(lines) and lines[index].startswith(">"):
            quote_lines.append(lines[index][1:].strip())
            block_lines.append(lines[index])
            index += 1

        while index < len(lines) and not lines[index].strip():
            block_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            return None

        citation = re.search(
            r"\*\*Source:\*\*\s*(.*?)\s*;\s*"
            r"\*\*Retrieved passage:\*\*\s*\[?Passage\s+(\d+)\]?",
            lines[index],
        )
        if not citation:
            return None

        source, number = citation.group(1), int(citation.group(2))
        passage = passages.get(number)
        if not passage or not (
            source == passage[0] or passage[0].startswith(source + " ")
        ):
            index += 1
            continue
        offset = _quote_offset(" ".join(quote_lines), passage[1])
        if offset is None:
            index += 1
            continue

        sutta_marker = None
        for marker in re.finditer(
            r"(?m)^\s*(SN|MN|DN|AN|Ud|Iti|Snp|Thag|Thig)\s*"
            r"(\d+(?:\.\d+)?)\b", passage[1][:offset]
        ):
            sutta_marker = marker
        citation_line = (
            f"**Source:** {passage[0]}; **Retrieved passage:** Passage {number}"
        )
        if sutta_marker:
            label = f"{sutta_marker.group(1)} {sutta_marker.group(2)}"
            slug = f"{sutta_marker.group(1).lower()}{sutta_marker.group(2)}"
            citation_line += (
                f"; **Sutta page:** [{label}]"
                f"(https://suttacentral.net/{slug}/en/sujato)"
            )
        output.extend(block_lines)
        output.append(citation_line + ".")
        found += 1
        index += 1

    return "\n".join(output) if found >= 1 else None


def quotations_are_grounded(answer, corpus):
    """Report whether each displayed quotation has a source match."""
    return grounded_answer(answer, corpus) is not None


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
