"""Configuración central de Room OS."""

import logging
import os

from core.runtime_paths import application_data_dir


LOG_LEVEL = logging.INFO

# La cámara intentará usar estos valores cuando el dispositivo los soporte.
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FPS = 30
CAMERA_MIRROR = True

# Índices de cámara que se comprobarán, empezando por el primero.
CAMERA_MAX_INDEX = 9
CAMERA_WINDOW_NAME = "Room OS - Camara"
CAMERA_RETRY_SECONDS = 5.0

# Seguimiento de manos.
HAND_TRACKING_DRAW = True
HAND_TRACKING_MAX_HANDS = 2
# Un umbral moderado ayuda a conservar manos pequenas cuando estan lejos.
HAND_TRACKING_MIN_DETECTION_CONFIDENCE = 0.35
HAND_TRACKING_MIN_TRACKING_CONFIDENCE = 0.40
HAND_TRACKING_FACE_EXCLUSION_ENABLED = True
HAND_TRACKING_FACE_BOX_MARGIN = 0.18
HAND_TRACKING_FACE_MIN_LANDMARKS = 15
HAND_TRACKING_FACE_BOX_MAX_AGE_SECONDS = 1.25

# Reconocimiento y estabilización de gestos.
GESTURE_CONFIRMATION_FRAMES = 4
GESTURE_MISSING_FRAMES = 3
GESTURE_HELD_INTERVAL_SECONDS = 0.10

# Acciones disparadas una sola vez al confirmar o cambiar de gesto.
GESTURE_ACTIONS_ENABLED = True
GESTURE_ACTION_COOLDOWN_SECONDS = 1.5
GESTURE_ACTION_STARTUP_GRACE_SECONDS = 2.5
GESTURE_ACTION_MAP = {
    "PEACE": "apps.open_apple_music",
    "THUMBS_UP": "media.play",
    "THUMBS_DOWN": "media.pause",
    "OPEN_PALM": "apps.open_codex",
    "SPIDERMAN": "apps.open_browser",
}

# Mouse virtual controlado con la mano derecha. F8 lo activa/desactiva.
VIRTUAL_MOUSE_ENABLED = False
CONTROL_HAND = "Right"
MIRROR_MOUSE_X = False
MIN_HAND_CONFIDENCE = 0.55

ACTIVE_REGION_LEFT = 0.15
ACTIVE_REGION_RIGHT = 0.85
ACTIVE_REGION_TOP = 0.15
ACTIVE_REGION_BOTTOM = 0.85

MOUSE_SMOOTHING_ENABLED = True
MOUSE_SMOOTHING_FACTOR = 0.55
MOUSE_MIN_CUTOFF = 1.2
MOUSE_BETA = 0.008
MOUSE_DEAD_ZONE_PIXELS = 6
MOUSE_POSE_CONFIRM_FRAMES = 2
MOUSE_POSE_GRACE_FRAMES = 4

PINCH_CLICK_THRESHOLD = 0.30
PINCH_RELEASE_THRESHOLD = 0.40
CLICK_DEBOUNCE_SECONDS = 0.35
DRAG_HOLD_SECONDS = 0.55
HAND_WARMUP_FRAMES = 8

RIGHT_CLICK_THRESHOLD = 0.30
RIGHT_CLICK_RELEASE_THRESHOLD = 0.40
RIGHT_CLICK_DEBOUNCE_SECONDS = 0.45

SCROLL_ENABLED = True
SCROLL_ACTIVATION_HOLD_SECONDS = 1.2
SCROLL_SENSITIVITY = 1.0
SCROLL_DEAD_ZONE = 0.02
SCROLL_MAX_STEP = 5

GESTURE_SUSPEND_DELAY_SECONDS = 0.40
VIRTUAL_MOUSE_TOGGLE_KEY = "F8"
VIRTUAL_MOUSE_RELEASE_KEY = "ESC"
VIRTUAL_MOUSE_CALIBRATE_KEY = "F9"
VIRTUAL_MOUSE_MOVE_EVENT_INTERVAL_SECONDS = 0.10
VIRTUAL_MOUSE_CALIBRATION_SAMPLES = 10
VIRTUAL_MOUSE_CALIBRATION_SETTLE_FRAMES = 6
VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN = 0.25
VIRTUAL_MOUSE_CALIBRATION_TARGET_RADIUS = 0.055
VIRTUAL_MOUSE_CALIBRATION_TARGETS = (
    (0.20, 0.20),
    (0.80, 0.20),
    (0.80, 0.80),
    (0.20, 0.80),
    (0.50, 0.50),
)

# Presencia y reconocimiento facial local.
PRESENCE_DETECTION_ENABLED = True
PRESENCE_MIN_CONFIDENCE = 0.55
PRESENCE_ENTER_FRAMES = 5
PRESENCE_EXIT_TIMEOUT_SECONDS = 2.0
PRESENCE_PROCESS_EVERY_N_FRAMES = 3
PRESENCE_UPDATE_THROTTLE_SECONDS = 1.0
MULTIPLE_PERSON_THRESHOLD = 2
PRESENCE_HISTORY_LIMIT = 100

