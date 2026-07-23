"""Chasse aux bugs « ça marche sous Linux, pas sous Windows » (QA adversarial).

Ce fichier reproduit, par du code, les écarts de comportement Windows / POSIX et les
points fragiles du flux d'installation UE4SS. Chaque test qui porte `BUG` dans son nom
DÉMONTRE un défaut réel (il documente le comportement actuel, fautif) ; les autres
verrouillent ce qui est solide pour empêcher une régression.

Le poste de dev n'a ni Windows ni le jeu : tout part de tools/make_fixture.py, et on
simule Windows en forçant sys.platform quand c'est le facteur en cause.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from fe_launcher.core import launch as launch_mod  # noqa: E402
from fe_launcher.core import logs, paths, ue4ss_setup  # noqa: E402
from fe_launcher.core.launch import (  # noqa: E402
    LaunchMode, SteamStatus, build_command)
from fe_launcher.core.ledger import Ledger  # noqa: E402
from fe_launcher.core.paths import APPID, Edition  # noqa: E402

from tools import make_fixture  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures locales : installs jetables, complètes ou nues.
# ---------------------------------------------------------------------------

def _full_nude(dest: Path) -> paths.GameInstall:
    root = make_fixture.build_install(dest, full=True, with_ue4ss=False, mods=[])
    inst = paths.inspect(root, source="fixture")
    assert inst is not None
    return inst


def _demo(dest: Path) -> paths.GameInstall:
    root = make_fixture.build_install(dest, full=False, mods=[])
    inst = paths.inspect(root, source="fixture")
    assert inst is not None
    return inst


def _files_under(win64: Path) -> set[str]:
    return {str(p.relative_to(win64)) for p in win64.rglob("*") if p.is_file()}


# ===========================================================================
# 3. FLUX D'INSTALLATION UE4SS DE BOUT EN BOUT
# ===========================================================================

def test_bundle_produces_exact_nested_layout(tmp_path):
    """SOLIDE : le bundle pose dwmapi.dll à la RACINE de Win64 et tout le reste
    dans Win64/ue4ss/. Une extraction à plat casserait le chargement (0-octet log)."""
    inst = _full_nude(tmp_path / "lib")
    led = Ledger(tmp_path / "data")
    rep = ue4ss_setup.SetupReport(ok=True)
    assert ue4ss_setup.install_from_bundle(inst, led, rep, replace=False)

    win64 = inst.engine_dir
    assert (win64 / "dwmapi.dll").is_file(), "dwmapi.dll doit être à la racine de Win64"
    assert (win64 / "ue4ss" / "UE4SS.dll").is_file()
    assert (win64 / "ue4ss" / "UE4SS-settings.ini").is_file()
    # dwmapi ne doit PAS être aussi dans ue4ss/
    assert not (win64 / "ue4ss" / "dwmapi.dll").exists()
    # la signature custom indispensable (spawn d'objets) est bien dans le bundle
    assert (win64 / "ue4ss" / "UE4SS_Signatures" / "StaticConstructObject.lua").is_file()
    # re-détection : l'install est reconnue comme NESTED (jeu complet)
    re = paths.inspect(inst.root)
    assert re.has_ue4ss and re.ue4ss.nested


def test_bundle_carries_no_gameplay_mods(tmp_path):
    """SOLIDE : le bundle n'embarque QUE les mods internes d'UE4SS, aucun mod FE
    gameplay. Sans la case « mods », rien de FE n'est posé."""
    inst = _full_nude(tmp_path / "lib")
    led = Ledger(tmp_path / "data")
    rep = ue4ss_setup.SetupReport(ok=True)
    ue4ss_setup.install_from_bundle(inst, led, rep)

    mods_dir = inst.engine_dir / "ue4ss" / "Mods"
    posed = {p.name for p in mods_dir.iterdir() if p.is_dir()}
    fe_gameplay = {n for n in posed if n.lower().startswith("ue4ss-fe")}
    assert not fe_gameplay, f"le bundle ne doit poser aucun mod FE gameplay, trouvé : {fe_gameplay}"


