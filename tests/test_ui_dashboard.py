"""Tests du tableau de bord : sélecteur d'installation et assistant UE4SS.

Ces deux ajouts touchent au point le plus sensible du launcher — quelle install on
regarde, et comment on la répare. Les trois choses qu'ils peuvent casser en silence :

1. **Le sélecteur n'apparaît qu'à partir de deux installs**, et changer sa valeur bascule
   VRAIMENT l'install active (`ctx.select`). Sans ça, l'utilisateur du jeu complet
   diagnostiquerait la démo en croyant regarder son jeu.
2. **Le bouton UE4SS apparaît quand il faut** : UE4SS absent, ou chemin grec à corriger.
3. **L'assistant lance bien `ue4ss_setup.run`** et affiche son rapport — refus compris.

On ne touche jamais au disque réel d'un vrai jeu : tout part de `tools/make_fixture.py`,
et `ue4ss_setup.run` est remplacé pour ne pas dépendre d'un renommage effectif.
"""

from __future__ import annotations

import os

# Doit être posé AVANT le premier import de Qt, sinon Qt tente d'ouvrir un affichage.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from fe_launcher.core import ue4ss_setup  # noqa: E402
from fe_launcher.core.ue4ss_setup import SetupReport  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.main_window import DashboardPage, Ue4ssSetupDialog  # noqa: E402
from fe_launcher.ui.theme import stylesheet  # noqa: E402

from .conftest import make_install  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet())
    return app


def _ctx(tmp_path: Path, installs, active) -> AppContext:
    context = AppContext(data_dir=tmp_path / "appdata")
    context.installs = list(installs)
    context.select(active)
    return context


# --- sélecteur d'installation ----------------------------------------------------

def test_picker_appears_with_two_installs(qapp, tmp_path):
    """Deux installs : un sélecteur les liste toutes, l'active en premier plan."""
    full = make_install(tmp_path / "full")
    demo = make_install(tmp_path / "demo", full=False)
    ctx = _ctx(tmp_path, [demo, full], full)

    page = DashboardPage(ctx)
    assert hasattr(page, "install_picker"), "le sélecteur doit exister à deux installs"
    assert page.install_picker.count() == 2
    # L'install active (le jeu complet) est bien celle sélectionnée.
    assert "Jeu complet" in page.install_picker.currentText()


def test_single_install_has_no_picker(qapp, tmp_path):
    """Une seule install : pas de liste déroulante à un choix, juste le nom."""
    full = make_install(tmp_path / "full")
    ctx = _ctx(tmp_path, [full], full)

    page = DashboardPage(ctx)
    # Le picker peut rester en attribut d'un test précédent, mais il ne doit pas être
    # dans la carte : on vérifie l'absence dans le contenu affiché.
    from fe_launcher.ui.widgets import ComboBox
    combos = page.install_card.findChildren(ComboBox)
    assert combos == [], "une install unique ne doit pas afficher de sélecteur"


def test_changing_picker_selects_the_install(qapp, tmp_path):
    """Changer la sélection bascule l'install active via ctx.select."""
    full = make_install(tmp_path / "full")
    demo = make_install(tmp_path / "demo", full=False)
    ctx = _ctx(tmp_path, [demo, full], full)

    calls: list = []
    original_select = ctx.select

    def spy(inst):
        calls.append(inst)
        return original_select(inst)

    ctx.select = spy  # type: ignore[method-assign]

    page = DashboardPage(ctx)
    # Index 0 = demo (voir l'ordre de la liste). On y bascule.
    page.install_picker.setCurrentIndex(0)

    assert calls, "changer la sélection doit appeler ctx.select"
    assert ctx.install.root == demo.root, "l'install active doit être la démo"


# --- bouton UE4SS ----------------------------------------------------------------

def test_ue4ss_button_appears_without_ue4ss(qapp, tmp_path):
    """Sans UE4SS, la carte install propose le bouton d'installation."""
    inst = make_install(tmp_path / "lib", with_ue4ss=False)
    ctx = _ctx(tmp_path, [inst], inst)

    page = DashboardPage(ctx)
    labels = [b.text() for b in page.install_card.findChildren(QPushButton)]
    assert any("Installer UE4SS" in t for t in labels)


