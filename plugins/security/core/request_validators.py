"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/request_validators.py
Description: Validadors de requests FastAPI. Valida headers, params i paths contra injeccions.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from fastapi import HTTPException, Request

from .injection_detectors import (
  detect_xss_attempt,
  detect_sql_injection,
  detect_command_injection,
  detect_path_traversal,
)

from .messages import get_message

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
  "application/json",
  "application/x-www-form-urlencoded",
  "multipart/form-data",
  "text/plain",
  "application/xml",
  "text/xml",
}

ALLOWED_CHARSETS = {
  "utf-8",
  "utf-16",
  "iso-8859-1",
  "us-ascii",
}

def validate_content_type(content_type: str, method: str = "POST", i18n=None, request: Request = None) -> bool:
  """
  Validate request Content-Type header with i18n support.

  Args:
    content_type: Content-Type header value
    method: HTTP method (GET, POST, etc.)
    i18n: I18n manager for translated error messages (optional)
    request: FastAPI Request object for SIEM logging (optional)

  Returns:
    True if valid

  Raises:
    HTTPException: 415 Unsupported Media Type
  """
  if not content_type and method in ["GET", "DELETE", "HEAD", "OPTIONS"]:
    return True

  base_content_type = content_type.split(";")[0].strip().lower()

  if base_content_type not in ALLOWED_CONTENT_TYPES:
    if request and hasattr(request, 'app') and hasattr(request.app, 'state'):
      if hasattr(request.app.state, 'security_logger'):
        client_ip = request.client.host if request.client else "unknown"
        request.app.state.security_logger.log_invalid_content_type(
          ip_address=client_ip,
          endpoint=str(request.url.path),
          content_type=content_type
        )

    raise HTTPException(
      status_code=415,
      detail=get_message(i18n, 'security.request.content_type_not_allowed',
               content_type=content_type)
    )

  return True

def validate_charset(content_type: str, i18n=None) -> bool:
  """
  Validate charset in Content-Type header with i18n support.

  Args:
    content_type: Content-Type header value
    i18n: I18n manager for translated error messages (optional)

  Returns:
    True if valid

  Raises:
    HTTPException: 415 Unsupported Media Type or 400 Bad Request
  """
  if "charset=" in content_type.lower():
    try:
      charset_part = [p for p in content_type.split(";") if "charset=" in p.lower()][0]
      charset = charset_part.split("=")[1].strip().lower()

      if charset not in ALLOWED_CHARSETS:
        raise HTTPException(
          status_code=415,
          detail=get_message(i18n, 'security.request.charset_not_allowed',
                   charset=charset)
        )
    except (IndexError, ValueError):
      raise HTTPException(
        status_code=400,
        detail=get_message(i18n, 'security.request.content_type_header_invalid')
      )

  return True

async def validate_request_headers(request: Request) -> bool:
  """
  Validate request headers (Content-Type, charset) with i18n support.

  Args:
    request: FastAPI Request object

  Returns:
    True if validation passes

  Raises:
    HTTPException: If validation fails
  """
  i18n = None
  if hasattr(request, 'app') and hasattr(request.app, 'state'):
    i18n = getattr(request.app.state, 'i18n', None)

  if request.method in ["POST", "PUT", "PATCH"]:
    content_type = request.headers.get("content-type", "")

    if content_type:
      validate_content_type(content_type, request.method, i18n=i18n, request=request)
      validate_charset(content_type, i18n=i18n)

  return True

async def validate_request_params(request: Request) -> bool:
  """
  Validate query parameters for injection attacks with i18n support.

  Args:
    request: FastAPI Request object

  Returns:
    True if validation passes

  Raises:
    HTTPException: If validation fails
  """
  i18n = None
  if hasattr(request, 'app') and hasattr(request.app, 'state'):
    i18n = getattr(request.app.state, 'i18n', None)

  for key, value in request.query_params.items():
    client_ip = request.client.host if request.client else "unknown"

    if detect_xss_attempt(value):
      logger.warning(
        "🚫 XSS attempt in query param '%s' from %s", key, client_ip
      )

      if hasattr(request, 'app') and hasattr(request.app, 'state'):
        if hasattr(request.app.state, 'security_logger'):
          request.app.state.security_logger.log_xss_attempt(
            ip_address=client_ip,
            endpoint=str(request.url.path),
            payload=value[:200]
          )

      raise HTTPException(
        400,
        get_message(i18n, 'security.request.invalid_query_param', param=key)
      )

    if detect_sql_injection(value):
      logger.warning(
        "🚫 SQL injection attempt in query param '%s' from %s", key, client_ip
      )

      if hasattr(request, 'app') and hasattr(request.app, 'state'):
        if hasattr(request.app.state, 'security_logger'):
          request.app.state.security_logger.log_sql_injection_attempt(
            ip_address=client_ip,
            endpoint=str(request.url.path),
            payload=value[:200]
          )

      raise HTTPException(
        400,
        get_message(i18n, 'security.request.invalid_query_param', param=key)
      )

    if detect_command_injection(value):
      logger.warning(
        "🚫 Command injection attempt in query param '%s' from %s", key, client_ip
      )

      if hasattr(request, 'app') and hasattr(request.app, 'state'):
        if hasattr(request.app.state, 'security_logger'):
          request.app.state.security_logger.log_command_injection_attempt(
            ip_address=client_ip,
            endpoint=str(request.url.path),
            payload=value[:200]
          )

      raise HTTPException(
        400,
        get_message(i18n, 'security.request.invalid_query_param', param=key)
      )

    if detect_path_traversal(value):
      logger.warning(
        "🚫 Path traversal attempt in query param '%s' from %s", key, client_ip
      )
      raise HTTPException(
        400,
        get_message(i18n, 'security.request.invalid_query_param', param=key)
      )

  return True

async def validate_request_path(request: Request) -> bool:
  """
  Validate request URL path with i18n support.

  Args:
    request: FastAPI Request object

  Returns:
    True if validation passes

  Raises:
    HTTPException: If validation fails
  """
  i18n = None
  if hasattr(request, 'app') and hasattr(request.app, 'state'):
    i18n = getattr(request.app.state, 'i18n', None)

  path = str(request.url.path)

  if detect_path_traversal(path):
    logger.warning(
      f"🚫 Path traversal attempt: {path} from {request.client.host if request.client else 'unknown'}"
    )
    raise HTTPException(
      400,
      get_message(i18n, 'security.request.invalid_path')
    )

  return True

async def validate_all_request_inputs(request: Request) -> bool:
  """
  Complete request validation (headers, params, path).

  This is the main validation dependency to use in FastAPI endpoints.

  Args:
    request: FastAPI Request object

  Returns:
    True if all validations pass

  Raises:
    HTTPException: If any validation fails

  Usage:
    @router.post("/endpoint")
    async def endpoint(
      data: dict,
      _: bool = Depends(validate_all_request_inputs)
    ):
      return {"status": "ok"}
  """
  await validate_request_headers(request)
  await validate_request_path(request)
  await validate_request_params(request)

  return True