def test_reinstall_removes_orphans_from_old_build(tmp_path):
    """SOLIDE : la réinstallation supprime les fichiers d'un ancien build absents du
    nouveau (orphelins), au lieu de les laisser traîner."""
    inst = _full_nude(tmp_path / "lib")
    led = Ledger(tmp_path / "data")
    ue4ss_setup.install_from_bundle(inst, led, ue4ss_setup.SetupReport(ok=True))

    # Un fichier d'un « vieux build » que le nouveau ne contient pas.
    orphan = inst.engine_dir / "ue4ss" / "OldBuildOnly.dll"
    orphan.write_bytes(b"stale")
    assert orphan.is_file()

    inst2 = paths.inspect(inst.root)
    ue4ss_setup.install_from_bundle(inst2, led, ue4ss_setup.SetupReport(ok=True),
                                    replace=True)
    assert not orphan.exists(), "un orphelin de l'ancien build doit être supprimé au replace"


def test_full_undo_restores_initial_state(tmp_path):
    """SOLIDE : après install + réinstall, un undo complet redonne l'état de départ
    (aucun fichier UE4SS résiduel, dwmapi.dll compris)."""
    inst = _full_nude(tmp_path / "lib")
    win64 = inst.engine_dir
    before = _files_under(win64)

    led = Ledger(tmp_path / "data")
    ue4ss_setup.install_from_bundle(inst, led, ue4ss_setup.SetupReport(ok=True))
    ue4ss_setup.install_from_bundle(paths.inspect(inst.root), led,
                                    ue4ss_setup.SetupReport(ok=True), replace=True)
    assert (win64 / "dwmapi.dll").is_file()

    results = led.undo()
    assert all(r.ok for r in results), [r.message for r in results if not r.ok]
    after = _files_under(win64)
    assert after == before, f"état non revenu à l'origine. Résidus : {after - before}"


def test_BUG_reinstall_crashes_when_a_file_is_locked(tmp_path):
    """BUG (gravité HAUTE, Windows) : réinstaller pendant qu'un fichier UE4SS est
    VERROUILLÉ (dwmapi.dll chargée par le jeu, un .ini tenu par un antivirus) fait
    LEVER une exception non rattrapée depuis install_from_bundle.

    Sur Windows, unlink d'un fichier ouvert lève PermissionError [WinError 32]. La
    boucle de suppression du mode `replace` (ue4ss_setup.py ~L79-94) appelle
    ledger.delete_file HORS du try/except (qui ne commence qu'à ~L96). L'exception
    remonte jusqu'au slot Qt et fait planter l'assistant au lieu d'un rapport rouge.
    """
    inst = _full_nude(tmp_path / "lib")
    led = Ledger(tmp_path / "data")
    ue4ss_setup.install_from_bundle(inst, led, ue4ss_setup.SetupReport(ok=True))

    inst2 = paths.inspect(inst.root)

    def locked(path, **kw):
        raise PermissionError("[WinError 32] fichier verrouillé : " + str(path))

    led.delete_file = locked  # simule un unlink refusé (fichier tenu par un process)
    rep = ue4ss_setup.SetupReport(ok=True)
    # CORRIGÉ : un fichier verrouillé ne fait plus crasher l'assistant. On rend False,
    # avec une étape en échec — pas d'exception qui remonterait au slot Qt.
    ok = ue4ss_setup.install_from_bundle(inst2, led, rep, replace=True)
    assert ok is False
    assert any(not s.ok for s in rep.steps)


def test_bundle_create_failure_is_reported_not_raised(tmp_path):
    """SOLIDE (contraste avec le bug ci-dessus) : un échec d'ÉCRITURE (Win64 non
    inscriptible) est rattrapé et rapporté proprement — pas d'exception."""
    inst = _full_nude(tmp_path / "lib")
    led = Ledger(tmp_path / "data")

    def denied(path, content=b"", **kw):
        raise OSError("[Errno 13] Win64 non inscriptible : " + str(path))

    led.create_file = denied
    rep = ue4ss_setup.SetupReport(ok=True)
    ok = ue4ss_setup.install_from_bundle(inst, led, rep, replace=False)
    assert ok is False
    assert any(not s.ok for s in rep.steps)


def test_bundle_absent_returns_false(tmp_path, monkeypatch):
    """SOLIDE : bundle embarqué manquant → échec propre (False), pas d'exception."""
    inst = _full_nude(tmp_path / "lib")
    led = Ledger(tmp_path / "data")
    monkeypatch.setattr(ue4ss_setup, "_bundle_dir",
                        lambda: tmp_path / "does-not-exist")
    rep = ue4ss_setup.SetupReport(ok=True)
    assert ue4ss_setup.install_from_bundle(inst, led, rep) is False


# ===========================================================================
# 5. LANCEMENT ADAPTÉ À L'ÉDITION (démo vs jeu complet)
# ===========================================================================