def test_ue4ss_button_appears_for_greek_path(qapp, tmp_path):
    """Chemin grec (jeu complet) : le bouton apparaît même si UE4SS est présent.

    C'est le piège du jeu complet — UE4SS « installé » mais mort au démarrage à cause de
    l'omicron grec. Le bouton doit proposer le correctif.
    """
    inst = make_install(tmp_path / "lib")  # full = chemin « Project Ygrό »
    assert inst.has_ue4ss and inst.non_ascii_path
    ctx = _ctx(tmp_path, [inst], inst)

    page = DashboardPage(ctx)
    labels = [b.text() for b in page.install_card.findChildren(QPushButton)]
    assert any("Installer UE4SS" in t for t in labels)


def test_ue4ss_button_absent_when_clean(qapp, tmp_path):
    """Démo saine (UE4SS présent, chemin ASCII) : pas de bouton d'installation."""
    inst = make_install(tmp_path / "lib", full=False)
    assert inst.has_ue4ss and not inst.non_ascii_path
    ctx = _ctx(tmp_path, [inst], inst)

    page = DashboardPage(ctx)
    labels = [b.text() for b in page.install_card.findChildren(QPushButton)]
    assert not any("Installer UE4SS" in t for t in labels)


# --- assistant UE4SS -------------------------------------------------------------

def test_setup_dialog_builds(qapp, tmp_path):
    """Le dialogue se construit sur une install réelle sans exploser."""
    inst = make_install(tmp_path / "lib", with_ue4ss=False)
    ctx = _ctx(tmp_path, [inst], inst)
    dialog = Ue4ssSetupDialog(ctx)
    assert dialog.run_btn.text() == "Lancer l'installation"
    assert dialog._zip is None


def test_setup_dialog_warns_on_bad_zip(qapp, tmp_path):
    """Un zip non reconnu déclenche l'avertissement rouge, sans bloquer."""
    inst = make_install(tmp_path / "lib", with_ue4ss=False)
    ctx = _ctx(tmp_path, [inst], inst)
    dialog = Ue4ssSetupDialog(ctx)

    dialog._set_zip(tmp_path / "pas_ue4ss.zip")  # inexistant → non reconnu
    # isHidden reflète l'état explicite hide()/show(), indépendamment du fait que le
    # dialogue lui-même ne soit pas affiché en test (offscreen).
    assert not dialog.zip_warning.isHidden()
    assert dialog._zip == tmp_path / "pas_ue4ss.zip"


def test_setup_dialog_run_calls_ue4ss_setup(qapp, tmp_path, monkeypatch):
    """Le bouton « Lancer l'installation » appelle ue4ss_setup.run et rend le rapport.

    On remplace `run` pour ne toucher à aucun disque réel, et on vérifie qu'il reçoit
    bien l'install, le journal et le zip choisi.
    """
    inst = make_install(tmp_path / "lib", with_ue4ss=False)
    ctx = _ctx(tmp_path, [inst], inst)
    dialog = Ue4ssSetupDialog(ctx)
    dialog._zip = tmp_path / "ue4ss.zip"

    seen: dict = {}

    def fake_run(install, ledger, *, ue4ss_zip=None, probe=None):
        seen["install"] = install
        seen["ledger"] = ledger
        seen["zip"] = ue4ss_zip
        report = SetupReport(ok=False)
        report.add("Étape verte", True, "détail ok")
        report.add("Étape rouge", False, "Steam ouvert : correctif refusé.")
        report.message = "1/2 étape(s) réussie(s)."
        return report

    monkeypatch.setattr(ue4ss_setup, "run", fake_run)

    dialog.run_btn.click()

    assert seen["install"] is inst
    assert seen["ledger"] is ctx.ledger
    assert seen["zip"] == tmp_path / "ue4ss.zip"

    # Le rapport (refus compris) est affiché tel quel, pas caché.
    from PySide6.QtWidgets import QLabel
    shown = " | ".join(lbl.text() for lbl in dialog.report_holder.findChildren(QLabel))
    assert "Étape rouge" in shown
    assert "correctif refusé" in shown
