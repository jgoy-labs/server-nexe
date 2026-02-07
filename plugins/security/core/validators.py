"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/validators.py
Description: Security validators. Prevents path traversal, RCE, and command validation.

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
from fastapi import HTTPException
import shlex
import re
from typing import List
from .messages import get_message

def validate_safe_path(requested_path: Path, base_path: Path) -> Path:
  """
  Validate that a path does not include path traversal (../)

  Args:
    requested_path: Requested path (may contain ../)
    base_path: Allowed base path (root of the safe directory)

  Returns:
    Resolved and validated path within base_path

  Raises:
    HTTPException 400 if it contains path traversal
    HTTPException 404 if the file does not exist

  Usage:
    @router.get("/assets/{filename}")
    async def serve_asset(filename: str):
      safe_path = validate_safe_path(ASSETS_PATH / filename, ASSETS_PATH)
      return FileResponse(safe_path)
  """
  try:
    resolved_path = requested_path.resolve()
    base_resolved = base_path.resolve()

    if not resolved_path.is_relative_to(base_resolved):
      from .logger import log_security_event
      log_security_event("path_traversal_blocked", {
        "requested": str(requested_path),
        "resolved": str(resolved_path),
        "base": str(base_path),
        "is_relative": False
      })

      raise HTTPException(
        status_code=400,
        detail=get_message(None, "security.validators.path_traversal")
      )

    if not resolved_path.exists():
      raise HTTPException(
        status_code=404,
        detail=get_message(None, "security.validators.file_not_found", filename=resolved_path.name)
      )

    if resolved_path.is_dir():
      raise HTTPException(
        status_code=400,
        detail=get_message(None, "security.validators.path_is_directory")
      )

    return resolved_path

  except ValueError as e:
    raise HTTPException(
      status_code=400,
      detail=get_message(None, "security.validators.invalid_path_format", error=str(e))
    )

def validate_command(command: str, allowed_commands: List[str]) -> List[str]:
  """
  Validate and sanitize a command for subprocess.run
  Prevents RCE (Remote Command Execution) via a whitelist

  Args:
    command: Command to validate (string)
    allowed_commands: List of allowed base commands (whitelist)

  Returns:
    Safe list of strings for subprocess.run(...)

  Raises:
    HTTPException 400 if the format is invalid
    HTTPException 403 if the command is not allowed

  Usage:
    safe_cmd = validate_command("open file.txt", allowed_commands=["open"])
    subprocess.run(safe_cmd)
  """
  try:
    parts = shlex.split(command)
  except ValueError as e:
    raise HTTPException(
      status_code=400,
      detail=get_message(None, "security.validators.invalid_command_format", error=str(e))
    )

  if not parts:
    raise HTTPException(
      status_code=400,
      detail=get_message(None, "security.validators.empty_command")
    )

  base_command = parts[0]
  if base_command not in allowed_commands:
    from .logger import log_security_event
    log_security_event("rce_blocked", {
      "command": command,
      "base_command": base_command,
      "allowed": allowed_commands
    })

    raise HTTPException(
      status_code=403,
      detail=get_message(None, "security.validators.command_not_allowed", command=base_command, allowed=allowed_commands)
    )

  return parts

def validate_filename(filename: str) -> str:
  """
  Validate that a filename does not contain dangerous characters

  Args:
    filename: Filename to validate

  Returns:
    Validated filename

  Raises:
    HTTPException 400 if it contains dangerous characters

  Usage:
    safe_name = validate_filename(user_input)
  """
  dangerous_patterns = [
    r'\.\.',
    r'^/',
    r'^\~',
    r'\x00',
    r'[;&|`$]',
    r'[\r\n]',
  ]

  for pattern in dangerous_patterns:
    if re.search(pattern, filename):
      raise HTTPException(
        status_code=400,
        detail=get_message(None, "security.validators.invalid_filename", pattern=pattern)
      )

  if len(filename) > 255:
    raise HTTPException(
      status_code=400,
      detail=get_message(None, "security.validators.filename_too_long")
    )

  return filename

def validate_api_endpoint_path(path: str, allowed_prefixes: List[str]) -> str:
  """
  Validate that an API path is within allowed prefixes

  Args:
    path: API path to validate
    allowed_prefixes: List of allowed prefixes

  Returns:
    Validated path

  Raises:
    HTTPException 403 if not allowed

  Usage:
    safe_path = validate_api_endpoint_path(
      request.url.path,
      allowed_prefixes=["/security"]
    )
  """
  path = path.strip()

  if not any(path.startswith(prefix) for prefix in allowed_prefixes):
    raise HTTPException(
      status_code=403,
      detail=get_message(None, "security.validators.endpoint_not_allowed", prefixes=allowed_prefixes)
    )

  return path
