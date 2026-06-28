"""INST-005: la clau API mai s'ha d'imprimir a stdout en mode no-interactiu.

En mode headless (GUI wizard) stdout es reflecteix al registre VISIBLE del
wizard, així que imprimir-hi la clau l'exposa en pantalla. La clau arriba al
wizard per un canal a part ([API_KEY]). En TTY interactiu (CLI) sí s'ha de
mostrar perquè l'usuari la copiï.
"""
import io

from installer.installer_setup_config import generate_env_file


class _TTY(io.StringIO):
    def isatty(self):
        return True


class _NoTTY(io.StringIO):
    def isatty(self):
        return False


def _key_written(tmp_path):
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    line = next(l for l in env.splitlines() if l.startswith("NEXE_PRIMARY_API_KEY="))
    return line.split("=", 1)[1].strip()


def _run(buf, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdout", buf, raising=False)
    generate_env_file(tmp_path)
    return buf.getvalue()


def test_inst005_headless_does_not_print_key(tmp_path, monkeypatch):
    out = _run(_NoTTY(), tmp_path, monkeypatch)
    key = _key_written(tmp_path)
    assert key and key not in out, "INST-005: la clau NO ha de sortir a stdout en headless"


def test_inst005_interactive_tty_shows_key(tmp_path, monkeypatch):
    out = _run(_TTY(), tmp_path, monkeypatch)
    key = _key_written(tmp_path)
    assert key in out, "en TTY interactiu la clau s'ha de mostrar perquè l'usuari la copiï"
