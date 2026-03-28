"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/cli/client.py
Description: HTTP client for communicating with the Nexe server.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any, Optional
from urllib.parse import urlparse
import os
import urllib.request
import urllib.error
import json
import ssl

from .config import NexeConfig

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

class NexeClient:
  """
  HTTP client for communicating with the Nexe server.

  Uses urllib to avoid external dependencies.
  Supports HTTPS with self-signed certificates.
  """

  def __init__(self, config: Optional[NexeConfig] = None):
    """
    Initialize client.

    Args:
      config: NexeConfig instance (default: creates new)
    """
    self.config = config or NexeConfig()

    if not self.config.verify_ssl:
      self._ssl_context = ssl.create_default_context()
      self._ssl_context.check_hostname = False
      self._ssl_context.verify_mode = ssl.CERT_NONE
    else:
      self._ssl_context = None

  def _request(
    self,
    method: str,
    endpoint: str,
    data: Optional[dict] = None,
  ) -> Dict[str, Any]:
    """
    Make HTTP request to server.

    Args:
      method: HTTP method (GET, POST, etc.)
      endpoint: API endpoint (e.g., "/api/health")
      data: JSON data for POST requests

    Returns:
      Response data as dict
    """
    url = f"{self.config.server_url}{endpoint}"

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
      return {
        "error": True,
        "status_code": 0,
        "message": f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.",
      }

    api_key = os.environ.get("NEXE_PRIMARY_API_KEY", "")
    headers = {
      "Accept": "application/json",
      "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    body = None
    if data is not None:
      body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
      url,
      data=body,
      headers=headers,
      method=method,
    )

    try:
      response = urllib.request.urlopen(
        request,
        timeout=self.config.timeout,
        context=self._ssl_context,
      )

      response_data = response.read().decode("utf-8")
      return json.loads(response_data)

    except urllib.error.HTTPError as e:
      return {
        "error": True,
        "status_code": e.code,
        "message": str(e.reason),
      }
    except urllib.error.URLError as e:
      return {
        "error": True,
        "status_code": 0,
        "message": f"Connection error: {e.reason}",
        "server_offline": True,
      }
    except Exception as e:
      return {
        "error": True,
        "status_code": 0,
        "message": str(e),
      }

  def get_status(self) -> Dict[str, Any]:
    """
    Get system status from server.

    Returns:
      Status data dict
    """
    health = self._request("GET", "/health")

    if health.get("error"):
      return {
        "url": self.config.server_url,
        "server": {"online": False},
        "error": health.get("message", "Server not available"),
      }

    modules_data = self._request("GET", "/modules")
    modules = modules_data.get("modules", []) if not modules_data.get("error") else []

    return {
      "url": self.config.server_url,
      "version": health.get("version", "N/A"),
      "server": {
        "online": True,
        "status": health.get("status", "unknown"),
      },
      "modules": modules,
    }

  def get_health(self) -> Dict[str, Any]:
    """
    Get health check from server.

    Returns:
      Health data dict
    """
    return self._request("GET", "/health")

  def get_modules(self) -> Dict[str, Any]:
    """
    Get list of modules from server.

    Returns:
      Modules data dict
    """
    return self._request("GET", "/ui-control/api/modules")

  def chat(self, message: str) -> Dict[str, Any]:
    """
    Send chat message to server.

    Args:
      message: User message

    Returns:
      Chat response dict
    """
    return self._request("POST", "/api/chat", {"message": message})

_client_instance: Optional[NexeClient] = None

def get_client() -> NexeClient:
  """Get singleton client instance."""
  global _client_instance
  if _client_instance is None:
    _client_instance = NexeClient()
  return _client_instance