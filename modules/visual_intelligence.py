"""Modulo no bloqueante de inteligencia visual conectado al EventBus."""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import cv2
import numpy as np

from config import (
    GEMINI_ENABLED,
    GEMINI_HEALTH_CHECK_RETRIES,
    GEMINI_HEALTH_CHECK_RETRY_DELAY_SECONDS,
    VISION_AI_DISCARD_STALE_REQUESTS,
    VISION_AI_ENABLED,
    VISION_AI_MAX_IDENTIFIER_LENGTH,
    VISION_AI_MAX_QUEUE_SIZE,
    VISION_AI_MAX_QUESTION_LENGTH,
    VISION_AI_RATE_LIMIT_REQUESTS,
    VISION_AI_RATE_LIMIT_WINDOW_SECONDS,
    VISION_AI_REQUEST_COOLDOWN_SECONDS,
)
from core.event_bus import EventBus
from core.input_validation import (
    InputValidationError,
    normalize_text,
    validate_identifier,
)
from core.rate_limiter import SlidingWindowRateLimiter
from services.gemini_client import GeminiRequestCancelledError
from services.vision_ai_service import VisionAIService


logger = logging.getLogger(__name__)

REQUEST_EVENTS = {
    "vision_ai.describe_scene": "describe_scene",
    "vision_ai.answer_question": "answer_question",
    "vision_ai.inspect_workspace": "inspect_workspace",
    "vision_ai.read_text": "read_text",
    "vision_ai.analyze_screen": "screen_analysis",
}


class VisualAIState(str, Enum):
    READY = "READY"
    ANALYZING = "ANALYZING"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class _AnalysisRequest:
    request_id: str
    analysis_type: str
    question: str
    session_id: str
    image: np.ndarray
    color_space: str
    requested_at: str


