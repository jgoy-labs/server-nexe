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
    compat_aliases: Optional[Dict[str, str]] = None,
    on_create: Optional[Callable] = None,
    on_get_instance: Optional[Callable] = None,
):
    """
    Crea les funcions estàndard d'un manifest lazy-singleton.

    Args:
        module_path:     Import path del mòdul (ex: "plugins.ollama_module.module")
        module_class:    Nom de la classe (ex: "OllamaModule")
        tags:            Tags pel router FastAPI
        compat_aliases:  Dict {nom_atribut: "router"|"instance"} per __getattr__
        on_create:       Callback(instance) cridat just després de crear la instància
        on_get_instance: Callback(instance) cridat cada cop que es demana la instància

    Returns:
        Dict amb _get_module, get_router, get_metadata,
        get_module_instance, __getattr__
    """
    _state: Dict[str, Any] = {"module": None, "router": None}

    def _get_module():
        if _state["module"] is None:
            mod = importlib.import_module(module_path)
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
    }


def install_lazy_manifest(caller_name: str, manifest_dict: dict, extra_attrs: Optional[dict] = None):
    """
    Reemplaça el mòdul ``caller_name`` a ``sys.modules`` amb un wrapper
    que suporta ``__getattr__`` i ``__setattr__`` per al patró singleton.

    Això permet als tests fer ``mod._module = None`` per resetejar l'estat.

    Ús típic al final d'un manifest.py::

        _m = create_lazy_manifest(...)
        install_lazy_manifest(__name__, _m, extra_attrs={...})

    Args:
        caller_name:   ``__name__`` del mòdul manifest
        manifest_dict: El dict retornat per ``create_lazy_manifest``
        extra_attrs:   Atributs addicionals a exposar (retrocompatibilitat)
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
            # Deleguem al __getattr__ de la factoria
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
    # Copiem tot el __dict__ de l'original
    wrapper.__dict__.update(original.__dict__)
    # Exposem les funcions del manifest
    wrapper.__dict__["_get_module"] = manifest_dict["_get_module"]
    wrapper.__dict__["get_router"] = manifest_dict["get_router"]
    wrapper.__dict__["get_metadata"] = manifest_dict["get_metadata"]
    wrapper.__dict__["get_module_instance"] = manifest_dict["get_module_instance"]
    # Atributs extra (retrocompat, constants, etc.)
    if extra_attrs:
        wrapper.__dict__.update(extra_attrs)
    sys.modules[caller_name] = wrapper