FACE_RECOGNITION_ENABLED = True
SAVE_UNKNOWN_FACES = False
SAVE_RAW_FACE_IMAGES = False
FACE_PROCESS_EVERY_N_FRAMES = 2
FACE_LOST_TIMEOUT_SECONDS = 1.5
FACE_CONFIRMATION_FRAMES = 3
FACE_MATCH_THRESHOLD = 0.50
FACE_DATABASE_PATH = application_data_dir() / "faces"
AUTHORIZED_PROFILE = os.getenv("ROOM_OS_AUTHORIZED_PROFILE", "authorized_user")
FACE_EVENT_THROTTLE_SECONDS = 1.0
FACE_MIN_SIZE_PIXELS = 60
FACE_TRACK_MAX_DISTANCE = 0.22
FACE_SIMILARITY_WINDOW = 5

FACE_REGISTRATION_CAPTURES_PER_POSE = 3
FACE_REGISTRATION_BLUR_THRESHOLD = 80.0

# Inteligencia visual mediante Gemini. La clave solo se lee desde el entorno.
GEMINI_ENABLED = True
GEMINI_MODEL = "gemini-3-flash-preview"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_TIMEOUT_SECONDS = 90
GEMINI_HEALTH_CHECK_RETRIES = 2
GEMINI_HEALTH_CHECK_RETRY_DELAY_SECONDS = 1.0

VISION_AI_ENABLED = True
VISION_AI_MAX_IMAGE_WIDTH = 1280
VISION_AI_MAX_IMAGE_HEIGHT = 720
VISION_AI_JPEG_QUALITY = 85
VISION_AI_MAX_QUEUE_SIZE = 2
VISION_AI_DEFAULT_LANGUAGE = "es"
VISION_AI_TEMPERATURE = 0.2
VISION_AI_MAX_RETRIES = 1
VISION_AI_REQUEST_COOLDOWN_SECONDS = 2.0
VISION_AI_HISTORY_LIMIT = 6
VISION_AI_DISCARD_STALE_REQUESTS = True
VISION_AI_RATE_LIMIT_REQUESTS = 5
VISION_AI_RATE_LIMIT_WINDOW_SECONDS = 60.0
VISION_AI_MAX_QUESTION_LENGTH = 1000
VISION_AI_MAX_IDENTIFIER_LENGTH = 64

# Integración de acciones Windows.
WINDOWS_ENABLED = True
ACTIONS_ENABLED = True
VOLUME_STEP = 5
SHUTDOWN_DELAY_SECONDS = 30

# Las operaciones peligrosas están bloqueadas por defecto.
ALLOW_SHUTDOWN = False
ALLOW_RESTART = False
ALLOW_SLEEP = False

PREVENT_DUPLICATE_APPS = True

# Rutas opcionales y explícitas. Se prueban antes que las ubicaciones comunes.
APP_PATHS = {
    "browser": [],
    "vscode": [],
    "terminal": [],
    "spotify": [],
    "discord": [],
    "codex": [],
    "claude": [],
    "apple_music": [],
}

# Identificadores fijos para aplicaciones de Microsoft Store sin ruta .exe pública.
APP_LAUNCH_IDS = {
    "codex": "OpenAI.Codex_2p2nqsd0c76g0!App",
    "claude": "Claude_pzs8sxrjxfjjc!Claude",
    "apple_music": "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App",
}

ALLOWED_APPS = (
    "browser",
    "vscode",
    "terminal",
    "spotify",
    "discord",
    "codex",
    "claude",
    "apple_music",
)

SYSTEM_ACTIONS_ENABLED = {
    "system.lock": True,
    "system.sleep": True,
    "system.shutdown": True,
    "system.restart": True,
    "system.cancel_power": True,
    "system.toggle_mute": True,
    "system.volume_up": True,
    "system.volume_down": True,
    "system.show_desktop": True,
    "system.open_task_manager": True,
}

MEDIA_ACTIONS_ENABLED = {
    "media.play": True,
    "media.pause": True,
    "media.play_pause": True,
    "media.next_track": True,
    "media.previous_track": True,
    "media.stop": True,
    "media.mute": True,
    "media.volume_up": True,
    "media.volume_down": True,
}

APP_ACTIONS_ENABLED = {
    "apps.open_apple_music": True,
    "apps.open_browser": True,
    "apps.open_vscode": True,
    "apps.open_terminal": True,
    "apps.open_spotify": True,
    "apps.open_discord": True,
    "apps.open_codex": True,
    "apps.open_claude": True,
    "apps.close_active_window": True,
    "apps.switch_window": True,
}

ACTION_ENABLED = {
    action_id: bool(ACTIONS_ENABLED and WINDOWS_ENABLED and enabled)
    for action_id, enabled in {
        **SYSTEM_ACTIONS_ENABLED,
        **MEDIA_ACTIONS_ENABLED,
        **APP_ACTIONS_ENABLED,
    }.items()
}
