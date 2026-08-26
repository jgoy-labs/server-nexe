"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_vlm_alternation.py
Description: Regression guard for #860 — the VLM branch built its prompt from
             the raw message list while the text branch ran it through
             sanitize_messages_for_alternation first. Same history, two
             different prompts: the text path emits a single merged user block
             and the VLM path emitted consecutive user blocks with no
             assistant turn between them, which is a malformed prompt for
             every VL model in the catalog.

             Reachability, measured 2026-08-25 (the finding's own two routes
             were both already closed):

               - /ui/chat CANNOT reach it. SessionManager collapses
                 consecutive same-role messages before building the history
                 (session_manager.py:183-192, "prevent VLM errors"), so the
                 B125 think-only placeholder and the MC-116 interrupted turn
                 named in the finding never arrive adjacent.
               - /v1/chat/completions CAN. It does not sanitize at all;
                 separate_messages() only splits the system prompt and hands
                 the rest straight to the module. A client sending
                 [user, user, assistant] — which the OpenAI wire format allows
                 — reaches _prepare_vlm_prompt untouched, and since the
                 default model is a VLM this is the ordinary API case, not an
                 exotic one.

             The gate the finding asks for: build both prompts from the same
             anomalous history and require that they agree.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from plugins.mlx_module.core.chat import MLXChatNode
from plugins.mlx_module.core.generate_helpers import (
    prepare_tokens,
    sanitize_messages_for_alternation,
)


# A history that does NOT alternate: two user turns in a row. This is what an
# API client is free to send, and what an interrupted turn used to leave
# behind before SessionManager started collapsing them.
ANOMALOUS = [
    {"role": "user", "content": "first question"},
    {"role": "user", "content": "second question"},
    {"role": "assistant", "content": "an answer"},
]

SYSTEM = "You are Nexe."


@pytest.fixture(autouse=True)
def _stub_mlx_vlm():
    """mlx_vlm is an Apple-Silicon-only native dep, absent from the CI venv.

    Register a minimal stub so the import inside _prepare_vlm_prompt resolves;
    every test patches the behaviour explicitly and never trusts the stub.
    """
    if "mlx_vlm" in sys.modules:
        yield
        return
    fake = MagicMock()
    fake.prompt_utils = MagicMock()
    fake.prompt_utils.apply_chat_template = MagicMock(return_value="prompt")
    sys.modules["mlx_vlm"] = fake
    sys.modules["mlx_vlm.prompt_utils"] = fake.prompt_utils
    try:
        yield
    finally:
        sys.modules.pop("mlx_vlm", None)
        sys.modules.pop("mlx_vlm.prompt_utils", None)


def _build_node():
    """MLXChatNode with a fake config — no real model is loaded.

    max_kv_size None on purpose: these tests are about role alternation, and
    the context ceiling (#845, covered in test_vlm_context_budget.py) must not
    drop turns underneath them. Left to MagicMock it would auto-invent an
    attribute that is neither None nor a number.
    """
    cfg = MagicMock()
    cfg.model_path = "/tmp/_fake_model_path"  # nosemgrep: hardcode.absolute_path
    cfg.max_kv_size = None
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = cfg
    return node


def _fake_tokenizer():
    """Tokenizer stub: templating returns text, encoding returns ints."""
    tok = MagicMock()
    tok.apply_chat_template = MagicMock(return_value="rendered")
    tok.encode = MagicMock(side_effect=lambda s: list(range(len(str(s)))))
    return tok


def _vlm_messages(node, messages, system):
    """Return the message list the VLM branch hands to apply_chat_template."""
    with patch(
        "mlx_vlm.prompt_utils.apply_chat_template", return_value="prompt"
    ) as fake_act, patch(
        "builtins.open", side_effect=FileNotFoundError()
    ):  # forces mdl_config={"model_type": ""} — no Qwen directive on either side
        node._prepare_vlm_prompt(
            messages=messages,
            system=system,
            processor=MagicMock(),
            has_image=False,
            thinking_enabled=True,
        )
    return fake_act.call_args.kwargs["prompt"]


def _text_messages(messages, system):
    """Return the message list the text branch builds (3rd tuple element)."""
    _, _, all_messages, _ = prepare_tokens(
        system=system,
        messages=messages,
        messages_for_cache=messages,
        tokenizer=_fake_tokenizer(),
        thinking_enabled=True,
        model_type="",
    )
    return all_messages


class TestVlmMatchesTextPath:
    """The finding's own gate: same history in, same messages out."""

    def test_anomalous_history_builds_the_same_messages_on_both_paths(self):
        node = _build_node()
        assert _vlm_messages(node, ANOMALOUS, SYSTEM) == _text_messages(
            ANOMALOUS, SYSTEM
        )

    def test_alternating_history_was_already_identical(self):
        """Control: with a well-formed history the two paths always agreed.

        This is what made #860 latent — it only shows up on the anomalous
        input, so a test built on a normal conversation proves nothing.
        """
        node = _build_node()
        good = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "how are you"},
        ]
        assert _vlm_messages(node, good, SYSTEM) == _text_messages(good, SYSTEM)


class TestVlmSanitizesRoles:
    """Direct assertions on the shape, so a failure names the defect."""

    def test_no_two_consecutive_messages_share_a_role(self):
        node = _build_node()
        got = _vlm_messages(node, ANOMALOUS, SYSTEM)
        roles = [m["role"] for m in got]
        assert all(
            a != b for a, b in zip(roles, roles[1:])
        ), f"consecutive same-role blocks in the VLM prompt: {roles}"

    def test_the_two_user_turns_are_merged_not_dropped(self):
        """Merge, not drop — the text path's policy, which keeps both texts.

        Worth pinning: SessionManager solves the same problem by DISCARDING
        the older message (session_manager.py:188), so the two policies in
        this repo disagree. The engine path must follow the engine's own.
        """
        node = _build_node()
        got = _vlm_messages(node, ANOMALOUS, SYSTEM)
        merged = [m for m in got if m["role"] == "user"]
        assert len(merged) == 1
        assert "first question" in merged[0]["content"]
        assert "second question" in merged[0]["content"]

    def test_system_prompt_survives_sanitization(self):
        """sanitize_messages_for_alternation drops system messages by design
        (generate_helpers.py:78) — it must be applied to the history only,
        with the system prompt prepended after, exactly as the text path does.
        """
        node = _build_node()
        got = _vlm_messages(node, ANOMALOUS, SYSTEM)
        assert got[0] == {"role": "system", "content": SYSTEM}
        assert got[1:] == sanitize_messages_for_alternation(ANOMALOUS)

    def test_no_system_prompt_still_sanitizes(self):
        node = _build_node()
        got = _vlm_messages(node, ANOMALOUS, "")
        assert got == sanitize_messages_for_alternation(ANOMALOUS)
