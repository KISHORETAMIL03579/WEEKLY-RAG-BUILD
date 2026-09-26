import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.errors import LLMGenerationError, register_exception_handlers
from backend.routes import chat as chat_route
from backend.services import llm, search


class TestXAIChatRequest(unittest.TestCase):
    def test_uses_configured_key_as_bearer_authorization(self):
        response = io.BytesIO(
            json.dumps(
                {"choices": [{"message": {"content": "Grounded answer [1]."}}]}
            ).encode("utf-8")
        )
        response.status = 200
        with (
            patch.object(llm, "XAI_API_KEY", "test-xai-key"),
            patch.object(llm.urllib.request, "urlopen") as urlopen,
        ):
            urlopen.return_value.__enter__.return_value = response
            result = llm._xai_chat_call("system", "question")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-xai-key")
        self.assertEqual(result, "Grounded answer [1].")

    def test_rejects_empty_provider_choices(self):
        response = io.BytesIO(b'{"choices":[]}')
        response.status = 200
        with patch.object(llm.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            with self.assertRaisesRegex(RuntimeError, "no choices"):
                llm._xai_chat_call("system", "question")

    def test_provider_error_details_are_not_logged(self):
        secret = "provider-secret-value"
        with (
            patch.object(
                llm.urllib.request, "urlopen", side_effect=RuntimeError(secret)
            ),
            self.assertLogs("ask_my_docs", level="ERROR") as captured,
        ):
            with self.assertRaises(RuntimeError):
                llm._xai_chat_call("system", "question")

        self.assertNotIn(secret, "\n".join(captured.output))


class TestAnswerGenerationFailures(unittest.TestCase):
    def test_provider_failure_is_typed_and_does_not_log_secret(self):
        secret = "provider-secret-value"
        with (
            patch.object(search, "chat_call", side_effect=RuntimeError(secret)),
            self.assertLogs("ask_my_docs", level="ERROR") as captured,
        ):
            with self.assertRaises(LLMGenerationError) as raised:
                search.generate_answer("question", [])

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.code, "LLM_GENERATION_FAILED")
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, "\n".join(captured.output))

    def test_ask_propagates_generation_failure_without_offline_fallback(self):
        result = {
            "id": "chunk-1",
            "doc_id": "doc-1",
            "filename": "policy.pdf",
            "page": 1,
            "text": "Relevant policy text.",
            "score": 0.9,
        }
        store = SimpleNamespace(chunks=[result], vectors=[[]])
        trace_store = SimpleNamespace(log=lambda record: None)

        def fail_generation(*args, **kwargs):
            raise LLMGenerationError()

        overrides = {
            "_get_store": lambda sid: store,
            "_embeddings_configured": lambda: True,
            "_chat_configured": lambda: True,
            "reciprocal_rank_fusion": lambda *args, **kwargs: [result],
            "generate_answer": fail_generation,
            "validate_context": lambda *args, **kwargs: True,
            "synthesize_answer": lambda *args, **kwargs: self.fail(
                "Provider failure must not run the offline fallback"
            ),
            "TRACES": trace_store,
            "RERANK_ENABLED": False,
            "QUERY_REWRITE_ENABLED": False,
            "SESSION_FILES": {"test-session": {}},
        }

        def resolve_symbol(name, default=None):
            return overrides.get(name, default)

        with patch.object(chat_route, "get_app_symbol", side_effect=resolve_symbol):
            with self.assertRaises(LLMGenerationError):
                chat_route.ask("test-session", chat_route.AskPayload(query="question"))

    def test_generation_failure_uses_retryable_503_api_error(self):
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/generation-failure")
        def generation_failure():
            raise LLMGenerationError()

        response = TestClient(app).get("/generation-failure")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "LLM_GENERATION_FAILED")
        self.assertTrue(response.json()["error"]["retryable"])
        self.assertNotIn("secret", response.text.lower())


if __name__ == "__main__":
    unittest.main()
