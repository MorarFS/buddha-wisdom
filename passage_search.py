"""Collect the matching PDF excerpts behind a short generated answer."""

import re


SUTTA_REFERENCE = re.compile(
    r"(?m)^\s*(SN|MN|DN|AN|Ud|Iti|Snp|Thag|Thig)\s*"
    r"(\d+(?:\.\d+)?)\b"
)


def join_overlapping_chunks(first, second):
    """Join neighboring index chunks without repeating their shared tail."""
    anchor = second[:48]
    start = first.find(anchor)
    while start >= 0:
        if second.startswith(first[start:]):
            return first + second[len(first) - start:]
        start = first.find(anchor, start + 1)
    return first + "\n" + second


def matching_passages(index, similarities, score_margin=0.08):
    """Return every page-backed excerpt near the strongest sutta match.

    This is a scored search over the whole local index, rather than a fixed
    top-k list. Adjacent matching chunks from the same PDF are one result.
    """
    sources = index["sources"]
    pages = index["pdf_page_ranges"]
    eligible = [i for i, page in enumerate(pages) if page]
    if not eligible:
        return []

    best = max(float(similarities[i]) for i in eligible)
    threshold = min(best, max(0.45, best - score_margin))
    hits = [i for i in eligible if float(similarities[i]) >= threshold]
    groups = []
    for position in hits:
        next_reference = SUTTA_REFERENCE.match(index["texts"][position])
        group_reference = (
            SUTTA_REFERENCE.search(index["texts"][groups[-1][0]])
            if groups else None
        )
        starts_new_sutta = (
            next_reference and group_reference
            and next_reference.group(0).strip() != group_reference.group(0).strip()
        )
        if (groups and position == groups[-1][-1] + 1
                and sources[position] == sources[groups[-1][-1]]
                and not starts_new_sutta):
            groups[-1].append(position)
        else:
            groups.append([position])

    results = []
    for group in groups:
        excerpt = index["texts"][group[0]]
        for position in group[1:]:
            excerpt = join_overlapping_chunks(excerpt, index["texts"][position])
        first_page = min(pages[i][0] for i in group)
        last_page = max(pages[i][1] for i in group)
        references = list(dict.fromkeys(
            f"{match.group(1)} {match.group(2)}"
            for match in SUTTA_REFERENCE.finditer(excerpt)
        ))
        results.append({
            "source": sources[group[0]],
            "pdf_pages": [first_page, last_page],
            "sutta_reference": references[0] if len(references) == 1 else None,
            "text": excerpt.strip(),
            "score": max(float(similarities[i]) for i in group),
        })

    results.sort(key=lambda result: result["score"], reverse=True)
    return results
