"""A streamed request to a provider asks for the closing usage event; a whole-reply request does not."""
from plugins.api_module.chat import build_payload


def _payload(stream):
    return build_payload("m", [{"role": "user", "content": "hi"}], stream, None, None)


def test_a_streamed_request_asks_the_provider_for_its_token_count():
    assert _payload(True)["stream_options"] == {"include_usage": True}


def test_a_whole_reply_request_sends_no_stream_options():
    assert "stream_options" not in _payload(False)
