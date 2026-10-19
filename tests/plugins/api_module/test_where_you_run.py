"""The API engine tells the model it is in the cloud, and which model it is
(live 13/10: «ets Claude, no? estàs al núvol» -> «no puc confirmar-ho ni descartar-ho»,
because the base prompt says Nexe runs 100% locally)."""
import asyncio
import json

import httpx

from plugins.api_module.chat import where_you_run

BASE = [{"role": "system", "content": "Your name is Nexe. 100% locally."},
        {"role": "user", "content": "Qui ets?"}]


def test_the_note_names_the_provider_and_the_model():
    out = where_you_run(BASE, "Claude", "claude-sonnet-5-5")
    system = out[0]["content"]
    assert system.startswith("Your name is Nexe. 100% locally.")
    assert "cloud API of Claude" in system and "claude-sonnet-5-5" in system
    assert out[1] == BASE[1]


def test_the_callers_messages_are_not_changed():
    where_you_run(BASE, "Claude", "claude-sonnet-5-5")
    assert BASE[0]["content"] == "Your name is Nexe. 100% locally."


def test_without_a_system_message_one_is_added_first():
    out = where_you_run([{"role": "user", "content": "hola"}], "DeepSeek", "deepseek-chat")
    assert out[0]["role"] == "system" and "deepseek-chat" in out[0]["content"]
    assert out[1]["content"] == "hola"


def test_what_leaves_the_machine_carries_it(monkeypatch):
    from plugins.api_module.module import ApiModule

    monkeypatch.setenv("NEXE_ALLOW_CLOUD_ENGINES", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-test-not-a-secret")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    async def go():
        module = ApiModule(transport=httpx.MockTransport(handler))
        return [c async for c in module.chat("claude-sonnet-5-5", BASE, stream=False)]

    asyncio.run(go())
    system = seen["body"]["messages"][0]["content"]
    assert "claude-sonnet-5-5" in system and "cloud API of Claude" in system
    assert seen["body"]["messages"][1]["content"] == "Qui ets?"
