import json
import uuid
from typing import Any, Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QTextEdit, QVBoxLayout, QWidget,
)

from ui.components import PageHeader
from ui.pages.camera_page import frame_to_pixmap
from config import VISION_AI_MAX_QUESTION_LENGTH
from core.input_validation import InputValidationError, escape_rich_text, normalize_text


class AIPage(QWidget):
    def __init__(self, event_bus: Any, latest_frame) -> None:
        super().__init__()
        self._event_bus = event_bus
        self._latest_frame = latest_frame
        self._request_id: Optional[str] = None
        self._session_id = uuid.uuid4().hex
        self._details: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(16)
        layout.addWidget(PageHeader("IA visual", "Pregunta a Gemini sobre lo que ve la cámara."))

        top = QHBoxLayout()
        self.state = QLabel("Comprobando disponibilidad…")
        self.state.setObjectName("muted")
        self.thumbnail = QLabel("Sin captura")
        self.thumbnail.setObjectName("video")
        self.thumbnail.setFixedSize(160, 90)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.state)
        top.addStretch()
        top.addWidget(self.thumbnail)
        layout.addLayout(top)

        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        self.chat.setPlaceholderText("La conversación aparecerá aquí.")
        layout.addWidget(self.chat, 1)

        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("¿Qué ves en esta imagen?")
        self.prompt.setFixedHeight(76)
        layout.addWidget(self.prompt)

        buttons = QHBoxLayout()
        self.analyze = QPushButton("Analizar")
        self.analyze.setObjectName("primary")
        self.stop = QPushButton("Detener")
        self.stop.setObjectName("danger")
        self.stop.setEnabled(False)
        self.clear = QPushButton("Limpiar")
        self.details = QPushButton("Detalles")
        self.details.setEnabled(False)
        buttons.addWidget(self.analyze)
        buttons.addWidget(self.stop)
        buttons.addWidget(self.clear)
        buttons.addStretch()
        buttons.addWidget(self.details)
        layout.addLayout(buttons)

        self.analyze.clicked.connect(self.submit)
        self.stop.clicked.connect(self.cancel)
        self.clear.clicked.connect(self.clear_history)
        self.details.clicked.connect(self.show_details)

    def submit(self) -> None:
        try:
            question = normalize_text(
                self.prompt.toPlainText(),
                field_name="La pregunta",
                max_length=VISION_AI_MAX_QUESTION_LENGTH,
            )
        except InputValidationError as error:
            self.state.setText(str(error))
            return
        frame = self._latest_frame()
        if not isinstance(frame, np.ndarray) or not frame.size:
            self.state.setText("Todavía no hay un frame disponible.")
            return
        self._request_id = uuid.uuid4().hex
        self._append_message("Tú", question, "#172B4D")
        self.prompt.clear()
        preview = frame_to_pixmap(frame).scaled(
            self.thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumbnail.setPixmap(preview)
        self.analyze.setEnabled(False)
        self.stop.setEnabled(True)
        self.state.setText("Analizando la captura…")
        self._event_bus.publish("vision_ai.answer_question", {
            "request_id": self._request_id,
            "session_id": self._session_id,
            "question": question,
            "image": frame,
            "color_space": "BGR",
        })

    def cancel(self) -> None:
        if self._request_id:
            self._event_bus.publish("vision_ai.cancel", {"request_id": self._request_id})
            self.state.setText("Cancelando…")

    def clear_history(self) -> None:
        self.cancel()
        self.chat.clear()
        self.prompt.clear()
        self.thumbnail.clear()
        self.thumbnail.setText("Sin captura")
        self._details.clear()
        self.details.setEnabled(False)

    def handle_event(self, name: str, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        if name == "vision_ai.ready":
            self.state.setText(f"Gemini listo · {data.get('model', '')}")
            return
        if name == "vision_ai.unavailable" and data.get("request_id") == "startup":
            self.state.setText("Gemini no disponible")
            return
        if data.get("request_id") != self._request_id:
            return
        if name == "vision_ai.started":
            self.state.setText("Gemini está analizando…")
            return
        if name == "vision_ai.completed":
            result = data.get("result") or {}
            answer = result.get("text") or result.get("data") or "Sin respuesta de texto."
            if not isinstance(answer, str):
                answer = json.dumps(answer, ensure_ascii=False, indent=2)
            self._append_message("Gemini", answer, "#416FA6")
            self.state.setText(f"Listo · {data.get('duration_ms', 0) / 1000:.1f} s")
            self._finish(data)
        elif name == "vision_ai.rate_limited":
            retry = max(1, int(float(data.get("retry_after_seconds") or 1)))
            self._append_message(
                "Room OS",
                f"Demasiadas solicitudes. Intenta de nuevo en {retry} segundos.",
                "#A64545",
            )
            self.state.setText("Limite temporal alcanzado")
            self._finish(data)
        elif name in {"vision_ai.failed", "vision_ai.unavailable"}:
            error = str(data.get("error") or "No se pudo completar el análisis.")
            self._append_message("Room OS", self._friendly_error(error), "#A64545")
            self.state.setText("No se pudo analizar")
            self._finish(data)
        elif name == "vision_ai.cancelled":
            self.state.setText("Análisis cancelado")
            self._finish(data)

    def _finish(self, details: dict[str, Any]) -> None:
        self._details = details
        self.details.setEnabled(True)
        self.analyze.setEnabled(True)
        self.stop.setEnabled(False)
        self._request_id = None

    @staticmethod
    def _friendly_error(error: str) -> str:
        lowered = error.lower()
        if "503" in lowered or "high demand" in lowered:
            return "Gemini está ocupado temporalmente. Intenta de nuevo en unos segundos."
        if "api_key" in lowered or "clave" in lowered:
            return "Gemini no está configurado. Revisa la clave de acceso en el entorno."
        if "timeout" in lowered or "tiempo" in lowered:
            return "El análisis tardó demasiado. Puedes intentarlo de nuevo."
        return "No se pudo completar el análisis. Consulta Detalles para ver el diagnóstico."

    def _append_message(self, sender: str, text: str, color: str) -> None:
        safe_sender = escape_rich_text(sender)
        safe = escape_rich_text(text)
        safe_color = color if color in {"#172B4D", "#416FA6", "#A64545"} else "#172B4D"
        self.chat.append(
            f'<p style="margin:8px 2px"><b style="color:{safe_color}">{safe_sender}</b><br>{safe}</p>'
        )

    def show_details(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Detalles técnicos")
        dialog.resize(560, 420)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setPlainText(json.dumps(self._details, ensure_ascii=False, indent=2, default=str))
        layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()
