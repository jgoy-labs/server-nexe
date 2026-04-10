"""
Tests per installer/installer_reinstall.py — Bug 7 fix release v0.9.0.

Cobreix els 3 modes de reinstal·lació:
- wipe       → esborra totes les dades d'usuari
- overwrite  → preserva dades, només neteja venv
- backup     → fa backup primer i després wipe

També verifica detect_existing_install() i validació de modes.
"""

from pathlib import Path

import pytest

from installer.installer_reinstall import (
    DEFAULT_REINSTALL_MODE,
    REINSTALL_MODE_BACKUP,
    REINSTALL_MODE_OVERWRITE,
    REINSTALL_MODE_WIPE,
    VALID_REINSTALL_MODES,
    apply_reinstall_mode,
    backup_user_data,
    detect_existing_install,
    wipe_user_data,
)
from installer import installer_reinstall as ir


def _make_install(root: Path) -> None:
    """Crea una instal·lació falsa amb .env, storage/, knowledge/, venv/."""
    (root / ".env").write_text("NEXE_PRIMARY_API_KEY=secret-key\n")
    (root / "storage").mkdir()
    (root / "storage" / "vectors").mkdir()
    (root / "storage" / "vectors" / "qdrant.db").write_text("vectors")
    (root / "knowledge").mkdir(exist_ok=True)
    (root / "knowledge" / "doc.md").write_text("# doc")
    (root / "venv").mkdir()
    (root / "venv" / "bin").mkdir()
    (root / "venv" / "bin" / "python").write_text("#!/bin/sh")


# ── detect_existing_install ─────────────────────────────────────────────


def test_detect_existing_install_empty_dir(tmp_path):
    assert detect_existing_install(tmp_path) is False


def test_detect_existing_install_with_env(tmp_path):
    (tmp_path / ".env").write_text("x")
    assert detect_existing_install(tmp_path) is True


def test_detect_existing_install_with_storage(tmp_path):
    (tmp_path / "storage").mkdir()
    assert detect_existing_install(tmp_path) is True


def test_detect_existing_install_with_venv(tmp_path):
    (tmp_path / "venv").mkdir()
    assert detect_existing_install(tmp_path) is True


# ── wipe_user_data ──────────────────────────────────────────────────────


def test_wipe_user_data_removes_env_and_storage(tmp_path):
    """knowledge/ és documentació del sistema (s'ingereix, no és dada d'usuari).
    wipe_user_data esborra .env i storage/, però preserva knowledge/ perquè
    el tar del payload la sobreescriu en reinstal·lar."""
    _make_install(tmp_path)
    removed = wipe_user_data(tmp_path)
    removed_names = {p.name for p in removed}
    assert ".env" in removed_names
    assert "storage" in removed_names
    assert "knowledge" not in removed_names
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "storage").exists()
    assert (tmp_path / "knowledge").exists()
    # venv NO el toca wipe_user_data — això ho fa apply_reinstall_mode
    assert (tmp_path / "venv").exists()


def test_wipe_user_data_idempotent(tmp_path):
    # Sense res, no peta
    removed = wipe_user_data(tmp_path)
    assert removed == []


# ── backup_user_data ────────────────────────────────────────────────────


def test_backup_user_data_creates_timestamped_dir(tmp_path):
    _make_install(tmp_path)
    backup_dir = backup_user_data(tmp_path)
    assert backup_dir.exists()
    assert backup_dir.is_dir()
    # .nexe-backups/<timestamp>/  (fora de storage/ per sobreviure al wipe)
    assert backup_dir.parent == tmp_path / ".nexe-backups"


def test_backup_user_data_moves_files(tmp_path):
    """Aviso 4 Consultor — backup usa `shutil.move`, no `copytree`.

    Això vol dir que després del backup els originals ja NO hi són
    al project_root (s'han mogut, no copiat). És instantani al mateix
    volum i no requereix 2x disc.
    """
    _make_install(tmp_path)
    backup_dir = backup_user_data(tmp_path)
    assert (backup_dir / ".env").exists()
    assert (backup_dir / ".env").read_text() == "NEXE_PRIMARY_API_KEY=secret-key\n"
    # knowledge/ NO va al backup — és documentació del sistema, el tar la sobreescriu
    assert not (backup_dir / "knowledge").exists()
    # .env s'ha mogut (no copiat)
    assert not (tmp_path / ".env").exists()
    # knowledge/ es preserva in-place (no és dada d'usuari)
    assert (tmp_path / "knowledge" / "doc.md").exists()


