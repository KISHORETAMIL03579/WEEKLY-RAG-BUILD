# tests/test_error_handling.py — Production Error Handling & API Contract Test Suite
import json
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.errors import (
    AppError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    DependencyError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    build_error_payload,
    register_exception_handlers,
    sanitize_error_message,
)
from backend.main import create_app
from backend.middleware import RequestCorrelationMiddleware


class TestErrorSanitization(unittest.TestCase):
    """Verifies that secrets, paths, and raw traceback headers are completely redacted."""

    def test_redact_gemini_and_openai_keys(self):
        msg = "Failed with key AIzaSyD9u1234567890abcdef1234567890abc and sk-12345678901234567890abcdef"
        sanitized = sanitize_error_message(msg)
        self.assertNotIn("AIzaSyD9u1234567890abcdef1234567890abc", sanitized)
        self.assertNotIn("sk-12345678901234567890abcdef", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_redact_windows_paths(self):
        msg = "File not found: C:\\Users\\Administrator\\AppData\\Local\\secret.json in pipeline"
        sanitized = sanitize_error_message(msg)
        self.assertNotIn("C:\\Users\\Administrator", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_redact_unix_paths(self):
        msg = "Could not open /Users/sanjith/code/project/config.env"
        sanitized = sanitize_error_message(msg)
        self.assertNotIn("/Users/sanjith", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_redact_basic_auth_urls(self):
        msg = "Connection failed to https://admin:supersecret123@qdrant.cloud.io:6333/collections"
        sanitized = sanitize_error_message(msg)
        self.assertNotIn("supersecret123", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_strip_raw_python_exception_prefixes(self):
        msg = "ValueError: Invalid chunk size 0"
        sanitized = sanitize_error_message(msg)
        self.assertEqual(sanitized, "Invalid chunk size 0")


class TestErrorPayloadContract(unittest.TestCase):
    """Verifies the JSON payload schema matches the standard error contract."""

    def test_payload_schema(self):
        payload = build_error_payload(
            code="RESOURCE_NOT_FOUND",
            message="Item 123 does not exist",
            request_id="req_test_abc123",
            retryable=False,
            details={"item_id": "123"},
        )
        self.assertFalse(payload["success"])
        self.assertIn("error", payload)
        err = payload["error"]
        self.assertEqual(err["code"], "RESOURCE_NOT_FOUND")
        self.assertEqual(err["message"], "Item 123 does not exist")
        self.assertEqual(err["request_id"], "req_test_abc123")
        self.assertFalse(err["retryable"])
        self.assertEqual(err["details"], {"item_id": "123"})


class TestFastApiErrorHandlers(unittest.TestCase):
    """Verifies FastAPI exception handlers with live TestClient."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = TestClient(cls.app)

    def test_404_not_found_error_schema(self):
        res = self.client.get("/api/evaluation/runs/non_existent_run_id_99999")
        self.assertEqual(res.status_code, 404)
        self.assertTrue(res.headers.get("X-Request-ID"))
        data = res.json()
        self.assertFalse(data["success"])
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], "NOT_FOUND")
        self.assertIn("not found", data["error"]["message"].lower())
        self.assertFalse(data["error"]["retryable"])
        self.assertEqual(data["error"]["request_id"], res.headers["X-Request-ID"])

    def test_404_policy_benchmark_run_schema(self):
        res = self.client.get("/api/policy/benchmark/runs/bench_non_existent_id")
        self.assertEqual(res.status_code, 404)
        self.assertTrue(res.headers.get("X-Request-ID"))
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "NOT_FOUND")

    def test_422_validation_error_schema(self):
        res = self.client.post("/api/policy/agent", json={"invalid_field": 123})
        self.assertEqual(res.status_code, 422)
        self.assertTrue(res.headers.get("X-Request-ID"))
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("details", data["error"])
        self.assertFalse(data["error"]["retryable"])

    def test_400_bad_request_error_schema(self):
        res = self.client.post("/eval/parse-qa-pdf", data={})
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.headers.get("X-Request-ID"))
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_request_id_correlation_preserved_from_client(self):
        custom_id = "req_custom_correlation_id_456"
        res = self.client.get(
            "/api/evaluation/runs/non_existent_id",
            headers={"X-Request-ID": custom_id},
        )
        self.assertEqual(res.headers.get("X-Request-ID"), custom_id)
        data = res.json()
        self.assertEqual(data["error"]["request_id"], custom_id)

    def test_app_error_subclasses_via_test_router(self):
        """Creates a dedicated test FastAPI app to verify all AppError subclasses."""
        test_app = FastAPI()
        test_app.add_middleware(RequestCorrelationMiddleware)
        register_exception_handlers(test_app)

        @test_app.get("/test/bad-request")
        def route_bad_request():
            raise BadRequestError("Bad parameter provided", details={"field": "query"})

        @test_app.get("/test/auth-error")
        def route_auth():
            raise AuthenticationError("Invalid session token")

        @test_app.get("/test/conflict")
        def route_conflict():
            raise ConflictError("Resource already exists")

        @test_app.get("/test/rate-limit")
        def route_rate_limit():
            raise RateLimitError("Max query budget reached")

        @test_app.get("/test/dependency")
        def route_dependency():
            raise DependencyError("Upstream vector store unreachable")

        @test_app.get("/test/unhandled")
        def route_unhandled():
            raise RuntimeError("Database connection string postgres://user:secret@db.lan/test crashed")

        client = TestClient(test_app, raise_server_exceptions=False)

        # 400
        r = client.get("/test/bad-request")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "BAD_REQUEST")
        self.assertEqual(r.json()["error"]["details"], {"field": "query"})

        # 401
        r = client.get("/test/auth-error")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "UNAUTHORIZED")

        # 409
        r = client.get("/test/conflict")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "CONFLICT")

        # 429
        r = client.get("/test/rate-limit")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"]["code"], "RATE_LIMIT_EXCEEDED")
        self.assertTrue(r.json()["error"]["retryable"])

        # 503
        r = client.get("/test/dependency")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"]["code"], "SERVICE_UNAVAILABLE")
        self.assertTrue(r.json()["error"]["retryable"])

        # 500 Unhandled Exception (Sanitized)
        r = client.get("/test/unhandled")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertNotIn("secret", r.json()["error"]["message"])
        self.assertNotIn("postgres", r.json()["error"]["message"])
        self.assertTrue(r.json()["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
