"""Ejecutor manual limitado exclusivamente a acciones Windows seguras."""

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import ACTION_ENABLED, WINDOWS_ENABLED  # noqa: E402
from core.action_engine import ActionEngine  # noqa: E402
from core.action_registry import ActionRegistry  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.logger import configure_logging  # noqa: E402


SAFE_ACTION_IDS = (
    "media.play_pause",
    "media.next_track",
    "media.previous_track",
    "system.volume_up",
    "system.volume_down",
    "system.toggle_mute",
    "system.show_desktop",
    "apps.open_browser",
    "apps.open_vscode",
    "apps.switch_window",
    "apps.close_active_window",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prueba manual de acciones seguras de Room OS.",
    )
    parser.add_argument("action_id", nargs="?", choices=SAFE_ACTION_IDS)
    parser.add_argument("--list", action="store_true", dest="list_actions")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    if args.list_actions or args.action_id is None:
        for action_id in SAFE_ACTION_IDS:
            print(action_id)
        return 0

    if os.name != "nt" or not WINDOWS_ENABLED:
        print("Las acciones Windows no están habilitadas en este sistema.")
        return 1

    event_bus = EventBus()
    registry = ActionRegistry(enabled_config=ACTION_ENABLED)
    engine = ActionEngine(event_bus, registry)
    result = engine.execute(
        args.action_id,
        {"source": "safe_manual_test"},
    )
    print(result.to_dict())
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