def test_demo_launches_via_shim_not_full_appid(tmp_path):
    """SOLIDE : la démo est lancée par son shim direct, JAMAIS via
    steam://rungameid/2467880 (qui démarrerait le jeu complet → mauvais log)."""
    demo = _demo(tmp_path / "demo")
    assert demo.edition is Edition.DEMO and demo.shim_exe is not None
    cmd, cwd, warns = build_command(demo, LaunchMode.STEAM)
    assert cmd == [str(demo.shim_exe)]
    assert cwd == demo.shim_exe.parent
    assert str(APPID) not in " ".join(cmd)
    assert not any("rungameid" in c for c in cmd)


def test_full_launches_via_steam_url(tmp_path, monkeypatch):
    """SOLIDE : le jeu complet passe par steam://rungameid/<appid> sur Windows."""
    full = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    monkeypatch.setattr(launch_mod.sys, "platform", "win32")
    monkeypatch.setattr(launch_mod, "steam_status",
                        lambda: SteamStatus(True, Path("C:/Steam"), True))
    cmd, cwd, warns = build_command(full, LaunchMode.STEAM)
    assert cmd == ["cmd", "/c", "start", "", f"steam://rungameid/{APPID}"]


# ===========================================================================
# 1. FENÊTRE / CONSOLE PARASITE SOUS WINDOWS
# ===========================================================================

