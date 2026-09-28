import unittest

from passage_search import join_overlapping_chunks, matching_passages


class PassageSearchTests(unittest.TestCase):
    def test_joins_neighboring_chunks_without_repeating_overlap(self):
        self.assertEqual(
            join_overlapping_chunks("A" * 70 + "B" * 60, "B" * 60 + "C" * 70),
            "A" * 70 + "B" * 60 + "C" * 70,
        )

    def test_uses_all_scored_page_backed_hits_and_merges_neighbors(self):
        index = {
            "texts": [
                "Translator's preface",  # The most similar text is not a sutta.
                "SN 1.1\n" + "A" * 70 + "B" * 60,
                "B" * 60 + "C" * 70,
                "SN 2.1\n" + "D" * 70,
                "Unrelated text",
            ],
            "sources": ["Preface", "Linked Discourses", "Linked Discourses",
                        "Linked Discourses", "Linked Discourses"],
            "pdf_page_ranges": [None, (10, 10), (11, 11), (20, 20), (30, 30)],
        }
        results = matching_passages(index, [0.95, 0.80, 0.78, 0.74, 0.60])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["pdf_pages"], [10, 11])
        self.assertEqual(results[0]["sutta_reference"], "SN 1.1")
        self.assertEqual(results[0]["text"], "SN 1.1\n" + "A" * 70 + "B" * 60 + "C" * 70)
        self.assertEqual(results[1]["sutta_reference"], "SN 2.1")


if __name__ == "__main__":
    unittest.main()
