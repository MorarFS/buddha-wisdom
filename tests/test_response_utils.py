import unittest
from types import SimpleNamespace

from response_utils import (
    add_pdf_page_citations,
    extract_response_text,
    quotations_are_grounded,
)
from source_pages import infer_pdf_page_ranges


class ExtractResponseTextTests(unittest.TestCase):
    def test_returns_primary_text(self):
        response = SimpleNamespace(text="  An answer.  ", candidates=[])
        self.assertEqual(extract_response_text(response), "An answer.")

    def test_reads_candidate_parts_when_primary_text_is_empty(self):
        response = SimpleNamespace(
            text=None,
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(text="First passage."),
                            SimpleNamespace(text="Second passage."),
                        ]
                    )
                )
            ],
        )
        self.assertEqual(
            extract_response_text(response),
            "First passage.\nSecond passage.",
        )

    def test_returns_none_when_no_text_was_generated(self):
        response = SimpleNamespace(
            text=None,
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
        )
        self.assertIsNone(extract_response_text(response))


class GroundedQuotationTests(unittest.TestCase):
    corpus = (
        "[Passage 2] (Source: Linked Discourses, Relevance: 0.9000):\n"
        "The 1.1noble truth of suﬀering is to be com-\npletely understood.\n"
    )

    def test_accepts_exact_words_after_pdf_cleanup(self):
        answer = (
            "> The noble truth of suffering is to be completely understood.\n\n"
            "**Source:** Linked Discourses; **Retrieved passage:** Passage 2."
        )
        self.assertTrue(quotations_are_grounded(answer, self.corpus))

    def test_rejects_unsupported_quote_or_wrong_source(self):
        answer = (
            "> The noble truth of suffering is to be completely ignored.\n\n"
            "**Source:** Linked Discourses; **Retrieved passage:** Passage 2."
        )
        self.assertFalse(quotations_are_grounded(answer, self.corpus))
        wrong_source = answer.replace("Linked Discourses", "Middle Discourses")
        self.assertFalse(quotations_are_grounded(wrong_source, self.corpus))

    def test_adds_only_verified_pdf_pages(self):
        answer = (
            "> The noble truth of suffering is to be completely understood.\n\n"
            "**Source:** Linked Discourses; **Retrieved passage:** Passage 2.\n"
        )
        result = add_pdf_page_citations(answer, {2: (138, 139)})
        self.assertIn("**PDF pages:** 138-139.", result)
        self.assertEqual(add_pdf_page_citations(answer, {}), answer)


class SourcePageTests(unittest.TestCase):
    def test_recovers_conservative_range_between_printed_footers(self):
        index = {
            "texts": [
                "A" * 60 + "\nSN 1.1 1\n" + "B" * 50,
                "C" * 60 + "\n2 SN 1.1\n" + "D" * 50,
                "E" * 80 + "\nSN 1.1 3\n" + "F" * 30,
            ],
            "sources": ["Linked Discourses"] * 3,
            "chunk_stride": 100,
        }
        self.assertEqual(infer_pdf_page_ranges(index)[1], (2, 3))


if __name__ == "__main__":
    unittest.main()