def test_backup_does_not_recurse_into_existing_backups(tmp_path):
    """Dev #3 fix (Consultor passada 1, finding 4): el test original
    mirava `backup2/storage/backups` però el codi real usa
    `.nexe-backups/` com a carpeta de backups, així que l'assert passava
    per construcció sense testar res. Ara verifiquem que el segon backup
    NO conté recursivament el directori `.nexe-backups` dins seu
    (altrament seria un backup que conté el backup anterior i creixeria
    exponencialment)."""
    _make_install(tmp_path)
    # Primera passada: crea .nexe-backups/<ts1>/
    backup1 = backup_user_data(tmp_path)
    assert backup1.parent == tmp_path / ".nexe-backups"
    # Reconstruïm dades per permetre una segona passada
    # (venv no es toca pel backup, així que l'esborrem primer)
    if (tmp_path / "venv").exists():
        shutil.rmtree(tmp_path / "venv")
    _make_install(tmp_path)
    # Segona passada: no ha de recursar dins .nexe-backups/
    backup2 = backup_user_data(tmp_path)
    assert backup2.parent == tmp_path / ".nexe-backups"
    # El segon backup NO ha de contenir `.nexe-backups` dins seu
    # (ni directament ni dins storage/)
    nested_backups_root = backup2 / ".nexe-backups"
    assert not nested_backups_root.exists(), (
        "backup recursed into itself at backup_dir root"
    )
    nested_storage_backups = backup2 / "storage" / ".nexe-backups"
    assert not nested_storage_backups.exists(), (
        "backup recursed into itself via storage/.nexe-backups"
    )
    # El primer backup encara és accessible (no s'ha mogut dins el segon)
    assert backup1.exists()
    assert (backup1 / ".env").exists()


# ── apply_reinstall_mode: WIPE ──────────────────────────────────────────


def test_apply_wipe_removes_user_data_and_venv(tmp_path):
    """WIPE esborra .env, storage/ i venv, però preserva knowledge/
    (documentació del sistema — el tar la sobreescriu en reinstal·lar)."""
    _make_install(tmp_path)
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE)
    assert summary["mode"] == REINSTALL_MODE_WIPE
    assert summary["backup_dir"] is None
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "storage").exists()
    assert (tmp_path / "knowledge").exists()
    assert not (tmp_path / "venv").exists()


# ── apply_reinstall_mode: OVERWRITE ─────────────────────────────────────


def test_apply_overwrite_preserves_user_data(tmp_path):
    _make_install(tmp_path)
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert summary["mode"] == REINSTALL_MODE_OVERWRITE
    assert summary["backup_dir"] is None
    # Dades preservades
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "storage" / "vectors" / "qdrant.db").exists()
    assert (tmp_path / "knowledge" / "doc.md").exists()
    # Venv eliminat (es regenerarà)
    assert not (tmp_path / "venv").exists()


def test_apply_overwrite_no_venv_no_op(tmp_path):
    (tmp_path / ".env").write_text("x")
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert summary["removed"] == []


# ── apply_reinstall_mode: BACKUP ────────────────────────────────────────


