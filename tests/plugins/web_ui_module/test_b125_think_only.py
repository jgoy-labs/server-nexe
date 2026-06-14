"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_b125_think_only.py
Description: B125 — a think-only assistant turn must still persist an assistant
            message, otherwise get_context_messages() drops the next user turn
            as a consecutive-duplicate role.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import inspect

from plugins.web_ui_module.api import routes_chat
from plugins.web_ui_module.core.session_manager import ChatSession


# ── The fix itself: _think_only_placeholder ──────────────────────────────────

class TestThinkOnlyPlaceholder:
    def test_think_only_returns_placeholder(self):
        """Model produced output (thinking) but it cleaned to empty → placeholder."""
        assert routes_chat._think_only_placeholder("", "<think>reasoning</think>") == "…"

    def test_non_empty_clean_response_is_unchanged(self):
        """A real answer is never replaced by the placeholder."""
        assert routes_chat._think_only_placeholder("hola", "<think>x</think>hola") == "hola"

    def test_genuinely_empty_turn_stays_empty(self):
        """No full_response (e.g. upstream exception) → nothing is fabricated."""
        assert routes_chat._think_only_placeholder("", "") == ""


# ── Why it matters: real ChatSession context re-pairing ──────────────────────

class TestContextPairingDropsUserWithoutAssistant:
    def test_missing_assistant_drops_next_user_turn(self):
        """Documents the bug: two consecutive user turns → the newer is dropped.

        This is the real get_context_messages() de-dup that B125 trips when a
        think-only turn persists no assistant message.
        """
        session = ChatSession()
        session.add_message("user", "primera pregunta")
        session.add_message("user", "segona pregunta")  # no assistant in between

        ctx = session.get_context_messages()
        users = [m for m in ctx if m["role"] == "user"]
        assert len(users) == 1  # the second user turn is silently lost

    def test_placeholder_assistant_preserves_next_user_turn(self):
        """With the placeholder assistant turn, both user messages survive."""
        session = ChatSession()
        session.add_message("user", "primera pregunta")
        session.add_message("assistant", "…")  # B125 placeholder
        session.add_message("user", "segona pregunta")

        ctx = session.get_context_messages()
        users = [m for m in ctx if m["role"] == "user"]
        assert len(users) == 2
        assert users[1]["content"] == "segona pregunta"


# ── Anti-theatre: the helper is actually wired into the streaming route ──────

def test_placeholder_is_wired_into_response_generator():
    """Guard: the route must invoke the helper at the persistence point.

    Without this, the helper could be tested in isolation while the real route
    silently stops calling it (test-theatre). We assert the exact call site.
    """
    src = inspect.getsource(routes_chat)
    assert "_think_only_placeholder(clean_response, full_response)" in src, (
        "the streaming route must call _think_only_placeholder before persisting "
        "the assistant turn (B125)"
    )
