"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/input_handler.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import logging
import readline
import select
import sys
from typing import Optional

logger = logging.getLogger(__name__)

def setup_readline():
  """
  Configura readline per suport de fletxes i historial.
  Cridar una vegada al inici del CLI.
  """
  try:
    readline.parse_and_bind('set editing-mode emacs')
    readline.parse_and_bind('"\e[A": previous-history')
    readline.parse_and_bind('"\e[B": next-history')
    readline.parse_and_bind('"\e[C": forward-char')
    readline.parse_and_bind('"\e[D": backward-char')
    readline.parse_and_bind('"\e[H": beginning-of-line')
    readline.parse_and_bind('"\e[F": end-of-line')
  except Exception as e:
    logger.debug("Readline setup failed: %s", e)

setup_readline()

class Colors:
  """Colors ANSI per output del CLI."""
  RESET = "\033[0m"
  BOLD = "\033[1m"
  DIM = "\033[2m"

  RED = "\033[31m"
  GREEN = "\033[32m"
  YELLOW = "\033[33m"
  BLUE = "\033[34m"
  MAGENTA = "\033[35m"
  CYAN = "\033[36m"
  WHITE = "\033[37m"

  BRIGHT_RED = "\033[91m"
  BRIGHT_GREEN = "\033[92m"
  BRIGHT_YELLOW = "\033[93m"
  BRIGHT_BLUE = "\033[94m"
  BRIGHT_MAGENTA = "\033[95m"
  BRIGHT_CYAN = "\033[96m"

def sync_input(
  prompt: str = ">>> ",
  paste_timeout_ms: int = 100,
  show_paste_indicator: bool = True,
  join_with: str = "\n"
) -> str:
  """
  Input síncron amb detecció de paste multilínia.

  Quan l'usuari fa Ctrl+V de text multilínia:
  - Detecta que arriben múltiples línies ràpidament
  - Les ajunta en un sol string
  - Mostra "[pasted X lines]" com a indicador visual

  Args:
    prompt: Prompt a mostrar (default: ">>> ")
    paste_timeout_ms: Timeout per detectar paste (default: 50ms)
    show_paste_indicator: Mostrar "[pasted X lines]" (default: True)
    join_with: Com ajuntar línies (default: "\\n")

  Returns:
    String amb tot l'input (línies ajuntades si paste)

  Example:
    >>> user_input = sync_input("Tu: ")
    Tu: [usuari enganxa 5 línies]
    [pasted 5 lines]
    >>> print(user_input)
    "línia 1\\nlínia 2\\nlínia 3\\nlínia 4\\nlínia 5"
  """
  try:
    first_line = input(prompt)
  except (EOFError, KeyboardInterrupt):
    raise

  lines = [first_line]

  try:
    timeout_s = paste_timeout_ms / 1000.0
    while True:
      readable, _, _ = select.select([sys.stdin], [], [], timeout_s)
      if not readable:
        break
      extra_line = sys.stdin.readline()
      if extra_line:
        lines.append(extra_line.rstrip('\n'))
      else:
        break
  except Exception as e:
    logger.debug("Paste detection failed: %s", e)

  if len(lines) > 1 and show_paste_indicator:
    print(f"{Colors.DIM}[pasted {len(lines)} lines]{Colors.RESET}")

  return join_with.join(lines)

async def async_input(
  prompt: str = ">>> ",
  paste_timeout_ms: int = 50,
  show_paste_indicator: bool = True,
  join_with: str = "\n"
) -> str:
  """
  Input asíncron amb detecció de paste multilínia.

  Executa sync_input() en un thread executor per no bloquejar
  l'event loop async, mantenint el suport de readline.

  Args:
    prompt: Prompt a mostrar (default: ">>> ")
    paste_timeout_ms: Timeout per detectar paste (default: 50ms)
    show_paste_indicator: Mostrar "[pasted X lines]" (default: True)
    join_with: Com ajuntar línies (default: "\\n")

  Returns:
    String amb tot l'input (línies ajuntades si paste)

  Example:
    >>> user_input = await async_input("Tu: ")
    Tu: [usuari enganxa text]
    [pasted 3 lines]
  """
  loop = asyncio.get_running_loop()
  return await loop.run_in_executor(
    None,
    lambda: sync_input(prompt, paste_timeout_ms, show_paste_indicator, join_with)
  )

def add_to_history(text: str):
  """
  Afegeix text a l'historial de readline.

  Args:
    text: Text a afegir a l'historial
  """
  try:
    readline.add_history(text)
  except Exception as e:
    logger.debug("Add to history failed: %s", e)

def clear_history():
  """Neteja l'historial de readline."""
  try:
    readline.clear_history()
  except Exception as e:
    logger.debug("Clear history failed: %s", e)

def get_history() -> list:
  """
  Retorna l'historial de readline.

  Returns:
    Llista amb els elements de l'historial
  """
  try:
    return [readline.get_history_item(i) for i in range(1, readline.get_current_history_length() + 1)]
  except Exception as e:
    logger.debug("Get history failed: %s", e)
    return []

__all__ = [
  "sync_input",
  "async_input",
  "setup_readline",
  "add_to_history",
  "clear_history",
  "get_history",
  "Colors",
]