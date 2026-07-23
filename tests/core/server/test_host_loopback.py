"""
WS1-01: _host_is_loopback classifies the resolved bind host, and
_enforce_loopback_bind refuses a non-loopback bind unless the explicit
opt-in NEXE_ALLOW_PUBLIC_BIND is set.
"""

import pytest

from core.server.runner import _enforce_loopback_bind, _host_is_loopback


@pytest.mark.parametrize("host", [
    "127.0.0.1",
    "127.0.0.2",       # whole 127.0.0.0/8 is loopback
    "::1",
    "localhost",
    "LOCALHOST",
    " 127.0.0.1 ",     # tolerates stray whitespace
])
def test_loopback_hosts(host):
    assert _host_is_loopback(host) is True


@pytest.mark.parametrize("host", [
    "0.0.0.0",         # wildcard bind = reachable from the network
    "::",
    "192.168.1.10",
    "10.0.0.5",
    "example.com",     # non-IP hostnames other than localhost are not trusted
    "",
    "garbage",
])
def test_non_loopback_hosts(host):
    assert _host_is_loopback(host) is False


class TestEnforceLoopbackBind:
    def test_loopback_is_a_noop(self, monkeypatch):
        monkeypatch.delenv("NEXE_ALLOW_PUBLIC_BIND", raising=False)
        _enforce_loopback_bind("127.0.0.1")  # must not raise/exit

    def test_public_bind_without_opt_in_refuses_to_start(self, monkeypatch):
        monkeypatch.delenv("NEXE_ALLOW_PUBLIC_BIND", raising=False)
        with pytest.raises(SystemExit) as exc:
            _enforce_loopback_bind("0.0.0.0")
        assert exc.value.code == 1

    def test_public_bind_with_opt_in_proceeds_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("NEXE_ALLOW_PUBLIC_BIND", "1")
        with caplog.at_level("WARNING"):
            _enforce_loopback_bind("0.0.0.0")  # must not exit
        assert any("NON-LOOPBACK" in r.message for r in caplog.records)

    @pytest.mark.parametrize("value", ["0", "false", "", "no"])
    def test_non_truthy_opt_in_still_refuses(self, monkeypatch, value):
        monkeypatch.setenv("NEXE_ALLOW_PUBLIC_BIND", value)
        with pytest.raises(SystemExit):
            _enforce_loopback_bind("192.168.1.10")
