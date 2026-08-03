"""Reconocimiento facial local, estabilizado y desacoplado de acciones."""

import logging
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Callable, Optional

import cv2
import numpy as np

from config import (
    AUTHORIZED_PROFILE,
    FACE_CONFIRMATION_FRAMES,
    FACE_DATABASE_PATH,
    FACE_EVENT_THROTTLE_SECONDS,
    FACE_LOST_TIMEOUT_SECONDS,
    FACE_MATCH_THRESHOLD,
    FACE_MIN_SIZE_PIXELS,
    FACE_PROCESS_EVERY_N_FRAMES,
    FACE_RECOGNITION_ENABLED,
    FACE_SIMILARITY_WINDOW,
    FACE_TRACK_MAX_DISTANCE,
)
from core.event_bus import EventBus
from services.face_database import FaceDatabase
from services.face_embedding import (
    cosine_similarity,
    crop_face,
    generate_face_embedding,
)


logger = logging.getLogger(__name__)

UNKNOWN = "UNKNOWN"
PENDING = "PENDING"


@dataclass
class _FaceTrack:
    track_id: int
    bounding_box: dict[str, float]
    first_seen: float
    last_seen: float
    candidate: str = PENDING
    candidate_frames: int = 0
    confirmed_identity: str = PENDING
    similarities: deque[float] = field(
        default_factory=lambda: deque(maxlen=FACE_SIMILARITY_WINDOW)
    )
    confidence: float = 0.0
    last_detected_event_at: float = float("-inf")


