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

from .i18n import t

logger = logging.getLogger(__name__)

def setup_readline():
  """
  Configure readline for arrow keys and history.
  Call once at CLI startup.
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
    logger.debug(
      t(
        "cli.input.readline_setup_failed",
        "Readline setup failed: {error}",
        error=str(e)
      )
    )

setup_readline()

class Colors:
  """ANSI colors for CLI output."""
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
  prompt: Optional[str] = None,
  paste_timeout_ms: int = 100,
  show_paste_indicator: bool = True,
  join_with: str = "\n"
) -> str:
  """
  Synchronous input with multiline paste detection.

  When the user pastes multiline text (Ctrl+V):
  - Detects multiple lines arriving quickly
  - Joins them into a single string
  - Shows "[pasted X lines]" as a visual indicator

  Args:
    prompt: Prompt to show (default: ">>> ")
    paste_timeout_ms: Timeout to detect paste (default: 50ms)
    show_paste_indicator: Show "[pasted X lines]" (default: True)
    join_with: How to join lines (default: "\\n")

  Returns:
    String with all input (lines joined if pasted)

  Example:
    >>> user_input = sync_input("Tu: ")
    Tu: [user pastes 5 lines]
    [pasted 5 lines]
    >>> print(user_input)
    "line 1\\nline 2\\nline 3\\nline 4\\nline 5"
  """
  if prompt is None:
    prompt = t("cli.input.prompt_default", ">>> ")

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
    logger.debug(
      t(
        "cli.input.paste_detection_failed",
        "Paste detection failed: {error}",
        error=str(e)
      )
    )

  if len(lines) > 1 and show_paste_indicator:
    print(
      f"{Colors.DIM}{t('cli.input.paste_indicator', '[pasted {count} lines]', count=len(lines))}{Colors.RESET}"
    )

  return join_with.join(lines)

async def async_input(
  prompt: Optional[str] = None,
  paste_timeout_ms: int = 50,
  show_paste_indicator: bool = True,
  join_with: str = "\n"
) -> str:
  """
  Async input with multiline paste detection.

  Runs sync_input() in a thread executor to avoid blocking
  the async event loop, while keeping readline support.

  Args:
    prompt: Prompt to show (default: ">>> ")
    paste_timeout_ms: Timeout to detect paste (default: 50ms)
    show_paste_indicator: Show "[pasted X lines]" (default: True)
    join_with: How to join lines (default: "\\n")

  Returns:
    String with all input (lines joined if pasted)

  Example:
    >>> user_input = await async_input("Tu: ")
    Tu: [user pastes text]
    [pasted 3 lines]
  """
  loop = asyncio.get_running_loop()
  return await loop.run_in_executor(
    None,
    lambda: sync_input(prompt, paste_timeout_ms, show_paste_indicator, join_with)
  )

def add_to_history(text: str):
  """
  Add text to readline history.

  Args:
    text: Text to add to history
  """
  try:
    readline.add_history(text)
  except Exception as e:
    logger.debug(
      t(
        "cli.input.add_history_failed",
        "Add to history failed: {error}",
        error=str(e)
      )
    )

def clear_history():
  """Clear readline history."""
  try:
    readline.clear_history()
  except Exception as e:
    logger.debug(
      t(
        "cli.input.clear_history_failed",
        "Clear history failed: {error}",
        error=str(e)
      )
    )

def get_history() -> list:
  """
  Return readline history.

  Returns:
    List of history entries
  """
  try:
    return [readline.get_history_item(i) for i in range(1, readline.get_current_history_length() + 1)]
  except Exception as e:
    logger.debug(
      t(
        "cli.input.get_history_failed",
        "Get history failed: {error}",
        error=str(e)
      )
    )
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