def test_steam_launch_detaches_console_on_windows(tmp_path, monkeypatch):
    """SOLIDE : le lancement `cmd /c start` de Steam sur Windows détache la console
    (DETACHED_PROCESS), donc aucune fenêtre noire ne flashe."""
    full = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    monkeypatch.setattr(launch_mod.sys, "platform", "win32")
    monkeypatch.setattr(launch_mod, "steam_status",
                        lambda: SteamStatus(True, Path("C:/Steam"), True))
    # DETACHED_PROCESS/CREATE_NEW_PROCESS_GROUP n'existent pas sous Linux : on les simule.
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x08, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)

    captured = {}

    class FakeProc:
        pid = 4321

    def fake_popen(cmd, **kw):
        captured.update(kw)
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    # is_running() emprunterait le vrai chemin tasklist (STARTUPINFO absent sous Linux).
    monkeypatch.setattr(launch_mod, "is_running", lambda: False)
    res = launch_mod.launch(full, mode=LaunchMode.STEAM)
    assert res.started
    flags = captured.get("creationflags", 0)
    # Au moins un drapeau qui empêche la console d'apparaître doit être posé.
    no_console = flags & (0x08 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    assert no_console, f"le lancement Steam laisse une console apparaître (flags={flags:#x})"


def test_probe_uses_no_window_on_windows(monkeypatch):
    """SOLIDE : la sonde de process (toutes les ~3 s) passe bien les kwargs no-window
    sur Windows, pour ne pas faire clignoter une console pendant qu'on joue."""
    monkeypatch.setattr(launch_mod.sys, "platform", "win32")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured.update(kw)

        class R:
            stdout = ""
        return R()

    monkeypatch.setattr(launch_mod, "run_hidden", fake_run)
    # run_hidden est ce qui injecte no_window_kwargs ; on vérifie qu'il est utilisé
    # (et non un subprocess.run nu, qui ferait clignoter la console à chaque sonde).
    launch_mod.probe_processes()
    assert captured["cmd"][0] == "tasklist"
    # no_window_kwargs() elle-même n'est vérifiable qu'à l'exécution sous Windows
    # (subprocess.STARTUPINFO/CREATE_NO_WINDOW n'existent pas sur le poste de dev) :
    # on se contente ici de garantir que la sonde ne contourne pas run_hidden.


# ===========================================================================
# 4. LECTEUR DE LOG + DÉTECTION DE FERMETURE
# ===========================================================================

_LOG_SAMPLE = (
    "[2025-01-01 10:00:00.000] UE4SS v3.0.1\n"
    "[2025-01-01 10:00:01.000] Starting Lua mod 'FEInfiniteCore'\n"
    "[2025-01-01 10:00:01.100] [Lua] [FEInfiniteCore] ready\n"
)


def test_log_found_nested_full(tmp_path):
    """SOLIDE : pour le jeu complet, le log est lu dans Win64/ue4ss/UE4SS.log."""
    inst = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    (inst.ue4ss.root / "UE4SS.log").write_text(_LOG_SAMPLE, encoding="utf-8")
    rep = logs.read(inst.ue4ss)
    assert rep.exists and rep.started
    assert "FEInfiniteCore" in rep.loaded_names


def test_log_found_flat_demo(tmp_path):
    """SOLIDE : pour la démo, le log est lu dans Win64/UE4SS.log (layout à plat)."""
    demo = paths.inspect(make_fixture.build_install(tmp_path / "demo", full=False, mods=[]))
    (demo.ue4ss.root / "UE4SS.log").write_text(_LOG_SAMPLE, encoding="utf-8")
    rep = logs.read(demo.ue4ss)
    assert rep.exists and rep.started


# ---- détection de fermeture, via l'UI ----

@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dashboard(qapp, ctx):
    from fe_launcher.ui.main_window import DashboardPage
    page = DashboardPage(ctx)
    # Ne jamais ouvrir de vraie modale (bloque en offscreen) : on capture à la place.
    page._presented = []
    page._present_dialog = lambda d: page._presented.append(d)  # type: ignore[assignment]
    return page


def _context(tmp_path, installs, active):
    from fe_launcher.ui.context import AppContext
    ctx = AppContext(data_dir=tmp_path / "appdata")
    ctx.installs = list(installs)
    ctx.select(active)
    return ctx


def test_poll_never_running_does_not_fire(qapp, tmp_path):
    """SOLIDE : si le jeu n'est jamais vu tourner, aucun résumé n'est proposé
    (un lancement Steam lent ne doit pas être pris pour une fermeture immédiate)."""
    inst = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    ctx = _context(tmp_path, [inst], inst)
    page = _dashboard(qapp, ctx)
    page._running_probe = lambda: False
    page._begin_watching()
    for _ in range(5):
        page._poll_game()
    assert page._presented == []


def test_poll_probe_raises_is_swallowed(qapp, tmp_path):
    """SOLIDE : une sonde qui lève ne fait pas remonter d'exception dans le timer."""
    inst = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    ctx = _context(tmp_path, [inst], inst)
    page = _dashboard(qapp, ctx)

    def boom():
        raise OSError("tasklist indisponible")

    page._running_probe = boom
    page._begin_watching()
    page._poll_game()  # ne doit pas lever
    assert page._presented == []


def test_poll_running_then_closed_fires_once(qapp, tmp_path):
    """SOLIDE : passage vu-tournant → fermé déclenche le résumé, une seule fois."""
    inst = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    (inst.ue4ss.root / "UE4SS.log").write_text(_LOG_SAMPLE, encoding="utf-8")
    ctx = _context(tmp_path, [inst], inst)
    page = _dashboard(qapp, ctx)

    state = {"running": True}
    page._running_probe = lambda: state["running"]
    page._begin_watching()
    page._poll_game()               # tourne
    state["running"] = False
    page._poll_game()               # fermé → 1 résumé
    page._poll_game()               # plus rien
    assert len(page._presented) == 1


def test_BUG_log_dialog_reads_wrong_install_after_switch(qapp, tmp_path):
    """BUG (gravité MOYENNE) : si l'utilisateur change d'install entre le lancement et
    la fermeture du jeu, le résumé lit le log de l'install ACTUELLEMENT sélectionnée,
    pas de celle qui a réellement tourné.

    `_play` lance `self.ctx.install`, mais `_on_game_closed` relit `self.ctx.install`
    à la fermeture. Le sélecteur (`_on_pick_install` → `ctx.select`) a pu changer
    `ctx.install` entre-temps. Le launcher présente alors le journal du MAUVAIS jeu —
    exactement le genre de confusion démo/complet que le reste du code combat.
    """
    full = paths.inspect(make_fixture.build_install(tmp_path / "full", full=True, mods=[]))
    demo = paths.inspect(make_fixture.build_install(tmp_path / "demo", full=False, mods=[]))
    ctx = _context(tmp_path, [full, demo], full)
    page = _dashboard(qapp, ctx)

    captured = {}
    import fe_launcher.ui.main_window as mw

    def spy_read(layout, **kw):
        captured["root"] = layout.root if layout else None
        return logs.LogReport(path=None, exists=False)

    orig = mw.logs.read
    mw.logs.read = spy_read
    try:
        # L'utilisateur a lancé le JEU COMPLET, puis bascule sur la DÉMO avant de fermer.
        ctx.select(demo)
        page._on_game_closed()
    finally:
        mw.logs.read = orig

    # Le bug : on a lu le log de la démo, alors que c'est le jeu complet qui a tourné.
    assert captured["root"] == demo.ue4ss.root
    assert captured["root"] != full.ue4ss.root
