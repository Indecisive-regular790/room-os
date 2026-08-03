"""Registro y descubrimiento automático de acciones."""

import importlib
import inspect
import logging
import pkgutil
import threading
from collections.abc import Mapping
from typing import Optional

from core.actions.base_action import BaseAction


logger = logging.getLogger(__name__)


class ActionRegistryError(RuntimeError):
    """Error base del registro de acciones."""


class DuplicateActionIdError(ActionRegistryError):
    """Indica que dos acciones intentaron usar el mismo ID."""


class ActionNotFoundError(ActionRegistryError):
    """Indica que no existe una acción con el ID o nombre solicitado."""


class ActionRegistry:
    """Descubre, registra y administra acciones de forma thread-safe."""

    def __init__(
        self,
        auto_discover: bool = True,
        enabled_config: Optional[Mapping[str, bool]] = None,
    ) -> None:
        self._actions: dict[str, BaseAction] = {}
        self._enabled_config = dict(enabled_config or {})
        self._lock = threading.RLock()

        if auto_discover:
            self.discover_actions()

    def register(self, action: BaseAction) -> None:
        """Registra una acción y rechaza IDs duplicados."""
        if not isinstance(action, BaseAction):
            raise TypeError("Solo se pueden registrar instancias de BaseAction")

        with self._lock:
            if action.id in self._actions:
                raise DuplicateActionIdError(
                    f"Ya existe una acción con el ID '{action.id}'"
                )
            if action.id in self._enabled_config:
                action.enabled = bool(self._enabled_config[action.id])
            self._actions[action.id] = action

        logger.debug(
            "Acción registrada: id=%s name=%s enabled=%s",
            action.id,
            action.name,
            action.enabled,
        )

    def discover_actions(self, package_name: str = "core.actions") -> None:
        """Importa módulos del paquete y registra sus clases concretas sin argumentos."""
        package = importlib.import_module(package_name)
        module_names = sorted(
            module_info.name
            for module_info in pkgutil.iter_modules(
                package.__path__,
                package.__name__ + ".",
            )
            if not module_info.name.endswith(".base_action")
        )

        for module_name in module_names:
            module = importlib.import_module(module_name)
            action_classes = [
                action_class
                for _, action_class in inspect.getmembers(module, inspect.isclass)
                if issubclass(action_class, BaseAction)
                and action_class is not BaseAction
                and action_class.__module__ == module.__name__
                and not inspect.isabstract(action_class)
                and not action_class.__name__.startswith("_")
            ]
            for action_class in action_classes:
                self.register(action_class())

        logger.info("Acciones descubiertas automáticamente: %d", len(self))

    def get(self, identifier: str) -> BaseAction:
        """Busca una acción primero por ID y después por nombre, sin distinguir mayúsculas."""
        with self._lock:
            action = self._actions.get(identifier)
            if action is not None:
                return action

            normalized = identifier.casefold()
            for registered_action in self._actions.values():
                if registered_action.name.casefold() == normalized:
                    return registered_action

        raise ActionNotFoundError(f"No existe la acción '{identifier}'")

    def get_by_id(self, action_id: str) -> BaseAction:
        """Busca exclusivamente por ID."""
        with self._lock:
            action = self._actions.get(action_id)
        if action is None:
            raise ActionNotFoundError(f"No existe la acción '{action_id}'")
        return action

    def get_by_name(self, name: str) -> BaseAction:
        """Busca exclusivamente por nombre, sin distinguir mayúsculas."""
        normalized = name.casefold()
        with self._lock:
            for action in self._actions.values():
                if action.name.casefold() == normalized:
                    return action
        raise ActionNotFoundError(f"No existe una acción llamada '{name}'")

    def list_actions(self, only_enabled: bool = False) -> list[BaseAction]:
        """Lista las acciones registradas, ordenadas por ID."""
        with self._lock:
            actions = [
                action
                for action in self._actions.values()
                if action.enabled or not only_enabled
            ]
        return sorted(actions, key=lambda action: action.id)

    def set_enabled(self, identifier: str, enabled: bool) -> BaseAction:
        """Habilita o deshabilita una acción por nombre o ID."""
        action = self.get(identifier)
        with self._lock:
            action.enabled = bool(enabled)
        logger.info(
            "Estado de acción actualizado: id=%s enabled=%s",
            action.id,
            action.enabled,
        )
        return action

    def enable(self, identifier: str) -> BaseAction:
        return self.set_enabled(identifier, True)

    def disable(self, identifier: str) -> BaseAction:
        return self.set_enabled(identifier, False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._actions)
