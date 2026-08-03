"""Pruebas unitarias del registro y motor de acciones."""

import unittest
from typing import Any, Optional

from config import ACTION_ENABLED
from core.action_engine import ActionEngine
from core.action_registry import (
    ActionNotFoundError,
    ActionRegistry,
    DuplicateActionIdError,
)
from core.actions.base_action import BaseAction
from core.event_bus import EventBus


class SuccessfulAction(BaseAction):
    def __init__(self, action_id: str = "test.success") -> None:
        super().__init__(action_id, "Successful test", "Returns a test result")

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"received": dict(context or {})}


class FailingAction(BaseAction):
    def __init__(self) -> None:
        super().__init__("test.failure", "Failing test", "Raises an exception")

    def execute(self, context: Optional[dict[str, Any]] = None) -> None:
        raise RuntimeError("simulated failure")


class ActionRegistryTests(unittest.TestCase):
    def test_register_search_list_and_duplicate_protection(self) -> None:
        registry = ActionRegistry(auto_discover=False)
        action = SuccessfulAction()
        registry.register(action)

        self.assertIs(action, registry.get_by_id("test.success"))
        self.assertIs(action, registry.get_by_name("successful TEST"))
        self.assertEqual([action], registry.list_actions())

        with self.assertRaises(DuplicateActionIdError):
            registry.register(SuccessfulAction())

    def test_enable_and_disable(self) -> None:
        registry = ActionRegistry(auto_discover=False)
        registry.register(SuccessfulAction())

        registry.disable("test.success")
        self.assertFalse(registry.get("test.success").enabled)
        registry.enable("Successful test")
        self.assertTrue(registry.get("test.success").enabled)

    def test_builtin_actions_are_discovered_automatically(self) -> None:
        registry = ActionRegistry()
        self.assertEqual(
            set(ACTION_ENABLED),
            {action.id for action in registry.list_actions()},
        )


class ActionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self.registry = ActionRegistry(auto_discover=False)
        self.engine = ActionEngine(self.bus, self.registry)

    def test_successful_execution(self) -> None:
        self.registry.register(SuccessfulAction())
        result = self.engine.execute("test.success", {"value": 42})

        self.assertTrue(result.success)
        self.assertEqual("success", result.status)
        self.assertEqual({"received": {"value": 42}}, result.result)
        self.assertIsNone(result.error_type)
        self.assertIsNone(result.error_message)
        self.assertIn("dangerous", result.metadata)
        self.assertEqual((result,), self.engine.get_history())

    def test_missing_action(self) -> None:
        result = self.engine.execute("test.missing")

        self.assertFalse(result.success)
        self.assertEqual("not_found", result.status)
        with self.assertRaises(ActionNotFoundError):
            self.registry.get_by_id("test.missing")

    def test_disabled_action(self) -> None:
        action = SuccessfulAction()
        action.enabled = False
        self.registry.register(action)

        result = self.engine.execute(action.id)
        self.assertFalse(result.success)
        self.assertEqual("disabled", result.status)

    def test_action_exception_is_captured(self) -> None:
        self.registry.register(FailingAction())

        result = self.engine.execute("test.failure")
        self.assertFalse(result.success)
        self.assertEqual("error", result.status)
        self.assertIn("simulated failure", result.error or "")
        self.assertEqual("RuntimeError", result.error_type)

    def test_event_bus_execution_and_result_event(self) -> None:
        self.registry.register(SuccessfulAction())
        published_results = []
        self.bus.subscribe("action.result", published_results.append)
        self.engine.start()

        self.bus.publish(
            "action.execute",
            {"action_id": "test.success", "context": {"source": "event"}},
        )

        self.assertEqual(1, len(published_results))
        self.assertTrue(published_results[0]["success"])
        self.engine.close()


if __name__ == "__main__":
    unittest.main()
