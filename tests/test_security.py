"""Pruebas de los limites de seguridad locales."""

import unittest

from core.input_validation import (
    InputValidationError,
    escape_rich_text,
    normalize_text,
    validate_identifier,
)
from core.rate_limiter import SlidingWindowRateLimiter


class InputValidationTests(unittest.TestCase):
    def test_normalizes_unicode_and_preserves_natural_language(self) -> None:
        text = normalize_text(
            "  SELECT * FROM notas WHERE autor = 'Test User'  ",
            field_name="pregunta",
            max_length=100,
        )
        self.assertEqual("SELECT * FROM notas WHERE autor = 'Test User'", text)

    def test_rejects_oversized_and_control_character_input(self) -> None:
        with self.assertRaises(InputValidationError):
            normalize_text("abcd", field_name="pregunta", max_length=3)
        with self.assertRaises(InputValidationError):
            normalize_text("hola\x00mundo", field_name="pregunta", max_length=30)

    def test_identifier_rejects_log_injection(self) -> None:
        with self.assertRaises(InputValidationError):
            validate_identifier("session\nERROR", field_name="session_id")

    def test_rich_text_is_escaped(self) -> None:
        escaped = escape_rich_text('<img src=x onerror="alert(1)">')
        self.assertNotIn("<img", escaped)
        self.assertIn("&lt;img", escaped)
        self.assertIn("&quot;", escaped)


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def test_blocks_after_limit_and_recovers_after_window(self) -> None:
        now = [100.0]
        limiter = SlidingWindowRateLimiter(2, 10.0, clock=lambda: now[0])
        self.assertTrue(limiter.consume("local").allowed)
        self.assertTrue(limiter.consume("local").allowed)
        blocked = limiter.consume("local")
        self.assertFalse(blocked.allowed)
        self.assertAlmostEqual(10.0, blocked.retry_after_seconds)
        now[0] = 110.01
        self.assertTrue(limiter.consume("local").allowed)

    def test_sessions_are_independent(self) -> None:
        limiter = SlidingWindowRateLimiter(1, 60.0, clock=lambda: 1.0)
        self.assertTrue(limiter.consume("one").allowed)
        self.assertFalse(limiter.consume("one").allowed)
        self.assertTrue(limiter.consume("two").allowed)


if __name__ == "__main__":
    unittest.main()
