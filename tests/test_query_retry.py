import importlib
import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace

google = types.ModuleType("google")
google.genai = types.ModuleType("google.genai")
numpy = types.ModuleType("numpy")
with patch.dict(sys.modules, {"google": google, "google.genai": google.genai, "numpy": numpy}):
    query_module = importlib.import_module("query_sutta_corpus")


class QueryRetryTests(unittest.TestCase):
    def test_retries_an_empty_answer(self):
        responses = [
            SimpleNamespace(text=None, candidates=[]),
            SimpleNamespace(text="A grounded answer.", candidates=[]),
        ]
        generate = unittest.mock.Mock(side_effect=responses)
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))

        with (
            patch.object(query_module.genai, "Client", return_value=client, create=True) as client_factory,
            patch.object(query_module, "retrieve_top_k_chunks", return_value="A passage") as retrieve,
            patch.object(query_module.time, "sleep"),
        ):
            answer = query_module.buddha_wisdom("What is dukkha?")

        self.assertEqual(answer, "A grounded answer.")
        self.assertEqual(generate.call_count, 2)
        retrieve.assert_called_once_with(client, "What is dukkha?", k=8)
        config = generate.call_args.kwargs["config"]
        self.assertNotIn("thinking_config", config)
        self.assertEqual(config["max_output_tokens"], 2048)
        self.assertEqual(generate.call_args.kwargs["model"], "gemini-3.1-flash-lite")
        client_factory.assert_any_call(
            vertexai=True,
            project=query_module.PROJECT_ID,
            location="global",
        )

    def test_raises_after_repeated_empty_answers(self):
        generate = unittest.mock.Mock(
            return_value=SimpleNamespace(text=None, candidates=[])
        )
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))

        with (
            patch.object(query_module.genai, "Client", return_value=client, create=True),
            patch.object(query_module, "retrieve_top_k_chunks", return_value="A passage"),
            patch.object(query_module.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "no answer"):
                query_module.buddha_wisdom("What is dukkha?")

        self.assertEqual(generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