def test_apply_backup_then_wipe(tmp_path):
    _make_install(tmp_path)
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_BACKUP)
    assert summary["mode"] == REINSTALL_MODE_BACKUP
    assert summary["backup_dir"] is not None

    backup_dir = Path(summary["backup_dir"])
    assert backup_dir.exists()
    # Backup conté les dades d'usuari
    assert (backup_dir / ".env").read_text() == "NEXE_PRIMARY_API_KEY=secret-key\n"
    # knowledge/ NO va al backup — és documentació del sistema
    assert not (backup_dir / "knowledge").exists()

    # .env i venv s'han eliminat
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "venv").exists()
    # knowledge/ es preserva in-place (el tar la sobreescriurà)
    assert (tmp_path / "knowledge" / "doc.md").exists()
    # storage/ ha estat esborrat (backup ja n'ha fet còpia abans)
    # Però com el backup ha creat storage/backups/<timestamp>, després
    # del wipe el directori 'storage' sencer no hi és. El backup_dir
    # pot quedar fora si s'ha creat dins de storage/. Verifiquem que
    # almenys el contingut del backup existeix.
    assert backup_dir.exists()


def test_apply_backup_with_custom_backup_root(tmp_path):
    _make_install(tmp_path)
    custom_backup = tmp_path.parent / "external_backups"
    summary = apply_reinstall_mode(
        tmp_path, REINSTALL_MODE_BACKUP, backup_root=custom_backup
    )
    assert Path(summary["backup_dir"]).parent == custom_backup
    # El backup extern sobreviu al wipe del project_root
    assert Path(summary["backup_dir"]).exists()
    assert (Path(summary["backup_dir"]) / ".env").exists()


# ── Validation ──────────────────────────────────────────────────────────


def test_apply_invalid_mode_raises(tmp_path):
    _make_install(tmp_path)
    with pytest.raises(ValueError, match="Invalid reinstall mode"):
        apply_reinstall_mode(tmp_path, "invalid_mode")


def test_default_mode_is_backup():
    assert DEFAULT_REINSTALL_MODE == REINSTALL_MODE_BACKUP


def test_all_modes_in_valid_set():
    assert REINSTALL_MODE_WIPE in VALID_REINSTALL_MODES
    assert REINSTALL_MODE_OVERWRITE in VALID_REINSTALL_MODES
    assert REINSTALL_MODE_BACKUP in VALID_REINSTALL_MODES
    assert len(VALID_REINSTALL_MODES) == 3


# ════════════════════════════════════════════════════════════════════════
# Tests Dev #2 — aplicació dels 7 avisos del Consultor
# ════════════════════════════════════════════════════════════════════════


# ── Aviso 1: stop server abans de qualsevol mode ─────────────────────────


def test_stop_server_called_before_any_mode(tmp_path):
    """El stop_server_func s'ha de cridar abans de tocar res."""
    _make_install(tmp_path)
    calls = []

    def fake_stop(root):
        calls.append(root)
        # Quan ens criden, .env encara hi és (no s'ha tocat)
        assert (root / ".env").exists()
        return True

    for mode in (REINSTALL_MODE_WIPE, REINSTALL_MODE_OVERWRITE, REINSTALL_MODE_BACKUP):
        _make_install(tmp_path) if not (tmp_path / ".env").exists() else None
        if not (tmp_path / ".env").exists():
            (tmp_path / ".env").write_text("x")
            (tmp_path / "storage").mkdir(exist_ok=True)
            (tmp_path / "knowledge").mkdir(exist_ok=True)
        calls.clear()
        apply_reinstall_mode(tmp_path, mode, stop_server_func=fake_stop)
        assert len(calls) == 1, f"stop_server_func not called for mode={mode}"


def test_apply_aborts_if_stop_server_fails(tmp_path):
    _make_install(tmp_path)

    def failing_stop(root):
        return False  # servidor viu, no es pot parar

    with pytest.raises(RuntimeError, match="Could not stop"):
        apply_reinstall_mode(
            tmp_path, REINSTALL_MODE_WIPE, stop_server_func=failing_stop
        )
    # Dades intactes
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "storage").exists()


def test_default_stop_server_no_pidfile(tmp_path):
    """Sense pidfile, _default_stop_server retorna True sense error."""
    assert ir._default_stop_server(tmp_path) is True


def test_default_stop_server_stale_pidfile(tmp_path):
    """Pidfile amb PID mort → retorna True i esborra el pidfile."""
    pid_dir = tmp_path / "storage" / "logs"
    pid_dir.mkdir(parents=True)
    pid_file = pid_dir / "core_supervisor.pid"
    # PID probablement mort (alt i arbitrari)
    pid_file.write_text("999999")
    assert ir._default_stop_server(tmp_path) is True
    assert not pid_file.exists()


