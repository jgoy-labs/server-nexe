"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/integration/__init__.py
Description: Package marker per sistema d'integració automàtica d'APIs. Agrupa components

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .api_integrator import APIIntegrator
from .route_manager import RouteManager
from .openapi_merger import OpenAPIMerger

__all__ = ['APIIntegrator', 'RouteManager', 'OpenAPIMerger']