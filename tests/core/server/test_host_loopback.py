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


class TestRejectIPv6Bind:
    """An IPv6 bind starts a server that answers 400 to everything.

    TrustedHostMiddleware does `headers["host"].split(":")[0]`, so a request to
    `Host: [::1]:9119` yields "[" and never matches the allow-list. Refusing the
    bind is the honest outcome: better than a server that logs a happy banner
    and then rejects every single request with no explanation.
    """

    @pytest.mark.parametrize("host", ["::1", "[::1]", "fe80::1", "2001:db8::1", "::"])
    def test_ipv6_bind_refuses_to_start(self, monkeypatch, host):
        monkeypatch.delenv("NEXE_ALLOW_PUBLIC_BIND", raising=False)
        with pytest.raises(SystemExit) as exc:
            _enforce_loopback_bind(host)
        assert exc.value.code == 1

    @pytest.mark.parametrize("host", ["::1", "2001:db8::1"])
    def test_public_bind_opt_in_does_not_unlock_ipv6(self, monkeypatch, host):
        """NEXE_ALLOW_PUBLIC_BIND is about exposure, not about IPv6 support."""
        monkeypatch.setenv("NEXE_ALLOW_PUBLIC_BIND", "1")
        with pytest.raises(SystemExit):
            _enforce_loopback_bind(host)

    def test_refusal_says_what_to_do_instead(self, monkeypatch, caplog):
        monkeypatch.delenv("NEXE_ALLOW_PUBLIC_BIND", raising=False)
        with caplog.at_level("ERROR"), pytest.raises(SystemExit):
            _enforce_loopback_bind("::1")
        logged = " ".join(r.message for r in caplog.records)
        assert "IPv6" in logged
        assert "127.0.0.1" in logged

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "127.0.0.2"])
    def test_ipv4_and_hostnames_are_untouched(self, monkeypatch, host):
        monkeypatch.delenv("NEXE_ALLOW_PUBLIC_BIND", raising=False)
        _enforce_loopback_bind(host)  # must not raise/exit
