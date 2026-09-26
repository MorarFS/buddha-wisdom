import unittest
from types import SimpleNamespace

from response_utils import extract_response_text


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


if __name__ == "__main__":
    unittest.main()
