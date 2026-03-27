"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/validators.py
Description: Security validators. Prevents path traversal, RCE and command validation.

www.jgoy.net · https://server-nexe.org
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
  Valida que un path no contingui path traversal (../)

  Args:
    requested_path: Path sol·licitat (pot contenir ../)
    base_path: Path base permès (root del directori segur)

  Returns:
    Path resolt i validat dins de base_path

  Raises:
    HTTPException 400 si conté path traversal
    HTTPException 404 si el fitxer no existeix

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
  Valida i sanititza un comandament per subprocess.run
  Prevé RCE (Remote Command Execution) mitjançant whitelist

  Args:
    command: Comandament a validar (string)
    allowed_commands: Llista de comandaments base permesos (whitelist)

  Returns:
    Lista de strings segura per subprocess.run(...)

  Raises:
    HTTPException 400 si format invàlid
    HTTPException 403 si comandament no permès

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
  Valida que un filename no contingui caràcters perillosos

  Args:
    filename: Nom del fitxer a validar

  Returns:
    Filename validat

  Raises:
    HTTPException 400 si conté caràcters perillosos

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
  Valida que un path d'API estigui dins dels prefixos permesos

  Args:
    path: Path de l'API a validar
    allowed_prefixes: Llista de prefixos permesos

  Returns:
    Path validat

  Raises:
    HTTPException 403 si no està permès

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