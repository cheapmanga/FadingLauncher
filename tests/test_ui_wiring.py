"""Câblage UI des trois fonctions métier : Steam, résumé des logs, détection de fermeture.

Ces tests ne vérifient pas l'apparence (c'est le rôle des captures) mais que le flux
tient : la section Steam se construit même sans Steam sur la machine, une préférence
cochée atteint le disque, et surtout le mécanisme de détection de fermeture du jeu
déclenche bien le dialogue de résumé — vérifié en injectant une fausse sonde de process,
puisque sur ce poste de dev le jeu ne tourne jamais.
"""

from __future__ import annotations

import os

# Doit être posé AVANT le premier import de Qt.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fe_launcher.core import logs  # noqa: E402
from fe_launcher.core.logs import LogReport  # noqa: E402
from fe_launcher.core.settings import Settings  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.main_window import DashboardPage, LogReviewDialog  # noqa: E402
from fe_launcher.ui.pages import SettingsPage  # noqa: E402
from fe_launcher.ui.theme import stylesheet  # noqa: E402

from .conftest import make_install  # noqa: E402

#: Un vrai log UE4SS du PC de jeu, pour éprouver le dialogue sur des données réelles.
SAMPLE_LOG = Path(
    "/home/pb/devDocker/antoine/glitch-hunting/AZAMA logs et tout/UE4SS(2).log")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet())
    return app


@pytest.fixture
def ctx(qapp, tmp_path: Path) -> AppContext:
    install = make_install(tmp_path / "lib")
    context = AppContext(data_dir=tmp_path / "appdata")
    context.installs = [install]
    context.select(install)
    return context


# --- TÂCHE 1 : section Streaming / Steam -----------------------------------------

def test_steam_section_builds_without_steam(ctx):
    """Sans install Steam sur la machine (le cas de ce PC), la section s'affiche.

    `steamcfg.status` rend alors `supported=False` : la page doit le dire proprement, pas
    planter. C'est exactement la situation du poste de développement.
    """
    page = SettingsPage(ctx)
    st = __import__("fe_launcher.core.steamcfg", fromlist=["status"]).status(
        page._launcher_exe())
    assert st.supported is False, "ce poste n'a pas d'install Steam"
    # Le badge et le message reflètent l'absence de Steam, sans exception.
    assert page.steam_status_badge.text() == "STEAM ABSENT"
    assert page.steam_status_label.text() == st.message
    # Le repli manuel est TOUJOURS renseigné, même sans branchement possible.
    assert page._launcher_exe() in page.steam_copy_line.text()
    assert "%command%" in page.steam_copy_line.text()


def test_launcher_exe_falls_back_to_python(ctx):
    """Sans exe renseigné, on retombe sur l'interpréteur courant (dev)."""
    ctx.settings.launcher_exe = ""
    page = SettingsPage(ctx)
    assert page._launcher_exe() == sys.executable


def test_stream_mode_toggle_persists(ctx):
    """Cocher « Mode discret » l'écrit sur le disque, pas seulement en mémoire."""
    page = SettingsPage(ctx)
    assert ctx.settings.stream_mode is False  # défaut demandé
    page.stream_mode_box.setChecked(True)
    reloaded = Settings.load(ctx.data_dir)
    assert reloaded.stream_mode is True


def test_unwire_button_disabled_when_not_wired(ctx):
    """Rien à débrancher tant qu'on n'est pas branché : le bouton reste inactif."""
    page = SettingsPage(ctx)
    assert not page.unwire_btn.isEnabled()


# --- TÂCHE 2 : case « Lire les logs à la fermeture » -----------------------------

def test_review_logs_toggle_persists(ctx):
    """La préférence de résumé des logs atteint le disque."""
    page = SettingsPage(ctx)
    assert ctx.settings.review_logs_on_close is True  # défaut
    page.review_logs_box.setChecked(False)
    assert Settings.load(ctx.data_dir).review_logs_on_close is False


# --- TÂCHE 3 : détection de fermeture + dialogue de résumé -----------------------

def test_close_detection_fires_dialog_on_running_to_stopped(ctx):
    """Le dialogue de résumé se déclenche quand la sonde passe de « tourne » à « fermé »."""
    page = DashboardPage(ctx)

    captured: list[object] = []
    page._present_dialog = lambda dlg: captured.append(dlg)

    state = {"running": True}
    page._running_probe = lambda: state["running"]

    # Le jeu tourne : rien ne se déclenche encore.
    page._poll_game()
    assert captured == []
    # Il se ferme : le résumé est proposé, une seule fois.
    state["running"] = False
    page._poll_game()
    page._poll_game()

    assert len(captured) == 1, "le dialogue ne doit s'ouvrir qu'une fois"
    assert isinstance(captured[0], LogReviewDialog)


def test_close_detection_ignores_never_seen_running(ctx):
    """Un jeu jamais vu tourner (Steam lent, sonde négative) ne déclenche rien."""
    page = DashboardPage(ctx)
    captured: list[object] = []
    page._present_dialog = lambda dlg: captured.append(dlg)
    page._running_probe = lambda: False

    for _ in range(3):
        page._poll_game()
    assert captured == []


def test_close_detection_respects_the_preference(ctx):
    """Si l'utilisateur a coupé le résumé, la fermeture ne propose rien."""
    ctx.settings.review_logs_on_close = False
    page = DashboardPage(ctx)
    captured: list[object] = []
    page._present_dialog = lambda dlg: captured.append(dlg)
    state = {"running": True}
    page._running_probe = lambda: state["running"]

    page._poll_game()
    state["running"] = False
    page._poll_game()
    assert captured == [], "résumé désactivé : aucun dialogue"


def test_log_review_dialog_on_real_report(qapp, tmp_path):
    """Le dialogue se construit sur un vrai log UE4SS du PC de jeu."""
    if not SAMPLE_LOG.is_file():
        pytest.skip("log d'exemple indisponible sur cette machine")
    report = logs.read(None, path=SAMPLE_LOG)
    assert report.exists and report.mods, "le log d'exemple doit contenir des mods"
    dialog = LogReviewDialog(report, tmp_path / "logs")
    # Le titre porte le headline ; le dialogue expose bien un bouton d'archivage.
    assert report.headline
    from PySide6.QtWidgets import QPushButton
    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "Archiver ce log" in labels


def test_log_review_dialog_when_no_log(qapp, tmp_path):
    """Sans log (report.exists=False), le dialogue le dit et n'offre pas d'archivage."""
    report = LogReport(path=None, exists=False)
    dialog = LogReviewDialog(report, tmp_path / "logs")
    from PySide6.QtWidgets import QPushButton
    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "Archiver ce log" not in labels, "rien à archiver sans log"
    assert any("Fermer" == t for t in labels)


def test_archive_from_dialog_writes_a_copy(qapp, tmp_path):
    """Le bouton d'archivage copie bien le log là où on l'attend."""
    if not SAMPLE_LOG.is_file():
        pytest.skip("log d'exemple indisponible sur cette machine")
    report = logs.read(None, path=SAMPLE_LOG)
    dest_dir = tmp_path / "logs"
    written = logs.archive(report, dest_dir)
    assert written is not None and written.is_file()
    assert written.parent == dest_dir
