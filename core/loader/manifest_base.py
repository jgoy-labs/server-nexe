"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/loader/manifest_base.py
Description: Factory per crear lazy-singleton manifests.
             Elimina duplicació entre plugins (F-103).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import importlib
import logging
import sys
import types
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def create_lazy_manifest(
    module_path: str,
    module_class: str,
    tags: List[str],
    *,
    removed_direct_routes: Optional[List[str]] = None,
    compat_aliases: Optional[Dict[str, str]] = None,
    on_create: Optional[Callable] = None,
    on_get_instance: Optional[Callable] = None,
):
    """
    Creates the standard functions for a lazy-singleton manifest.

    Args:
        module_path:     Import path of the module (e.g. "plugins.ollama_module.module")
        module_class:    Class name (e.g. "OllamaModule")
        tags:            Tags for the FastAPI router
        compat_aliases:  Dict {attr_name: "router"|"instance"} for __getattr__
        on_create:       Callback(instance) called right after creating the instance
        on_get_instance: Callback(instance) called every time the instance is requested

    Returns:
        Dict with _get_module, get_router, get_metadata,
        get_module_instance, __getattr__, removed_direct_routes
    """
    _removed: List[str] = list(removed_direct_routes or [])
    for _r in _removed:
        if not _r.startswith("/"):
            raise ValueError(
                f"removed_direct_routes: every entry must start with '/': {_r!r}"
            )

    _state: Dict[str, Any] = {"module": None, "router": None}

    def _get_module():
        if _state["module"] is None:
            mod = importlib.import_module(module_path)  # nosemgrep: non-literal-import — module_path from validated manifest, constrained by NEXE_APPROVED_MODULES allowlist
            cls = getattr(mod, module_class)
            instance = cls()
            instance._init_router()
            if on_create:
                on_create(instance)
            _state["module"] = instance
        return _state["module"]

    def get_router():
        if _state["router"] is None:
            module = _get_module()
            _state["router"] = module.get_router()
            _state["router"].tags = list(tags)
        return _state["router"]

    def get_metadata():
        return _get_module().metadata

    def get_module_instance():
        instance = _get_module()
        if on_get_instance:
            on_get_instance(instance)
        return instance

    aliases = compat_aliases or {}

    def __getattr__(name: str):
        if name == "_module":
            return _state["module"]
        if name == "_router":
            return _state["router"]
        target = aliases.get(name)
        if target == "router" or name == "router_public":
            return get_router()
        if target == "instance":
            return get_module_instance()
        raise AttributeError(name)

    return {
        "_state": _state,
        "_get_module": _get_module,
        "get_router": get_router,
        "get_metadata": get_metadata,
        "get_module_instance": get_module_instance,
        "__getattr__": __getattr__,
        "removed_direct_routes": _removed,
    }


def install_lazy_manifest(caller_name: str, manifest_dict: dict, extra_attrs: Optional[dict] = None):
    """
    Replaces the ``caller_name`` module in ``sys.modules`` with a wrapper
    that supports ``__getattr__`` and ``__setattr__`` for the singleton pattern.

    This allows tests to do ``mod._module = None`` to reset state.

    Typical usage at the end of a manifest.py::

        _m = create_lazy_manifest(...)
        install_lazy_manifest(__name__, _m, extra_attrs={...})

    Args:
        caller_name:   ``__name__`` of the manifest module
        manifest_dict: The dict returned by ``create_lazy_manifest``
        extra_attrs:   Additional attributes to expose (backward compatibility)
    """
    _state = manifest_dict["_state"]
    original = sys.modules[caller_name]

    class _LazyModule(types.ModuleType):

        def __getattr__(self, name):
            # Check if the original module had the attribute
            # (functions, backward-compatibility constants, etc.)
            try:
                return original.__dict__[name]
            except KeyError:
                pass
            # Delegate to the factory's __getattr__
            return manifest_dict["__getattr__"](name)

        def __setattr__(self, name, value):
            if name == "_module":
                _state["module"] = value
                return
            if name == "_router":
                _state["router"] = value
                return
            super().__setattr__(name, value)

    wrapper = _LazyModule(caller_name, original.__doc__)
    # Copy the entire __dict__ from the original
    wrapper.__dict__.update(original.__dict__)
    # Expose the manifest functions
    wrapper.__dict__["_get_module"] = manifest_dict["_get_module"]
    wrapper.__dict__["get_router"] = manifest_dict["get_router"]
    wrapper.__dict__["get_metadata"] = manifest_dict["get_metadata"]
    wrapper.__dict__["get_module_instance"] = manifest_dict["get_module_instance"]
    wrapper.__dict__["removed_direct_routes"] = manifest_dict.get("removed_direct_routes", [])
    # Extra attributes (backward compat, constants, etc.)
    if extra_attrs:
        wrapper.__dict__.update(extra_attrs)
    sys.modules[caller_name] = wrapper
