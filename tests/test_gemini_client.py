"""Pruebas del adaptador de Gemini sin llamadas reales a Google."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from google.genai import errors

from services.gemini_client import (
    GeminiAuthenticationError,
    GeminiClient,
    GeminiRequestTimeoutError,
)


class GeminiClientTests(unittest.TestCase):
    def make_client(self, native_client: Mock) -> GeminiClient:
        return GeminiClient(
            model="gemini-3.5-flash",
            timeout_seconds=3,
            client=native_client,
        )

    def test_missing_api_key_is_unavailable_without_crashing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = GeminiClient(api_key_env="GEMINI_API_KEY")
        health = client.health_check()
        self.assertFalse(health["available"])
        self.assertFalse(health["configured"])
        self.assertIn("GEMINI_API_KEY", health["error"])

    def test_gemini_available_and_model_accessible(self) -> None:
        native = Mock()
        native.models.get.return_value = SimpleNamespace(
            name="models/gemini-3.5-flash"
        )
        health = self.make_client(native).health_check()
        self.assertTrue(health["available"])
        self.assertTrue(health["model_available"])
        native.models.get.assert_called_once_with(model="gemini-3.5-flash")

    def test_invalid_api_key_is_reported_without_echoing_key(self) -> None:
        native = Mock()
        native.models.get.side_effect = errors.ClientError(
            403,
            {"error": {"message": "forbidden"}},
        )
        health = self.make_client(native).health_check()
        self.assertFalse(health["available"])
        self.assertIn("GEMINI_API_KEY", health["error"])

    def test_send_text(self) -> None:
        native = Mock()
        native.models.generate_content.return_value = SimpleNamespace(
            text="respuesta",
            model_version="gemini-3.5-flash",
            usage_metadata=SimpleNamespace(
                prompt_token_count=10,
                candidates_token_count=5,
            ),
            candidates=[],
        )
        result = self.make_client(native).send_text(
            "hola",
            system_prompt="sistema",
        )
        self.assertEqual("respuesta", result["text"])
        call = native.models.generate_content.call_args.kwargs
        self.assertEqual("gemini-3.5-flash", call["model"])
        self.assertEqual(["hola"], call["contents"])

    def test_send_image_uses_inline_jpeg_bytes(self) -> None:
        native = Mock()
        native.models.generate_content.return_value = SimpleNamespace(
            text="imagen recibida",
            model_version="gemini-3.5-flash",
            usage_metadata=None,
            candidates=[],
        )
        image_bytes = b"\xff\xd8jpeg\xff\xd9"
        self.make_client(native).send_image(image_bytes, "describe")
        contents = native.models.generate_content.call_args.kwargs["contents"]
        self.assertEqual(image_bytes, contents[0].inline_data.data)
        self.assertEqual("image/jpeg", contents[0].inline_data.mime_type)
        self.assertEqual("describe", contents[-1])

    def test_json_schema_is_sent_to_gemini(self) -> None:
        native = Mock()
        native.models.generate_content.return_value = SimpleNamespace(
            text='{"ok": true}',
            model_version="gemini-3.5-flash",
            usage_metadata=None,
            candidates=[],
        )
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        self.make_client(native).send_text("json", response_format=schema)
        config = native.models.generate_content.call_args.kwargs["config"]
        self.assertEqual("application/json", config.response_mime_type)
        self.assertEqual(schema, config.response_json_schema)

    def test_timeout_is_translated(self) -> None:
        native = Mock()
        native.models.generate_content.side_effect = httpx.ReadTimeout("slow")
        with self.assertRaises(GeminiRequestTimeoutError):
            self.make_client(native).send_text("hola")

    def test_missing_key_prevents_requests(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = GeminiClient(api_key_env="GEMINI_API_KEY")
        with self.assertRaises(GeminiAuthenticationError):
            client.send_text("hola")

    def test_invalid_environment_key_is_rejected_without_echoing_it(self) -> None:
        invalid_key = "secret with spaces"
        with patch.dict(os.environ, {"GEMINI_API_KEY": invalid_key}, clear=True):
            with self.assertLogs("services.gemini_client", level="ERROR") as captured:
                client = GeminiClient(api_key_env="GEMINI_API_KEY")
        health = client.health_check()
        self.assertFalse(health["configured"])
        self.assertNotIn(invalid_key, "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
