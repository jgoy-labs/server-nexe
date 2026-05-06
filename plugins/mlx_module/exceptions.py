# -*- coding: utf-8 -*-
"""Excepcions del mòdul MLX."""


class MissingDependencyError(RuntimeError):
    """Dependència requerida no disponible en l'entorn d'execució actual."""