# ── Aviso 2: overwrite regenera .env preservant secrets ──────────────────


def test_mode_overwrite_regenerates_env_keeping_secrets(tmp_path):
    """Mode overwrite ha de preservar API key i CSRF via _update_env_model_config.

    La funció apply_reinstall_mode no reescriu el .env per si mateixa —
    només valida que és llegible. La regeneració real passa quan
    generate_env_file() es crida més tard al flow de l'installer. Aquí
    verifiquem el contracte: (a) el .env queda intacte després d'overwrite
    i (b) _update_env_model_config preserva els secrets quan l'installer
    el cridi després.
    """
    _make_install(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEXE_PRIMARY_API_KEY=supersecret-abc123\n"
        "NEXE_CSRF_SECRET=csrf-xyz789\n"
        "NEXE_DEFAULT_MODEL=gemma3_4b\n"
        "NEXE_MODEL_ENGINE=ollama\n"
        "NEXE_OLLAMA_MODEL=gemma3:4b\n"
    )
    apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    # .env encara hi és (overwrite no l'esborra)
    assert env_file.exists()
    content = env_file.read_text()
    assert "NEXE_PRIMARY_API_KEY=supersecret-abc123" in content
    assert "NEXE_CSRF_SECRET=csrf-xyz789" in content

    # Ara simulem que l'installer crida el merge amb un model nou
    from installer.installer_setup_config import _update_env_model_config
    new_model = {
        "id": "qwen2.5:7b",
        "engine": "ollama",
        "prompt_tier": "full",
    }
    _update_env_model_config(env_file, new_model)
    after = env_file.read_text()
    # Secrets preservats
    assert "NEXE_PRIMARY_API_KEY=supersecret-abc123" in after
    assert "NEXE_CSRF_SECRET=csrf-xyz789" in after
    # Model refrescat
    assert "NEXE_DEFAULT_MODEL=qwen2.5:7b" in after
    assert "NEXE_OLLAMA_MODEL=qwen2.5:7b" in after


# ── Aviso 3: overwrite esborra .knowledge_ingested marker ────────────────


def test_mode_overwrite_clears_knowledge_ingested_marker(tmp_path):
    _make_install(tmp_path)
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.touch()
    assert marker.exists()

    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert not marker.exists()
    assert str(marker) in summary["removed"]
    # Storage i knowledge preservats per la resta
    assert (tmp_path / "storage" / "vectors" / "qdrant.db").exists()
    assert (tmp_path / "knowledge" / "doc.md").exists()


# ── Aviso 4: backup usa move, no copytree ────────────────────────────────


def test_mode_backup_uses_move_not_copytree(monkeypatch, tmp_path):
    """Verifiquem que backup crida shutil.move i no shutil.copytree."""
    _make_install(tmp_path)

    move_calls = []
    copytree_calls = []

    real_move = shutil.move
    real_copytree = shutil.copytree

    def tracking_move(src, dst, *a, **kw):
        move_calls.append((str(src), str(dst)))
        return real_move(src, dst, *a, **kw)

    def tracking_copytree(src, dst, *a, **kw):
        copytree_calls.append((str(src), str(dst)))
        return real_copytree(src, dst, *a, **kw)

    monkeypatch.setattr(ir.shutil, "move", tracking_move)
    monkeypatch.setattr(ir.shutil, "copytree", tracking_copytree)

    backup_user_data(tmp_path)

    assert len(move_calls) > 0, "backup ha d'usar shutil.move"
    assert len(copytree_calls) == 0, "backup NO ha d'usar shutil.copytree"


def test_mode_backup_excludes_models_by_default(tmp_path):
    """Per defecte, storage/models/ (pot ser 30+GB) queda al seu lloc."""
    _make_install(tmp_path)
    models_dir = tmp_path / "storage" / "models"
    models_dir.mkdir(parents=True)
    big_file = models_dir / "gemma3-12b.gguf"
    big_file.write_text("fake-huge-model")

    backup_dir = backup_user_data(tmp_path, exclude_models=True)

    # Models NO estan al backup
    assert not (backup_dir / "storage" / "models").exists()
    # Models encara hi són al seu lloc original
    assert big_file.exists()
    # Però altres subdirs de storage sí que s'han mogut al backup
    assert (backup_dir / "storage" / "vectors" / "qdrant.db").exists()


