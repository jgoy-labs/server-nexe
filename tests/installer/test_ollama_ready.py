"""
Tests del finding #833: l'installer feia `ollama pull` abans que l'API d'Ollama
estigués llesta.

Tres forats reals (el wizard SSE ja arrencava Ollama abans del pull a
core/endpoints/installer.py):
  1. installer_setup_models._ollama_ensure_running decidia "viu" amb el
     returncode d'`ollama list`, esperava per accept TCP (accept ≠ API llesta)
     i en timeout NOMÉS avisava i continuava → el pull petava després.
  2. installer_ollama_install (macOS/Windows) declarava èxit amb el CLI
     present o el port TCP obert, mai amb l'API responent.
  3. core/cli/cli.py `model install` feia el pull sense cap comprovació.

Fix: installer/ollama_ready.py (probe GET /api/tags == 200, stdlib pur) +
fail dur reutilitzant el contracte CalledProcessError que el caller ja empara.
"""
import io
import subprocess
import urllib.error

import pytest

from installer import ollama_ready
from installer import installer_setup_models as ism


class _FakeOpener:
    def __init__(self, fn):
        self._fn = fn

    def open(self, url, timeout=None):
        return self._fn(url, timeout)



class _FakeTime:
    """Rellotge determinista: monotonic avança el que dormim."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestOllamaApiAlive:
    def test_true_on_200(self, monkeypatch):
        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(lambda url, timeout: _Resp(200)))
        assert ollama_ready.ollama_api_alive() is True

    def test_false_on_non_200(self, monkeypatch):
        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(lambda url, timeout: _Resp(503)))
        assert ollama_ready.ollama_api_alive() is False

    def test_false_when_connection_refused(self, monkeypatch):
        def _refuse(url, timeout):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(_refuse))
        assert ollama_ready.ollama_api_alive() is False

    def test_false_when_tcp_accepts_but_api_fails(self, monkeypatch):
        """MUTACIÓ-CONTROL de la classe del bug: el port accepta la connexió
        però l'API encara no serveix (500/handshake a mig arrencar). El check
        antic per socket.create_connection hauria dit "llest"."""

        def _http_error(url, timeout):
            raise urllib.error.HTTPError(url, 500, "starting up", {}, io.BytesIO(b""))

        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(_http_error))
        assert ollama_ready.ollama_api_alive() is False


class TestWaitOllamaApiReady:
    def test_ready_first_try(self, monkeypatch):
        fake = _FakeTime()
        monkeypatch.setattr(ollama_ready, "time", fake)
        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(lambda url, timeout: _Resp(200)))
        assert ollama_ready.wait_ollama_api_ready(timeout=10) is True
        assert fake.sleeps == []

    def test_ready_third_try(self, monkeypatch):
        fake = _FakeTime()
        calls = {"n": 0}

        def _flaky(url, timeout):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("not yet")
            return _Resp(200)

        monkeypatch.setattr(ollama_ready, "time", fake)
        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(_flaky))
        assert ollama_ready.wait_ollama_api_ready(timeout=30, interval=1.0) is True
        assert calls["n"] == 3

    def test_never_ready_returns_false_within_budget(self, monkeypatch):
        fake = _FakeTime()

        def _never(url, timeout):
            raise urllib.error.URLError("down")

        monkeypatch.setattr(ollama_ready, "time", fake)
        monkeypatch.setattr(ollama_ready, "_OPENER", _FakeOpener(_never))
        assert ollama_ready.wait_ollama_api_ready(timeout=5, interval=1.0) is False
        assert fake.now <= 6.5, "no pot esperar gaire més enllà del pressupost"


class TestBaseUrlResolution:
    """Review #833: el probe ha d'apuntar al MATEIX daemon que serve/pull."""

    def test_default_localhost(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("NEXE_OLLAMA_HOST", raising=False)
        assert ollama_ready._resolve_base_url() == "http://127.0.0.1:11434"

    def test_honours_ollama_host(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11500")
        assert ollama_ready._resolve_base_url() == "http://127.0.0.1:11500"

    def test_nexe_var_wins(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11500")
        monkeypatch.setenv("NEXE_OLLAMA_HOST", "http://127.0.0.1:11600")
        assert ollama_ready._resolve_base_url() == "http://127.0.0.1:11600"

    def test_bind_all_normalised(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
        assert ollama_ready._resolve_base_url() == "http://127.0.0.1:11434"

    def test_probe_url_follows_env(self, monkeypatch):
        """MUTACIÓ-CONTROL del major de la review: amb OLLAMA_HOST custom, el
        probe anava a 11434 i refusava una instal·lació sana."""
        seen = []
        monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11999")
        monkeypatch.setattr(
            ollama_ready,
            "_OPENER",
            _FakeOpener(lambda url, timeout: seen.append(url) or _Resp(200)),
        )
        assert ollama_ready.ollama_api_alive() is True
        assert seen == ["http://127.0.0.1:11999/api/tags"]

    def test_opener_is_proxy_free(self):
        """Review #833 (CONFIRMAT empíricament): el urlopen per defecte passa
        per HTTP_PROXY fins i tot cap a 127.0.0.1 — l'opener del probe no pot
        dur CAP ProxyHandler (ProxyHandler({}) buit no registra handlers, i
        passar-lo a build_opener desplaça el default basat en env)."""
        import urllib.request as _ur

        assert not any(
            isinstance(h, _ur.ProxyHandler) for h in ollama_ready._OPENER.handlers
        ), "l'opener del probe ha de ser immune a HTTP_PROXY/registre"


class TestEnsureRunningFailsHard:
    """_ollama_ensure_running: mai més WARN-i-continuar amb Ollama mort.

    Contra HEAD (espera TCP + warn + return) aquests tests són RED.
    """

    def test_skips_spawn_when_api_alive(self, monkeypatch):
        spawned = []
        monkeypatch.setattr(ism, "ollama_api_alive", lambda **kw: True, raising=False)
        monkeypatch.setattr(
            ism.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None
        )
        ism._ollama_ensure_running("/fake/ollama")
        assert spawned == [], "amb l'API viva no s'ha d'engegar cap serve"

    def test_spawns_and_waits_until_api_ready(self, monkeypatch):
        spawned = []
        monkeypatch.setattr(ism, "ollama_api_alive", lambda **kw: False, raising=False)
        monkeypatch.setattr(
            ism, "wait_ollama_api_ready", lambda **kw: True, raising=False
        )
        monkeypatch.setattr(
            ism.subprocess, "Popen", lambda *a, **k: spawned.append(a[0]) or None
        )
        ism._ollama_ensure_running("/fake/ollama")
        assert spawned and spawned[0][:2] == ["/fake/ollama", "serve"]

    def test_raises_when_api_never_ready(self, monkeypatch):
        """El cor del #833: en timeout ha de FALLAR (CalledProcessError, que el
        caller ja captura) — mai continuar cap al pull."""
        monkeypatch.setattr(ism, "ollama_api_alive", lambda **kw: False, raising=False)
        monkeypatch.setattr(
            ism, "wait_ollama_api_ready", lambda **kw: False, raising=False
        )
        monkeypatch.setattr(ism.subprocess, "Popen", lambda *a, **k: None)
        with pytest.raises(subprocess.CalledProcessError):
            ism._ollama_ensure_running("/fake/ollama")


class TestInstallerPostInstallWait:
    """installer_ollama_install: èxit d'instal·lació = API responent, no port TCP."""

    def test_wait_api_after_install_ok(self, monkeypatch):
        from installer import installer_ollama_install as ioi

        monkeypatch.setattr(ioi, "wait_ollama_api_ready", lambda **kw: True, raising=False)
        assert ioi._wait_api_after_install() is True

    def test_wait_api_after_install_timeout_is_failure(self, monkeypatch):
        """Contra HEAD el camí Windows retornava True amb el comentari 'let the
        pull retry' — i cap retry existia."""
        from installer import installer_ollama_install as ioi

        monkeypatch.setattr(ioi, "wait_ollama_api_ready", lambda **kw: False, raising=False)
        assert ioi._wait_api_after_install() is False


class TestCliEnsureBeforePull:
    """core/cli/cli.py `model install`: ensure ABANS del pull; sense API no hi ha pull."""

    def _fake_entry(self):
        class _E:
            short_name = "fake-model"
            size_gb = 1
            ollama_tag = "fake:1b"
            mlx_hf_id = None

        return _E()

    def test_pull_not_executed_when_ollama_not_ready(self, monkeypatch):
        from click.testing import CliRunner
        import core.cli.cli as cli_mod

        pulls = []
        monkeypatch.setattr(
            "personality.models.registry.get_model_entry", lambda name: self._fake_entry()
        )
        monkeypatch.setattr(
            cli_mod, "_cli_ensure_ollama_ready", lambda: False, raising=False
        )
        monkeypatch.setattr(
            cli_mod.subprocess if hasattr(cli_mod, "subprocess") else __import__("subprocess"),
            "run",
            lambda *a, **k: pulls.append(a),
        )
        runner = CliRunner()
        result = runner.invoke(cli_mod.install_model, ["fake-model", "--engine", "ollama"])
        assert pulls == [], "sense API llesta el pull NO es pot executar"
        assert result.exit_code != 0

    def test_pull_runs_after_ensure_ok(self, monkeypatch):
        from click.testing import CliRunner
        import core.cli.cli as cli_mod

        order = []
        monkeypatch.setattr(
            "personality.models.registry.get_model_entry", lambda name: self._fake_entry()
        )
        monkeypatch.setattr(
            cli_mod,
            "_cli_ensure_ollama_ready",
            lambda: order.append("ensure") or True,
            raising=False,
        )
        import subprocess as _sp

        def _fake_run(cmd, **kw):
            order.append("pull")
            return _sp.CompletedProcess(cmd, 0)

        monkeypatch.setattr(_sp, "run", _fake_run)
        runner = CliRunner()
        # input "n" → no el posem com a primary (evita l'escriptura de config)
        result = runner.invoke(
            cli_mod.install_model, ["fake-model", "--engine", "ollama"], input="n\n"
        )
        assert order == ["ensure", "pull"], f"ordre incorrecte: {order} ({result.output})"