class VisualIntelligence:
    """Conserva el ultimo frame y ejecuta una sola inferencia a la vez."""

    def __init__(
        self,
        event_bus: EventBus,
        service: VisionAIService,
        *,
        enabled: bool = VISION_AI_ENABLED and GEMINI_ENABLED,
        max_queue_size: int = VISION_AI_MAX_QUEUE_SIZE,
        cooldown_seconds: float = VISION_AI_REQUEST_COOLDOWN_SECONDS,
        discard_stale_requests: bool = VISION_AI_DISCARD_STALE_REQUESTS,
        health_check_retries: int = GEMINI_HEALTH_CHECK_RETRIES,
        health_retry_delay_seconds: float = GEMINI_HEALTH_CHECK_RETRY_DELAY_SECONDS,
        rate_limit_requests: int = VISION_AI_RATE_LIMIT_REQUESTS,
        rate_limit_window_seconds: float = VISION_AI_RATE_LIMIT_WINDOW_SECONDS,
        draw_overlay: bool = True,
    ) -> None:
        self._event_bus = event_bus
        self._service = service
        self._enabled = bool(enabled)
        self._queue: queue.Queue[Optional[_AnalysisRequest]] = queue.Queue(
            maxsize=max(1, int(max_queue_size))
        )
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._discard_stale = bool(discard_stale_requests)
        self._health_retries = max(0, int(health_check_retries))
        self._health_retry_delay = max(0.0, float(health_retry_delay_seconds))
        self._draw_overlay_enabled = bool(draw_overlay)
        self._rate_limiter = SlidingWindowRateLimiter(
            rate_limit_requests,
            rate_limit_window_seconds,
        )

        self._state = VisualAIState.UNAVAILABLE
        self._state_lock = threading.RLock()
        self._frame_lock = threading.RLock()
        self._latest_frame: Optional[np.ndarray] = None
        self._last_request_at = float("-inf")
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._active_request_id: Optional[str] = None
        self._cancelled: set[str] = set()
        self._cancelled_emitted: set[str] = set()
        self._started = False

    @property
    def state(self) -> VisualAIState:
        with self._state_lock:
            return self._state

    def start(self) -> None:
        if self._started:
            return
        self._event_bus.subscribe("camera.frame", self._on_camera_frame)
        for event_name, analysis_type in REQUEST_EVENTS.items():
            self._event_bus.subscribe(
                event_name,
                self._request_callback(analysis_type),
            )
        self._event_bus.subscribe("vision_ai.cancel", self._on_cancel)
        self._stop_event.clear()
        if self._enabled:
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="room-os-visual-ai",
                daemon=True,
            )
            self._worker.start()
            self._start_health_check()
        logger.info(
            "Inteligencia visual %s | modelo=%s",
            "iniciada" if self._enabled else "deshabilitada",
            self._service.model,
        )
        self._started = True

    def _request_callback(self, analysis_type: str):
        def callback(event_data: Any) -> None:
            self._submit(analysis_type, event_data)

        callback.__name__ = f"_on_{analysis_type}"
        setattr(self, f"_callback_{analysis_type}", callback)
        return callback

    def _on_camera_frame(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        frame = event_data.get("frame")
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            return
        with self._frame_lock:
            self._latest_frame = frame.copy()
        if self._draw_overlay_enabled:
            self._draw_status(frame)

    def _submit(self, analysis_type: str, event_data: Any) -> None:
        data = event_data if isinstance(event_data, dict) else {}
        fallback_request_id = uuid.uuid4().hex
        try:
            request_id = validate_identifier(
                data.get("request_id") or fallback_request_id,
                field_name="request_id",
                max_length=VISION_AI_MAX_IDENTIFIER_LENGTH,
            )
            session_id = validate_identifier(
                data.get("session_id") or "default",
                field_name="session_id",
                max_length=VISION_AI_MAX_IDENTIFIER_LENGTH,
            )
            question = normalize_text(
                data.get("question") or "",
                field_name="La pregunta",
                max_length=VISION_AI_MAX_QUESTION_LENGTH,
                allow_empty=analysis_type != "answer_question",
            )
        except InputValidationError as error:
            self._publish_terminal(
                "vision_ai.failed",
                fallback_request_id,
                analysis_type,
                "",
                error=str(error),
            )
            return

        if not self._enabled:
            self._publish_terminal(
                "vision_ai.unavailable",
                request_id,
                analysis_type,
                question,
                error="La inteligencia visual esta deshabilitada",
            )
            return
        if self.state not in {VisualAIState.READY, VisualAIState.ANALYZING}:
            self._publish_terminal(
                "vision_ai.unavailable",
                request_id,
                analysis_type,
                question,
                error=(
                    f"Gemini o el modelo {self._service.model} no estan disponibles. "
                    f"{self._service.setup_hint}"
                ),
            )
            self._start_health_check()
            return
        now = time.perf_counter()
        if now - self._last_request_at < self._cooldown:
            self._publish_terminal(
                "vision_ai.failed",
                request_id,
                analysis_type,
                question,
                error=f"Espera {self._cooldown:.1f} segundos entre solicitudes",
            )
            return

        rate_limit = self._rate_limiter.consume(session_id)
        if not rate_limit.allowed:
            retry_after = max(1.0, rate_limit.retry_after_seconds)
            self._publish_terminal(
                "vision_ai.rate_limited",
                request_id,
                analysis_type,
                question,
                error=f"Limite de solicitudes alcanzado; intenta en {retry_after:.0f} segundos",
                extra={"retry_after_seconds": retry_after},
            )
            logger.warning(
                "Solicitud de Vision AI limitada: session_id=%s retry_after=%.1fs",
                session_id,
                retry_after,
            )
            return

        image = data.get("image")
        color_space = str(data.get("color_space") or "BGR")
        if image is None:
            with self._frame_lock:
                image = None if self._latest_frame is None else self._latest_frame.copy()
        elif isinstance(image, np.ndarray):
            image = image.copy()
        if not isinstance(image, np.ndarray) or image.size == 0:
            self._publish_terminal(
                "vision_ai.failed",
                request_id,
                analysis_type,
                question,
                error="No hay una imagen disponible para analizar",
            )
            return

        request = _AnalysisRequest(
            request_id=request_id,
            analysis_type=analysis_type,
            question=question,
            session_id=session_id,
            image=image,
            color_space=color_space,
            requested_at=self._utc_now(),
        )
        if not self._enqueue(request):
            return
        self._last_request_at = now

    def _enqueue(self, request: _AnalysisRequest) -> bool:
        try:
            self._queue.put_nowait(request)
            return True
        except queue.Full:
            if not self._discard_stale:
                self._publish_terminal(
                    "vision_ai.failed",
                    request.request_id,
                    request.analysis_type,
                    request.question,
                    error="La cola de inteligencia visual esta llena",
                )
                return False
        try:
            stale = self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            stale = None
        if stale is not None:
            self._publish_cancelled(stale, "Solicitud obsoleta descartada")
        try:
            self._queue.put_nowait(request)
            return True
        except queue.Full:
            self._publish_terminal(
                "vision_ai.failed",
                request.request_id,
                request.analysis_type,
                request.question,
                error="No se pudo encolar la solicitud",
            )
            return False

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                request = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if request is None:
                    return
                if self._is_cancelled(request.request_id):
                    self._publish_cancelled(request, "Solicitud cancelada antes de iniciar")
                    continue
                self._execute_request(request)
            finally:
                self._queue.task_done()

    def _execute_request(self, request: _AnalysisRequest) -> None:
        started_clock = time.perf_counter()
        started_at = self._utc_now()
        self._active_request_id = request.request_id
        self._set_state(VisualAIState.ANALYZING)
        self._event_bus.publish(
            "vision_ai.started",
            self._payload(
                request,
                started_at=started_at,
                finished_at=None,
                duration_ms=0.0,
                success=False,
                result=None,
                error=None,
                image_dimensions=self._original_dimensions(request.image),
            ),
        )
        try:
            result = self._call_service(request)
            if self._is_cancelled(request.request_id):
                self._publish_cancelled(request, "Respuesta descartada tras cancelacion")
                return
            finished_at = self._utc_now()
            duration_ms = (time.perf_counter() - started_clock) * 1000.0
            payload = self._payload(
                request,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                success=True,
                result=result,
                error=None,
                image_dimensions=result.get("image_dimensions"),
            )
            self._event_bus.publish("vision_ai.completed", payload)
            logger.info(
                "Vision AI completada: %s",
                json.dumps(
                    {
                        "request_id": request.request_id,
                        "analysis_type": request.analysis_type,
                        "duration_ms": round(duration_ms, 1),
                        "model": self._service.model,
                        "structured": result.get("structured"),
                        "result": result.get("data") or result.get("text"),
                    },
                    ensure_ascii=False,
                ),
            )
            self._set_state(VisualAIState.READY)
        except GeminiRequestCancelledError:
            self._publish_cancelled(request, "Solicitud cancelada")
            self._set_state(VisualAIState.READY)
        except Exception as error:
            safe_error = self._safe_error(error)
            self._set_state(VisualAIState.ERROR)
            self._event_bus.publish(
                "vision_ai.failed",
                self._payload(
                    request,
                    started_at=started_at,
                    finished_at=self._utc_now(),
                    duration_ms=(time.perf_counter() - started_clock) * 1000.0,
                    success=False,
                    result=None,
                    error=safe_error,
                    image_dimensions=self._original_dimensions(request.image),
                ),
            )
            logger.error(
                "Vision AI fallo: request_id=%s type=%s error=%s",
                request.request_id,
                request.analysis_type,
                safe_error,
            )
        finally:
            self._service.clear_cancelled_request(request.request_id)
            self._cancelled.discard(request.request_id)
            self._cancelled_emitted.discard(request.request_id)
            self._active_request_id = None

    def _call_service(self, request: _AnalysisRequest) -> dict[str, Any]:
        common = {
            "session_id": request.session_id,
            "request_id": request.request_id,
        }
        if request.analysis_type == "describe_scene":
            return self._service.describe_scene(request.image, **common)
        if request.analysis_type == "answer_question":
            return self._service.answer_question(
                request.image,
                request.question,
                **common,
            )
        if request.analysis_type == "inspect_workspace":
            return self._service.inspect_workspace(request.image, **common)
        if request.analysis_type == "read_text":
            return self._service.read_text(request.image, **common)
        if request.analysis_type == "screen_analysis":
            return self._service.analyze_screen(
                request.image,
                request.question or None,
                color_space=request.color_space,
                **common,
            )
        raise ValueError(f"Tipo de analisis no soportado: {request.analysis_type}")

    def _on_cancel(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        request_id = str(event_data.get("request_id") or "")
        if not request_id:
            return
        self._cancelled.add(request_id)
        self._service.cancel_request(request_id)
        if request_id not in self._cancelled_emitted:
            self._cancelled_emitted.add(request_id)
            self._publish_terminal(
                "vision_ai.cancelled",
                request_id,
                str(event_data.get("analysis_type") or "unknown"),
                str(event_data.get("question") or ""),
                error="Solicitud cancelada por el usuario",
            )

    def _publish_cancelled(self, request: _AnalysisRequest, reason: str) -> None:
        if request.request_id in self._cancelled_emitted:
            return
        self._cancelled_emitted.add(request.request_id)
        self._event_bus.publish(
            "vision_ai.cancelled",
            self._payload(
                request,
                started_at=request.requested_at,
                finished_at=self._utc_now(),
                duration_ms=0.0,
                success=False,
                result=None,
                error=reason,
                image_dimensions=self._original_dimensions(request.image),
            ),
        )

    def _publish_terminal(
        self,
        event_name: str,
        request_id: str,
        analysis_type: str,
        question: str,
        *,
        error: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        now = self._utc_now()
        payload = {
                "request_id": request_id,
                "analysis_type": analysis_type,
                "question": question or None,
                "started_at": now,
                "finished_at": now,
                "duration_ms": 0.0,
                "model": self._service.model,
                "success": False,
                "result": None,
                "error": self._safe_error(error),
                "image_dimensions": None,
            }
        if extra:
            payload.update(extra)
        self._event_bus.publish(event_name, payload)

    def _payload(
        self,
        request: _AnalysisRequest,
        *,
        started_at: Optional[str],
        finished_at: Optional[str],
        duration_ms: float,
        success: bool,
        result: Any,
        error: Optional[str],
        image_dimensions: Any,
    ) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "analysis_type": request.analysis_type,
            "question": request.question or None,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": float(duration_ms),
            "model": self._service.model,
            "success": bool(success),
            "result": result,
            "error": error,
            "image_dimensions": image_dimensions,
        }

    def _start_health_check(self) -> None:
        if not self._enabled:
            return
        if self._health_thread is not None and self._health_thread.is_alive():
            return
        self._health_thread = threading.Thread(
            target=self._health_loop,
            name="room-os-gemini-health",
            daemon=True,
        )
        self._health_thread.start()

    def _health_loop(self) -> None:
        health: dict[str, Any] = {}
        for attempt in range(self._health_retries + 1):
            if self._stop_event.is_set():
                return
            health = self._service.health_check()
            if health.get("available"):
                break
            if attempt < self._health_retries:
                self._stop_event.wait(self._health_retry_delay)
        if health.get("available") and health.get("model_available", health.get("model_installed")):
            self._set_state(VisualAIState.READY)
            self._event_bus.publish(
                "vision_ai.ready",
                {"model": self._service.model, "timestamp": self._utc_now()},
            )
            logger.info("Gemini listo con el modelo %s", self._service.model)
            return
        self._set_state(VisualAIState.UNAVAILABLE)
        error = health.get("error")
        if health.get("available") and not health.get(
            "model_available", health.get("model_installed")
        ):
            error = f"El modelo no esta disponible. {self._service.setup_hint}"
        logger.warning("AI no disponible: %s", error or "estado desconocido")
        self._publish_terminal(
            "vision_ai.unavailable",
            "startup",
            "health_check",
            "",
            error=str(error or "Gemini no disponible"),
        )

    def _draw_status(self, frame: np.ndarray) -> None:
        state = self.state
        color = {
            VisualAIState.READY: (70, 220, 100),
            VisualAIState.ANALYZING: (0, 220, 255),
            VisualAIState.UNAVAILABLE: (80, 120, 255),
            VisualAIState.ERROR: (40, 40, 255),
        }[state]
        cv2.putText(
            frame,
            f"AI: {state.value}",
            (20, 230),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
            cv2.LINE_AA,
        )

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_overlay_enabled = bool(enabled)

    def _set_state(self, state: VisualAIState) -> None:
        with self._state_lock:
            self._state = state

    def _is_cancelled(self, request_id: str) -> bool:
        return request_id in self._cancelled

    @staticmethod
    def _original_dimensions(image: np.ndarray) -> dict[str, Any]:
        height, width = image.shape[:2]
        return {
            "original": {"width": int(width), "height": int(height)},
            "sent": None,
        }

    @staticmethod
    def _safe_error(error: Any) -> str:
        text = str(error).replace("\r", " ").replace("\n", " ")
        text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[imagen omitida]", text)
        text = re.sub(r"\b(?:AQ\.|AIza)[A-Za-z0-9._-]{20,}", "[credencial omitida]", text)
        text = re.sub(r"[A-Za-z0-9+/=]{256,}", "[datos omitidos]", text)
        return " ".join(text.split())[:500]

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def close(self) -> None:
        if self._started:
            self._event_bus.unsubscribe("camera.frame", self._on_camera_frame)
            for event_name, analysis_type in REQUEST_EVENTS.items():
                callback = getattr(self, f"_callback_{analysis_type}", None)
                if callback is not None:
                    self._event_bus.unsubscribe(event_name, callback)
            self._event_bus.unsubscribe("vision_ai.cancel", self._on_cancel)
        self._stop_event.set()
        if self._active_request_id:
            self._cancelled.add(self._active_request_id)
            self._service.cancel_request(self._active_request_id)
        try:
            self._service.close()
        except Exception:
                logger.exception("No se pudo cerrar el cliente de Gemini")
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                stale = self._queue.get_nowait()
                self._queue.task_done()
                if stale is not None:
                    self._publish_cancelled(stale, "Room OS se esta cerrando")
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        if self._worker is not None:
            self._worker.join(timeout=5.0)
            if self._worker.is_alive():
                logger.warning("El worker de inteligencia visual no termino a tiempo")
            self._worker = None
        if self._health_thread is not None:
            self._health_thread.join(timeout=2.0)
            self._health_thread = None
        with self._frame_lock:
            self._latest_frame = None
        self._started = False
        logger.info("Inteligencia visual cerrada")