def test_mode_backup_includes_models_when_optin(tmp_path):
    _make_install(tmp_path)
    models_dir = tmp_path / "storage" / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "m.gguf").write_text("x")

    backup_dir = backup_user_data(tmp_path, exclude_models=False)
    # Amb opt-in, storage/ sencer es mou (incloent models/)
    assert (backup_dir / "storage" / "models" / "m.gguf").exists()


# ── Aviso 5: refusa wipe si project_root és el bundle del procés ─────────


def test_refuses_wipe_if_install_path_inside_running_bundle(tmp_path, monkeypatch):
    _make_install(tmp_path)

    def fake_is_bundle(root):
        return True

    monkeypatch.setattr(ir, "_is_project_root_running_bundle", fake_is_bundle)

    for mode in (REINSTALL_MODE_WIPE, REINSTALL_MODE_BACKUP):
        with pytest.raises(RuntimeError, match="Refusing to wipe"):
            apply_reinstall_mode(tmp_path, mode)
    # Dades intactes
    assert (tmp_path / ".env").exists()


def test_overwrite_allowed_even_if_inside_bundle(tmp_path, monkeypatch):
    """Overwrite NO fa wipe global, així que pot anar encara que project_root
    estigui dins del bundle (només toca venv + marker)."""
    _make_install(tmp_path)
    monkeypatch.setattr(ir, "_is_project_root_running_bundle", lambda r: True)

    # No ha de petar
    apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert (tmp_path / ".env").exists()


# ── Aviso 6: master key al Keychain — no es toca per defecte ─────────────


def test_wipe_does_not_touch_keychain_by_default(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"delete": False}

    def fake_delete():
        called["delete"] = True
        return True

    monkeypatch.setattr(ir, "_wipe_keychain_master_key", fake_delete)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE)
    assert called["delete"] is False


def test_wipe_keychain_optin(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"delete": False}

    def fake_delete():
        called["delete"] = True
        return True

    monkeypatch.setattr(ir, "_wipe_keychain_master_key", fake_delete)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE, wipe_keychain=True)
    assert called["delete"] is True


# ── Aviso 7: ~/.nexe/mail365*.json — no es toca per defecte ──────────────


def test_wipe_does_not_touch_home_nexe_by_default(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"oauth": False}

    def fake_oauth():
        called["oauth"] = True
        return []

    monkeypatch.setattr(ir, "_wipe_home_nexe_oauth", fake_oauth)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE)
    assert called["oauth"] is False


def test_wipe_home_nexe_optin(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"oauth": False}

    def fake_oauth():
        called["oauth"] = True
        return [Path("/tmp/fake-mail365.json")]

    monkeypatch.setattr(ir, "_wipe_home_nexe_oauth", fake_oauth)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE, wipe_home_nexe=True)
    assert called["oauth"] is True


import shutil  # noqa: E402 — usat pels tests de move tracking


# ════════════════════════════════════════════════════════════════════════
# Tests Dev #3 — fixes Consultor passada 1
# ════════════════════════════════════════════════════════════════════════


# ── Finding 2: BACKUP mode ha de preservar storage/models/ end-to-end ───


