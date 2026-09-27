"""Recover conservative printed PDF page ranges from the existing index text."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
import re


# The deployed index uses 1,200-character chunks with 200 characters of overlap.
# Newly built indexes record their own stride in create_local_index.py.
LEGACY_CHUNK_STRIDE = 1000
SUTTA_REF = r"(?:AN|DN|MN|SN|Dhp|Ud|Iti|Thag|Thig|Snp)[ \t]+[\d.]+(?:[–-]\d+)?"
PAGE_FOOTER = re.compile(
    rf"(?im)^[ \t]*(?:(?P<left>\d{{1,4}})[ \t]+{SUTTA_REF}|"
    rf"{SUTTA_REF}[ \t]+(?P<right>\d{{1,4}}))[ \t]*$"
)


def infer_pdf_page_ranges(index):
    """Return a narrow range for each chunk, or None when markers are uncertain.

    SuttaCentral's printed page number appears in each page footer. A chunk
    between footers N and N+1 belongs to page N+1. Gaps yield a conservative
    page range, and wide or contradictory gaps are left uncited.
    """
    texts = index["texts"]
    sources = index["sources"]
    stride = index.get("chunk_stride", LEGACY_CHUNK_STRIDE)
    local_numbers = defaultdict(int)
    chunk_positions = []
    markers = defaultdict(list)

    for text, source in zip(texts, sources):
        local_number = local_numbers[source]
        local_numbers[source] += 1
        start = local_number * stride
        chunk_positions.append((source, start, start + len(text)))
        for match in PAGE_FOOTER.finditer(text):
            page = int(match.group("left") or match.group("right"))
            markers[source].append((start + match.start(), page))

    page_positions = {}
    page_numbers = {}
    for source, source_markers in markers.items():
        deduplicated = []
        for position, page in sorted(source_markers):
            if (
                deduplicated
                and deduplicated[-1][1] == page
                and position - deduplicated[-1][0] <= 250
            ):
                continue
            deduplicated.append((position, page))
        page_positions[source] = [position for position, _ in deduplicated]
        page_numbers[source] = [page for _, page in deduplicated]

    ranges = []
    for source, start, end in chunk_positions:
        positions = page_positions.get(source, [])
        numbers = page_numbers.get(source, [])
        before = bisect_right(positions, start - 20) - 1
        after = bisect_left(positions, end + 20)
        if before < 0 or after >= len(positions):
            ranges.append(None)
            continue
        first = numbers[before] + 1
        last = numbers[after]
        if not (first <= last <= first + 2) or positions[after] - positions[before] > 8000:
            ranges.append(None)
        else:
            ranges.append((first, last))

    return ranges