class FaceRecognizer:
    """Compara descriptores locales y estabiliza identidad por track facial."""

    def __init__(
        self,
        event_bus: EventBus,
        database: Optional[FaceDatabase] = None,
        embedding_function: Callable[[Any], np.ndarray] = generate_face_embedding,
        enabled: bool = FACE_RECOGNITION_ENABLED,
        draw_overlay: bool = True,
        confirmation_frames: int = FACE_CONFIRMATION_FRAMES,
        match_threshold: float = FACE_MATCH_THRESHOLD,
        lost_timeout_seconds: float = FACE_LOST_TIMEOUT_SECONDS,
        process_every_n_frames: int = FACE_PROCESS_EVERY_N_FRAMES,
        authorized_profile: str = AUTHORIZED_PROFILE,
    ) -> None:
        self._event_bus = event_bus
        self._database = database or FaceDatabase(FACE_DATABASE_PATH)
        self._embedding_function = embedding_function
        self._enabled = bool(enabled)
        self._draw_overlay_enabled = bool(draw_overlay)
        self._confirmation_frames = max(1, int(confirmation_frames))
        self._match_threshold = min(max(float(match_threshold), 0.0), 1.0)
        self._lost_timeout = max(0.1, float(lost_timeout_seconds))
        self._process_every = max(1, int(process_every_n_frames))
        self._authorized_profile = str(authorized_profile)
        self._queue: queue.Queue[
            tuple[list[tuple[dict[str, float], Any]], float, int] | None
        ] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._started = False
        self._batch_counter = 0
        self._next_track_id = 1
        self._tracks: dict[int, _FaceTrack] = {}
        self._profiles: dict[str, np.ndarray] = {}
        self._display_names: dict[str, str] = {}
        self._latest_results: list[dict[str, Any]] = []

    @property
    def has_registered_profiles(self) -> bool:
        return bool(self._database.list_profiles())

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start(self) -> None:
        if self._started:
            return
        self._event_bus.subscribe("camera.frame", self._on_camera_frame)
        if self._enabled:
            self._reload_profiles()
            self._event_bus.subscribe("presence.faces", self._on_presence_faces)
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="room-os-face-recognition",
                daemon=True,
            )
            self._thread.start()
        self._started = True
        logger.info(
            "Reconocimiento facial %s | perfiles: %d",
            "iniciado" if self._enabled else "deshabilitado",
            len(self._profiles),
        )

    def _reload_profiles(self) -> None:
        self._profiles = self._database.load_all()
        self._display_names = {}
        for profile_name in self._profiles:
            try:
                metadata = self._database.load_metadata(profile_name)
                self._display_names[profile_name] = str(
                    metadata.get("display_name", profile_name)
                )
            except Exception:
                logger.exception("No se pudo leer metadata del perfil %s", profile_name)
                self._display_names[profile_name] = profile_name

    def _on_presence_faces(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        self._batch_counter += 1
        if self._batch_counter % self._process_every:
            return
        frame = event_data.get("frame")
        if frame is None:
            return
        timestamp = float(event_data.get("timestamp", time.perf_counter()))
        frame_id = int(event_data.get("frame_id", self._batch_counter))
        height, width = frame.shape[:2]
        faces: list[tuple[dict[str, float], Any]] = []
        for raw_box in event_data.get("bounding_boxes", []):
            box = dict(raw_box)
            pixel_width = box.get("width", 0.0) * width
            pixel_height = box.get("height", 0.0) * height
            if min(pixel_width, pixel_height) < FACE_MIN_SIZE_PIXELS:
                continue
            face_image = crop_face(frame, box)
            if face_image is not None:
                faces.append((box, face_image))
        self._enqueue_latest((faces, timestamp, frame_id))

    def _enqueue_latest(
        self,
        item: tuple[list[tuple[dict[str, float], Any]], float, int],
    ) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            logger.debug("Se descartó un lote facial atrasado")

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                faces, timestamp, frame_id = item
                observations = []
                for box, face_image in faces:
                    embedding = None
                    if self._profiles:
                        try:
                            embedding = self._embedding_function(face_image)
                        except Exception:
                            logger.exception("No se pudo generar un descriptor facial")
                    observations.append(
                        {"bounding_box": box, "embedding": embedding}
                    )
                self._process_observations(observations, timestamp, frame_id)
            except Exception as error:
                logger.exception("Error en reconocimiento facial")
                self._event_bus.publish(
                    "face.error",
                    {"timestamp": time.perf_counter(), "error": str(error)},
                )
            finally:
                self._queue.task_done()

    def _process_observations(
        self,
        observations: list[dict[str, Any]],
        timestamp: float,
        frame_id: int,
    ) -> None:
        pending_events: list[tuple[str, dict[str, Any]]] = []
        with self._lock:
            pending_events.extend(
                self._expire_tracks(timestamp, frame_id, set())
            )
            assignments = self._assign_tracks(observations, timestamp)
            visible_track_ids: set[int] = set()
            latest_results: list[dict[str, Any]] = []

            for track, observation in assignments:
                visible_track_ids.add(track.track_id)
                track.bounding_box = dict(observation["bounding_box"])
                track.last_seen = timestamp
                identity, similarity = self._match_embedding(observation.get("embedding"))
                identity_events = self._advance_identity(
                    track,
                    identity,
                    similarity,
                    timestamp,
                    frame_id,
                )
                pending_events.extend(identity_events)
                identity_changed_now = any(
                    event_name == "face.identity_changed"
                    for event_name, _ in identity_events
                )
                if (
                    timestamp - track.last_detected_event_at
                    >= FACE_EVENT_THROTTLE_SECONDS
                ):
                    track.last_detected_event_at = timestamp
                    pending_events.append(
                        (
                            "face.detected",
                            self._payload(track, timestamp, frame_id),
                        )
                    )
                    if track.confirmed_identity == UNKNOWN and not identity_changed_now:
                        pending_events.append(
                            (
                                "face.unknown",
                                self._payload(track, timestamp, frame_id),
                            )
                        )
                    elif (
                        track.confirmed_identity != PENDING
                        and not identity_changed_now
                    ):
                        pending_events.append(
                            (
                                "face.recognized",
                                self._payload(track, timestamp, frame_id),
                            )
                        )
                visible_result = self._payload(track, timestamp, frame_id)
                visible_result["visible"] = True
                latest_results.append(visible_result)

            pending_events.extend(
                self._expire_tracks(timestamp, frame_id, visible_track_ids)
            )
            for track_id, track in self._tracks.items():
                if track_id in visible_track_ids:
                    continue
                retained_result = self._payload(track, timestamp, frame_id)
                retained_result["visible"] = False
                latest_results.append(retained_result)
            self._latest_results = latest_results

        for event_name, payload in pending_events:
            self._event_bus.publish(event_name, payload)

    def _assign_tracks(
        self,
        observations: list[dict[str, Any]],
        timestamp: float,
    ) -> list[tuple[_FaceTrack, dict[str, Any]]]:
        available_tracks = set(self._tracks)
        assignments: list[tuple[_FaceTrack, dict[str, Any]]] = []
        for observation in observations:
            box = observation["bounding_box"]
            center = self._box_center(box)
            nearest_id = None
            nearest_distance = float("inf")
            for track_id in available_tracks:
                distance = math.dist(
                    center,
                    self._box_center(self._tracks[track_id].bounding_box),
                )
                if distance < nearest_distance:
                    nearest_id = track_id
                    nearest_distance = distance
            if nearest_id is not None and nearest_distance <= FACE_TRACK_MAX_DISTANCE:
                track = self._tracks[nearest_id]
                available_tracks.remove(nearest_id)
            else:
                track = _FaceTrack(
                    track_id=self._next_track_id,
                    bounding_box=dict(box),
                    first_seen=timestamp,
                    last_seen=timestamp,
                )
                self._tracks[track.track_id] = track
                self._next_track_id += 1
            assignments.append((track, observation))
        return assignments

    def _match_embedding(self, embedding: Any) -> tuple[str, float]:
        if embedding is None or not self._profiles:
            return UNKNOWN, 0.0
        best_profile = UNKNOWN
        best_similarity = 0.0
        for profile, registered_embeddings in self._profiles.items():
            similarities = sorted(
                (
                    max(
                        0.0,
                        min(
                            1.0,
                            (cosine_similarity(embedding, registered) - 0.5) / 0.5,
                        ),
                    )
                    for registered in registered_embeddings
                ),
                reverse=True,
            )
            strongest = similarities[: min(3, len(similarities))]
            profile_similarity = float(median(strongest))
            if profile_similarity > best_similarity:
                best_profile = profile
                best_similarity = profile_similarity
        if best_similarity < self._match_threshold:
            return UNKNOWN, best_similarity
        return best_profile, best_similarity

    def _advance_identity(
        self,
        track: _FaceTrack,
        identity: str,
        similarity: float,
        timestamp: float,
        frame_id: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        if identity == track.candidate:
            track.candidate_frames += 1
        else:
            track.candidate = identity
            track.candidate_frames = 1
            track.similarities.clear()
        track.similarities.append(float(similarity))
        stable_similarity = float(median(track.similarities))
        track.confidence = (
            max(0.5, stable_similarity)
            if identity != UNKNOWN
            else max(0.0, min(0.49, 0.49 * (1.0 - stable_similarity)))
        )
        if track.candidate_frames < self._confirmation_frames:
            return []
        if track.confirmed_identity == identity:
            return []

        previous = track.confirmed_identity
        track.confirmed_identity = identity
        payload = self._payload(track, timestamp, frame_id)
        payload["previous_identity"] = previous
        events: list[tuple[str, dict[str, Any]]] = [
            ("face.identity_changed", payload)
        ]
        events.append(
            (
                "face.unknown" if identity == UNKNOWN else "face.recognized",
                payload,
            )
        )
        if previous == self._authorized_profile and identity != self._authorized_profile:
            events.append(("face.authorized_exited", payload))
        if identity == self._authorized_profile and previous != self._authorized_profile:
            events.append(("face.authorized_entered", payload))
        return events

    def _expire_tracks(
        self,
        timestamp: float,
        frame_id: int,
        visible_track_ids: set[int],
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        for track_id, track in tuple(self._tracks.items()):
            if track_id in visible_track_ids:
                continue
            if timestamp - track.last_seen < self._lost_timeout:
                continue
            payload = self._payload(track, timestamp, frame_id)
            events.append(("face.lost", payload))
            if track.confirmed_identity == self._authorized_profile:
                events.append(("face.authorized_exited", payload))
            del self._tracks[track_id]
        return events

    def _payload(
        self,
        track: _FaceTrack,
        timestamp: float,
        frame_id: int,
    ) -> dict[str, Any]:
        identity = track.confirmed_identity
        return {
            "timestamp": float(timestamp),
            "identity": identity,
            "display_name": self._display_names.get(identity, identity),
            "is_authorized": identity == self._authorized_profile,
            "confidence": track.confidence,
            "similarity": (
                float(median(track.similarities)) if track.similarities else 0.0
            ),
            "bounding_box": dict(track.bounding_box),
            "track_id": track.track_id,
            "duration_seconds": max(0.0, timestamp - track.first_seen),
            "frame_id": int(frame_id),
        }

    @staticmethod
    def _box_center(box: dict[str, float]) -> tuple[float, float]:
        return (
            float(box["x"]) + float(box["width"]) / 2.0,
            float(box["y"]) + float(box["height"]) / 2.0,
        )

    def _on_camera_frame(self, event_data: Any) -> None:
        if not self._draw_overlay_enabled:
            return
        if not isinstance(event_data, dict):
            return
        frame = event_data.get("frame")
        if frame is None:
            return
        with self._lock:
            results = tuple(dict(result) for result in self._latest_results)
        if not self._enabled:
            cv2.putText(
                frame,
                "Face recognition: OFF",
                (20, 198),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                (120, 120, 255),
                2,
                cv2.LINE_AA,
            )
            return

        height, width = frame.shape[:2]
        authorized_visible = False
        unknown_count = 0
        identity_names = []
        for result in results:
            box = result["bounding_box"]
            left = int(box["x"] * width)
            top = int(box["y"] * height)
            right = int((box["x"] + box["width"]) * width)
            bottom = int((box["y"] + box["height"]) * height)
            identity = str(result["identity"])
            display_name = str(result.get("display_name", identity))
            authorized_visible |= bool(result["is_authorized"])
            unknown_count += int(identity == UNKNOWN)
            identity_names.append(display_name)
            color = (60, 220, 60) if result["is_authorized"] else (40, 80, 255)
            if result.get("visible", True):
                cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                cv2.putText(
                    frame,
                    f"{display_name} {result['confidence']:.2f} #{result['track_id']}",
                    (left, max(top - 8, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                    cv2.LINE_AA,
                )
        recognition_state = (
            "AUTHORIZED_USER"
            if authorized_visible
            else (f"UNKNOWN x{unknown_count}" if unknown_count else "WAITING")
        )
        identities = ", ".join(identity_names) if identity_names else "none"
        cv2.putText(
            frame,
            f"Face: {recognition_state} | Identity: {identities}",
            (20, 198),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (80, 230, 120) if authorized_visible else (100, 170, 255),
            2,
            cv2.LINE_AA,
        )

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_overlay_enabled = bool(enabled)

    def close(self) -> None:
        if self._started:
            self._event_bus.unsubscribe("camera.frame", self._on_camera_frame)
            if self._enabled:
                self._event_bus.unsubscribe("presence.faces", self._on_presence_faces)
        self._stop_event.set()
        if self._thread is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(None)
                except queue.Full:
                    pass
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("El worker facial no terminó a tiempo")
            self._thread = None
        with self._lock:
            self._tracks.clear()
            self._latest_results = []
        self._started = False
        logger.info("Reconocimiento facial cerrado")