def test_apply_backup_preserves_models_end_to_end(tmp_path):
    """Finding 2 Consultor passada 1: abans del fix, mode BACKUP feia
    backup_user_data(exclude_models=True) — que preservava models/ — i
    després cridava wipe_user_data amb USER_DATA_PATHS incloent 'storage'
    → shutil.rmtree(storage) esborrava els models que havíem preservat.
    Ara el wipe post-backup és selectiu i salta storage/models/."""
    _make_install(tmp_path)
    models_dir = tmp_path / "storage" / "models"
    models_dir.mkdir(parents=True)
    model_file = models_dir / "gemma3-12b.gguf"
    model_file.write_text("fake-huge-model")
    # Subdir més típic dins storage/ que SÍ s'ha de netejar
    sessions_dir = tmp_path / "storage" / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "s1.json").write_text("{}")

    summary = apply_reinstall_mode(
        tmp_path, REINSTALL_MODE_BACKUP, exclude_models=True
    )
    assert summary["mode"] == REINSTALL_MODE_BACKUP
    backup_dir = Path(summary["backup_dir"])
    assert backup_dir.exists()

    # Assert 1: models preservats in-place, al seu lloc original
    assert model_file.exists(), (
        "BACKUP mode destruïa els models preservats — Bug 7 Consultor"
    )
    assert model_file.read_text() == "fake-huge-model"

    # Assert 2: el backup conté les dades "normals" de storage/
    assert (backup_dir / "storage" / "sessions" / "s1.json").exists()

    # Assert 3: storage/sessions/ original ja no hi és (s'ha mogut al backup)
    assert not sessions_dir.exists()

    # Assert 4: .env al backup; knowledge/ NO (és sistema, es preserva in-place)
    assert (backup_dir / ".env").exists()
    assert not (backup_dir / "knowledge").exists()
    assert (tmp_path / "knowledge").exists()

    # Assert 5: venv eliminat per reinstal·lació
    assert not (tmp_path / "venv").exists()


def test_apply_backup_full_wipe_when_include_models(tmp_path):
    """Confirma que el comportament amb exclude_models=False és el
    complet (wipe total de storage/) — cap regressió del path antic."""
    _make_install(tmp_path)
    (tmp_path / "storage" / "models").mkdir(parents=True)
    (tmp_path / "storage" / "models" / "m.gguf").write_text("x")

    apply_reinstall_mode(
        tmp_path, REINSTALL_MODE_BACKUP, exclude_models=False
    )
    # Amb opt-in, tot storage/ és al backup (i originals fora)
    assert not (tmp_path / "storage").exists()


# ── Finding 5: e2e overwrite preserva secrets via generate_env_file ─────


def test_apply_overwrite_preserves_secrets_e2e(tmp_path):
    """Finding 5 Consultor passada 1: flow complet
    apply_reinstall_mode(OVERWRITE) → generate_env_file() real → secrets
    preservats. Abans només verificàvem la unit _update_env_model_config
    però no el flow sencer."""
    _make_install(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEXE_PRIMARY_API_KEY=abc123\n"
        "NEXE_CSRF_SECRET=xyz789\n"
        "NEXE_ENV=production\n"
        "NEXE_DEFAULT_MODEL=gemma3_4b\n"
        "NEXE_MODEL_ENGINE=ollama\n"
        "NEXE_OLLAMA_MODEL=gemma3:4b\n"
        "NEXE_PROMPT_TIER=full\n"
    )

    # Pas 1 — apply overwrite: .env s'ha de mantenir intacte
    apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert env_file.exists()

    # Pas 2 — flow complet: l'installer crida generate_env_file amb un
    # model config (possiblement diferent del que hi havia). Com que
    # .env existeix, generate_env_file delega a _update_env_model_config
    # que ha de preservar els secrets.
    from installer.installer_setup_config import generate_env_file
    new_model = {
        "id": "qwen2.5:7b",
        "engine": "ollama",
        "prompt_tier": "full",
    }
    # generate_env_file imprimeix a stdout — OK, només ens importa el
    # contingut del fitxer final.
    generate_env_file(tmp_path, new_model)

    content = env_file.read_text()
    # Assert secrets intactes
    assert "NEXE_PRIMARY_API_KEY=abc123" in content, (
        "API key perduda després de generate_env_file (Bug crític)"
    )
    assert "NEXE_CSRF_SECRET=xyz789" in content, (
        "CSRF secret perdut després de generate_env_file (Bug crític)"
    )
    # Assert model refrescat
    assert "NEXE_DEFAULT_MODEL=qwen2.5:7b" in content
    assert "NEXE_OLLAMA_MODEL=qwen2.5:7b" in content
