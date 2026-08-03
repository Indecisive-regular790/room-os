"""Pruebas del worker y los eventos de inteligencia visual."""

import json
import threading
import time
import unittest

import numpy as np

from core.event_bus import EventBus
from modules.visual_intelligence import VisualAIState, VisualIntelligence


class FakeVisionService:
    model = "gemini-3.5-flash"
    setup_hint = "Configura GEMINI_API_KEY"

    def __init__(self, *, available=True, installed=True, block=False, error=None):
        self.available = available
        self.installed = installed
        self.block = block
        self.error = error
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancelled = []
        self.closed = False

    def health_check(self):
        return {
            "available": self.available,
            "model_available": self.installed,
            "error": None if self.available else "connection refused",
        }

    def _respond(self, image, analysis_type):
        self.entered.set()
        if self.block:
            self.release.wait(timeout=3.0)
        if self.error:
            raise self.error
        height, width = image.shape[:2]
        return {
            "success": True,
            "analysis_type": analysis_type,
            "model": self.model,
            "structured": False,
            "data": None,
            "text": "resultado",
            "image_dimensions": {
                "original": {"width": width, "height": height},
                "sent": {"width": width, "height": height},
            },
            "inference": {"total_duration_ms": 1.0},
        }

    def describe_scene(self, image, **kwargs):
        return self._respond(image, "describe_scene")

    def answer_question(self, image, question, **kwargs):
        return self._respond(image, "answer_question")

    def inspect_workspace(self, image, **kwargs):
        return self._respond(image, "inspect_workspace")

    def read_text(self, image, **kwargs):
        return self._respond(image, "read_text")

    def analyze_screen(self, image, question=None, **kwargs):
        return self._respond(image, "screen_analysis")

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)

    def clear_cancelled_request(self, request_id):
        pass

    def close(self):
        self.closed = True
        self.release.set()


class VisualIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)

    @staticmethod
    def wait_for(predicate, timeout=2.0):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def start_module(self, service, **kwargs):
        module = VisualIntelligence(
            self.bus,
            service,
            cooldown_seconds=0.0,
            health_check_retries=0,
            **kwargs,
        )
        module.start()
        self.assertTrue(self.wait_for(lambda: module.state == VisualAIState.READY))
        self.bus.publish("camera.frame", {"frame": self.frame, "timestamp": 1.0})
        return module

    def test_started_and_completed_events(self) -> None:
        service = FakeVisionService()
        module = self.start_module(service)
        started, completed = [], []
        self.bus.subscribe("vision_ai.started", started.append)
        self.bus.subscribe("vision_ai.completed", completed.append)
        self.bus.publish("vision_ai.describe_scene", {"request_id": "one"})
        self.assertTrue(self.wait_for(lambda: len(completed) == 1))
        self.assertEqual("one", started[0]["request_id"])
        self.assertTrue(completed[0]["success"])
        self.assertEqual("describe_scene", completed[0]["analysis_type"])
        self.assertIsNotNone(completed[0]["image_dimensions"])
        module.close()

    def test_camera_is_not_blocked_during_inference(self) -> None:
        service = FakeVisionService(block=True)
        module = self.start_module(service)
        self.bus.publish("vision_ai.describe_scene", {"request_id": "slow"})
        self.assertTrue(service.entered.wait(timeout=1.0))
        started = time.perf_counter()
        self.bus.publish("camera.frame", {"frame": self.frame, "timestamp": 2.0})
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.1)
        service.release.set()
        module.close()

    def test_limited_queue_discards_old_pending_request(self) -> None:
        service = FakeVisionService(block=True)
        module = self.start_module(service, max_queue_size=1)
        cancelled = []
        self.bus.subscribe("vision_ai.cancelled", cancelled.append)
        self.bus.publish("vision_ai.describe_scene", {"request_id": "active"})
        self.assertTrue(service.entered.wait(timeout=1.0))
        self.bus.publish("vision_ai.describe_scene", {"request_id": "old"})
        self.bus.publish("vision_ai.describe_scene", {"request_id": "new"})
        self.assertTrue(self.wait_for(lambda: any(x["request_id"] == "old" for x in cancelled)))
        service.release.set()
        module.close()

    def test_active_request_can_be_cancelled(self) -> None:
        service = FakeVisionService(block=True)
        module = self.start_module(service)
        cancelled, completed = [], []
        self.bus.subscribe("vision_ai.cancelled", cancelled.append)
        self.bus.subscribe("vision_ai.completed", completed.append)
        self.bus.publish("vision_ai.describe_scene", {"request_id": "cancel-me"})
        self.assertTrue(service.entered.wait(timeout=1.0))
        self.bus.publish("vision_ai.cancel", {"request_id": "cancel-me"})
        self.assertTrue(self.wait_for(lambda: len(cancelled) == 1))
        service.release.set()
        time.sleep(0.05)
        self.assertEqual([], completed)
        self.assertIn("cancel-me", service.cancelled)
        module.close()

    def test_model_error_emits_failed_and_worker_survives(self) -> None:
        service = FakeVisionService(error=RuntimeError("model failure"))
        module = self.start_module(service)
        failed = []
        self.bus.subscribe("vision_ai.failed", failed.append)
        self.bus.publish("vision_ai.describe_scene", {"request_id": "bad"})
        self.assertTrue(self.wait_for(lambda: len(failed) == 1))
        self.assertIn("model failure", failed[0]["error"])
        self.assertTrue(module._worker.is_alive())
        module.close()

    def test_explicit_screen_image_is_supported(self) -> None:
        service = FakeVisionService()
        module = self.start_module(service)
        completed = []
        self.bus.subscribe("vision_ai.completed", completed.append)
        screen = np.zeros((300, 500, 3), dtype=np.uint8)
        self.bus.publish(
            "vision_ai.analyze_screen",
            {"request_id": "screen", "image": screen, "question": "Que ventana es?"},
        )
        self.assertTrue(self.wait_for(lambda: len(completed) == 1))
        dimensions = completed[0]["image_dimensions"]["original"]
        self.assertEqual({"width": 500, "height": 300}, dimensions)
        module.close()

    def test_unavailable_gemini_does_not_break_other_subscribers(self) -> None:
        service = FakeVisionService(available=False)
        module = VisualIntelligence(
            self.bus,
            service,
            cooldown_seconds=0.0,
            health_check_retries=0,
        )
        unrelated = []
        unavailable = []
        self.bus.subscribe("room_os.unrelated", unrelated.append)
        self.bus.subscribe("vision_ai.unavailable", unavailable.append)
        module.start()
        self.assertTrue(self.wait_for(lambda: len(unavailable) >= 1))
        self.bus.publish("room_os.unrelated", {"ok": True})
        self.assertEqual([{"ok": True}], unrelated)
        module.close()

    def test_logs_and_events_redact_long_base64_like_errors(self) -> None:
        secret = "A" * 400
        service = FakeVisionService(error=RuntimeError(secret))
        module = self.start_module(service)
        failed = []
        self.bus.subscribe("vision_ai.failed", failed.append)
        with self.assertLogs("modules.visual_intelligence", level="ERROR") as captured:
            self.bus.publish("vision_ai.describe_scene", {"request_id": "secret"})
            self.assertTrue(self.wait_for(lambda: len(failed) == 1))
        logs = "\n".join(captured.output)
        self.assertNotIn(secret, logs)
        self.assertNotIn(secret, json.dumps(failed))
        module.close()

    def test_rate_limit_emits_retry_without_calling_service_again(self) -> None:
        service = FakeVisionService()
        module = self.start_module(
            service,
            rate_limit_requests=1,
            rate_limit_window_seconds=60.0,
        )
        completed, limited = [], []
        self.bus.subscribe("vision_ai.completed", completed.append)
        self.bus.subscribe("vision_ai.rate_limited", limited.append)
        self.bus.publish(
            "vision_ai.describe_scene",
            {"request_id": "first", "session_id": "local"},
        )
        self.assertTrue(self.wait_for(lambda: len(completed) == 1))
        self.bus.publish(
            "vision_ai.describe_scene",
            {"request_id": "second", "session_id": "local"},
        )
        self.assertTrue(self.wait_for(lambda: len(limited) == 1))
        self.assertEqual("second", limited[0]["request_id"])
        self.assertGreater(limited[0]["retry_after_seconds"], 0)
        module.close()

    def test_invalid_question_is_rejected_before_service_call(self) -> None:
        service = FakeVisionService()
        module = self.start_module(service)
        failed = []
        self.bus.subscribe("vision_ai.failed", failed.append)
        self.bus.publish(
            "vision_ai.answer_question",
            {"request_id": "invalid", "question": "hola\x00mundo"},
        )
        self.assertTrue(self.wait_for(lambda: len(failed) == 1))
        self.assertFalse(service.entered.is_set())
        module.close()


if __name__ == "__main__":
    unittest.main()
