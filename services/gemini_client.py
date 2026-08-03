"""Cliente aislado para la API multimodal de Gemini."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

import httpx
from google import genai
from google.genai import errors, types

from config import (
    GEMINI_API_KEY_ENV,
    GEMINI_MODEL,
    GEMINI_TIMEOUT_SECONDS,
)


logger = logging.getLogger(__name__)


class GeminiClientError(RuntimeError):
    """Error base del proveedor Gemini."""


class GeminiUnavailableError(GeminiClientError):
    """La API no esta configurada o no responde."""


class GeminiAuthenticationError(GeminiClientError):
    """La clave de Gemini falta o fue rechazada."""


class GeminiRequestTimeoutError(GeminiClientError):
    """La solicitud excedio el timeout configurado."""


class GeminiRequestCancelledError(GeminiClientError):
    """La respuesta de una solicitud cancelada debe descartarse."""


class GeminiModelError(GeminiClientError):
    """Gemini rechazo la solicitud o no pudo generar una respuesta."""


class GeminiClient:
    """Encapsula el SDK oficial sin exponer claves ni objetos del proveedor."""

    def __init__(
        self,
        model: str = GEMINI_MODEL,
        timeout_seconds: float = GEMINI_TIMEOUT_SECONDS,
        api_key_env: str = GEMINI_API_KEY_ENV,
        client: Optional[Any] = None,
    ) -> None:
        self.model = str(model)
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.api_key_env = str(api_key_env)
        resolved_key = str(os.getenv(self.api_key_env, "")).strip()
        if resolved_key and (
            len(resolved_key) > 512
            or any(character.isspace() or not character.isprintable() for character in resolved_key)
        ):
            logger.error("La variable %s tiene un formato invalido", self.api_key_env)
            resolved_key = ""
        self._configured = bool(client is not None or resolved_key)
        self._client = client
        if self._client is None and resolved_key:
            self._client = genai.Client(
                api_key=resolved_key,
                http_options=types.HttpOptions(
                    timeout=int(self.timeout_seconds * 1000),
                ),
            )
        self._cancelled: set[str] = set()
        self._lock = threading.RLock()

    @property
    def setup_hint(self) -> str:
        return (
            f"Configura la variable {self.api_key_env} y reinicia Room OS. "
            "La clave se crea en https://aistudio.google.com/apikey"
        )

    def health_check(self) -> dict[str, Any]:
        """Comprueba credenciales y acceso al modelo sin enviar una imagen."""
        if not self._configured or self._client is None:
            return self._health_failure(
                f"Falta la variable de entorno {self.api_key_env}",
                configured=False,
            )
        try:
            model_info = self._client.models.get(model=self.model)
            resolved_name = getattr(model_info, "name", None) or self.model
            return {
                "success": True,
                "available": True,
                "model_installed": True,
                "model_available": True,
                "configured": True,
                "model": self.model,
                "resolved_model": str(resolved_name),
                "provider": "gemini",
                "error": None,
            }
        except (httpx.TimeoutException, TimeoutError) as error:
            return self._health_failure(f"Timeout conectando con Gemini: {error}")
        except errors.ClientError as error:
            return self._health_failure(self._client_error_message(error))
        except (errors.ServerError, httpx.NetworkError) as error:
            return self._health_failure(f"Gemini no esta disponible: {error}")
        except Exception as error:
            return self._health_failure(f"No se pudo comprobar Gemini: {error}")

    def send_text(
        self,
        instruction: str,
        *,
        system_prompt: str = "",
        messages: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[str | dict[str, Any]] = None,
        temperature: float = 0.2,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        contents: list[Any] = [self._conversation_text(messages), str(instruction)]
        return self._generate(
            [item for item in contents if item],
            system_prompt=system_prompt,
            response_format=response_format,
            temperature=temperature,
            request_id=request_id,
        )

    def send_image(
        self,
        image_bytes: bytes,
        instruction: str,
        *,
        system_prompt: str = "",
        messages: Optional[list[dict[str, Any]]] = None,
        response_format: Optional[str | dict[str, Any]] = None,
        temperature: float = 0.2,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise ValueError("La imagen debe contener bytes JPEG")
        conversation = self._conversation_text(messages)
        contents: list[Any] = [
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        ]
        if conversation:
            contents.append(conversation)
        contents.append(str(instruction))
        return self._generate(
            contents,
            system_prompt=system_prompt,
            response_format=response_format,
            temperature=temperature,
            request_id=request_id,
        )

    def cancel_request(self, request_id: str) -> None:
        if request_id:
            with self._lock:
                self._cancelled.add(str(request_id))

    def clear_cancelled_request(self, request_id: str) -> None:
        with self._lock:
            self._cancelled.discard(str(request_id))

    def _generate(
        self,
        contents: list[Any],
        *,
        system_prompt: str,
        response_format: Optional[str | dict[str, Any]],
        temperature: float,
        request_id: Optional[str],
    ) -> dict[str, Any]:
        if not self._configured or self._client is None:
            raise GeminiAuthenticationError(self.setup_hint)
        self._raise_if_cancelled(request_id)
        config: dict[str, Any] = {
            "system_instruction": str(system_prompt),
            "temperature": min(max(float(temperature), 0.0), 2.0),
        }
        if response_format:
            config["response_mime_type"] = "application/json"
            if isinstance(response_format, dict):
                config["response_json_schema"] = response_format
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except (httpx.TimeoutException, TimeoutError) as error:
            raise GeminiRequestTimeoutError(
                f"Gemini excedio {self.timeout_seconds:.0f} segundos"
            ) from error
        except errors.ClientError as error:
            status = int(getattr(error, "code", 0) or 0)
            message = self._client_error_message(error)
            if status in {401, 403}:
                raise GeminiAuthenticationError(message) from error
            raise GeminiModelError(message) from error
        except (errors.ServerError, httpx.NetworkError) as error:
            raise GeminiUnavailableError(f"Gemini no esta disponible: {error}") from error
        self._raise_if_cancelled(request_id)
        return self._normalize_response(
            response,
            observed_duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _normalize_response(
        self,
        response: Any,
        *,
        observed_duration_ms: float,
    ) -> dict[str, Any]:
        try:
            text = str(response.text or "").strip()
        except Exception as error:
            raise GeminiModelError(
                "Gemini no devolvio contenido textual utilizable"
            ) from error
        if not text:
            raise GeminiModelError("Gemini devolvio una respuesta vacia")
        usage = getattr(response, "usage_metadata", None)
        return {
            "success": True,
            "text": text,
            "model": str(getattr(response, "model_version", None) or self.model),
            "created_at": "",
            "done_reason": self._finish_reason(response),
            "total_duration_ms": float(observed_duration_ms),
            "load_duration_ms": 0.0,
            "prompt_eval_count": int(
                getattr(usage, "prompt_token_count", 0) or 0
            ),
            "eval_count": int(
                getattr(usage, "candidates_token_count", 0) or 0
            ),
        }

    @staticmethod
    def _finish_reason(response: Any) -> Optional[str]:
        candidates = getattr(response, "candidates", None) or ()
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        return str(reason) if reason is not None else None

    @staticmethod
    def _conversation_text(messages: Optional[list[dict[str, Any]]]) -> str:
        lines = []
        for message in messages or ():
            role = str(message.get("role", "user"))
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                lines.append(f"{role}: {content}")
        return "Contexto conversacional:\n" + "\n".join(lines) if lines else ""

    def _raise_if_cancelled(self, request_id: Optional[str]) -> None:
        if not request_id:
            return
        with self._lock:
            cancelled = str(request_id) in self._cancelled
        if cancelled:
            raise GeminiRequestCancelledError(
                f"La solicitud '{request_id}' fue cancelada"
            )

    def _health_failure(
        self,
        error: str,
        *,
        configured: bool = True,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "available": False,
            "model_installed": False,
            "model_available": False,
            "configured": configured,
            "model": self.model,
            "resolved_model": None,
            "provider": "gemini",
            "error": str(error),
        }

    def _client_error_message(self, error: Exception) -> str:
        status = int(getattr(error, "code", 0) or 0)
        if status in {401, 403}:
            return f"Gemini rechazo {self.api_key_env}; verifica la clave y permisos"
        if status == 404:
            return f"El modelo '{self.model}' no esta disponible para esta clave"
        if status == 429:
            return "Gemini alcanzo el limite de cuota o solicitudes"
        return f"Gemini rechazo la solicitud: {error}"

    def close(self) -> None:
        if self._client is not None:
            close_method = getattr(self._client, "close", None)
            if callable(close_method):
                close_method()
