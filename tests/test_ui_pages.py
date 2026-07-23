"""Tests des pages d'interface, sur une vraie install fabriquée.

Ces tests tournent sans écran (`QT_QPA_PLATFORM=offscreen`, posé avant l'import de Qt).
Ils ne vérifient pas l'apparence — c'est le rôle des captures — mais les trois choses
qu'une page peut casser en silence :

1. **Elle se construit** sur une install réelle, avec les vrais mods et leurs conflits.
2. **Elle se rafraîchit** sans exploser quand l'état disque change sous elle.
3. **Cocher une case change bien l'état SUR LE DISQUE.** C'est le point critique : une
   case qui se coche à l'écran sans créer d'`enabled.txt` donne une interface qui ment,
   et l'utilisateur ne s'en aperçoit qu'au lancement du jeu.

On vérifie aussi qu'aucune écriture de réglage n'échappe au journal : c'est ce qui rend
la désinstallation capable de rendre les `.lua` dans leur état d'origine.
"""

from __future__ import annotations

import os

# Doit être posé AVANT le premier import de Qt, sinon Qt tente d'ouvrir un affichage.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fe_launcher.core import luaconf, moddocs  # noqa: E402
from fe_launcher.core.mods import ModState  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.pages import ModsPage, SettingsPage  # noqa: E402
from fe_launcher.ui.pages.mods_page import ModRow, display_name  # noqa: E402
from fe_launcher.ui.pages.settings_page import (  # noqa: E402
    CONFIRM_WORD, UninstallDialog,
)
from fe_launcher.ui.theme import stylesheet  # noqa: E402

from .conftest import make_install  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Une seule QApplication pour toute la session — Qt en interdit deux."""
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet())
    return app


@pytest.fixture
def ctx(qapp, tmp_path: Path) -> AppContext:
    """Contexte pointant une install jetable, avec ses données hors du dossier du jeu."""
    install = make_install(tmp_path / "lib")
    context = AppContext(data_dir=tmp_path / "appdata")
    context.installs = [install]
    context.select(install)
    return context


def _row(page: ModsPage, name: str) -> ModRow:
    rows = [page.list_layout.itemAt(i).widget()
            for i in range(page.list_layout.count())]
    match = [r for r in rows if isinstance(r, ModRow) and r.mod_name == name]
    assert match, f"{name} devrait être affiché dans la liste"
    return match[0]


# --- construction ---------------------------------------------------------------

def test_pages_build(ctx):
    """Les deux pages se construisent sur une install réelle."""
    mods_page = ModsPage(ctx)
    settings_page = SettingsPage(ctx)
    assert mods_page.title == "Mods"
    assert settings_page.title == "Paramètres"
    # La liste n'est pas vide : le fixture pose trois mods.
    assert ctx.visible_mods
    assert mods_page.list_layout.count() >= len(ctx.visible_mods)


def test_pages_survive_refresh(ctx):
    """Un refresh du contexte reconstruit les deux pages sans erreur."""
    mods_page = ModsPage(ctx)
    settings_page = SettingsPage(ctx)
    for _ in range(3):
        ctx.refresh()
    assert mods_page.list_layout.count() > 0
    assert settings_page.ledger_card.body.count() > 0


def test_page_builds_without_ue4ss(qapp, tmp_path):
    """Sans UE4SS, la page s'affiche et l'explique — elle ne plante pas."""
    install = make_install(tmp_path / "lib", with_ue4ss=False)
    context = AppContext(data_dir=tmp_path / "appdata")
    context.installs = [install]
    context.select(install)
    page = ModsPage(context)
    assert page.list_layout.count() >= 1


# --- activation : l'écran et le disque doivent dire la même chose ----------------

def test_uncheck_removes_marker_on_disk(ctx):
    """Décocher un mod retire son `enabled.txt` du disque, pas seulement de l'écran."""
    page = ModsPage(ctx)
    mod = next(m for m in ctx.visible_mods if m.state is ModState.ENABLED)
    marker = mod.path / "enabled.txt"
    assert marker.is_file(), "le fixture livre les mods activés"

    _row(page, mod.name).box.setChecked(False)

    assert not marker.is_file(), "décocher doit retirer le marqueur du disque"
    reloaded = next(m for m in ctx.mods if m.name == mod.name)
    assert reloaded.state is ModState.DISABLED
    assert not _row(page, mod.name).box.isChecked()


def test_recheck_restores_marker_on_disk(ctx):
    """Recocher recrée le marqueur, et l'état relu vaut de nouveau ENABLED."""
    page = ModsPage(ctx)
    mod = next(m for m in ctx.visible_mods if m.state is ModState.ENABLED)
    marker = mod.path / "enabled.txt"

    _row(page, mod.name).box.setChecked(False)
    assert not marker.is_file()

    _row(page, mod.name).box.setChecked(True)
    assert marker.is_file(), "recocher doit recréer le marqueur"
    assert next(m for m in ctx.mods if m.name == mod.name).state is ModState.ENABLED


def test_selection_survives_a_toggle(ctx):
    """Cocher un mod ne renvoie pas le panneau de détail sur un autre mod."""
    page = ModsPage(ctx)
    target = ctx.visible_mods[-1].name
    page._on_pick(target)
    assert page._selected == target
    _row(page, target).box.setChecked(False)
    assert page._selected == target


# --- réglages : jamais d'écriture sans journal -----------------------------------

def test_setting_change_writes_and_logs(ctx):
    """Modifier un réglage écrit le .lua ET laisse une entrée annulable dans le journal."""
    page = ModsPage(ctx)
    mod = next(m for m in ctx.visible_mods if m.script is not None)
    before = luaconf.read(mod.script, "VOID_DELAY_MS")
    assert before is not None and before.value == 1200

    page._on_setting(mod, "VOID_DELAY_MS", 450)

    after = luaconf.read(mod.script, "VOID_DELAY_MS")
    assert after.value == 450, "la valeur doit être écrite dans le fichier"

    pending = ctx.ledger.pending
    assert len(pending) == 1, "toute écriture doit être journalisée"
    assert pending[0].payload == {"name": "VOID_DELAY_MS", "old": 1200, "new": 450}

    # Et surtout : le journal doit savoir revenir en arrière.
    results = ctx.ledger.undo()
    assert all(r.ok for r in results)
    assert luaconf.read(mod.script, "VOID_DELAY_MS").value == 1200


def test_setting_unchanged_is_not_logged(ctx):
    """Réécrire la même valeur ne pollue pas le journal d'entrées vides."""
    page = ModsPage(ctx)
    mod = next(m for m in ctx.visible_mods if m.script is not None)
    page._on_setting(mod, "VOID_DELAY_MS", 1200)
    assert ctx.ledger.pending == []


def test_comment_is_preserved_after_a_setting_change(ctx):
    """L'écriture reste chirurgicale : le commentaire du mod survit à un réglage."""
    page = ModsPage(ctx)
    mod = next(m for m in ctx.visible_mods if m.script is not None)
    page._on_setting(mod, "CORE_TYPE", "fire")
    text = mod.script.read_text(encoding="utf-8")
    assert 'local CORE_TYPE     = "fire"' in text
    assert "water|waste|fire|glitch" in text


# --- filtre et mods restreints ---------------------------------------------------

def test_search_filters_the_list(ctx):
    """Le champ de recherche réduit la liste sans toucher à l'inventaire réel."""
    page = ModsPage(ctx)
    total = len(ctx.visible_mods)
    page.search.setText("MoonJump")
    shown = [page.list_layout.itemAt(i).widget()
             for i in range(page.list_layout.count())]
    shown = [w for w in shown if isinstance(w, ModRow)]
    assert len(shown) == 1 and shown[0].mod_name.endswith("FEMoonJump")

    page.search.setText("")
    assert len(ctx.visible_mods) == total


def test_restricted_mod_hidden_until_developer_mode(qapp, tmp_path):
    """FEDevMenu reste invisible tant que le mode développeur n'est pas coché."""
    restricted = sorted(moddocs.RESTRICTED)[0]
    install = make_install(tmp_path / "lib",
                           mod_names=["ue4ss-FEMoonJump", restricted])
    context = AppContext(data_dir=tmp_path / "appdata")
    context.installs = [install]
    context.select(install)

    page = ModsPage(context)
    settings_page = SettingsPage(context)
    assert restricted in {m.name for m in context.mods}
    assert restricted not in {m.name for m in context.visible_mods}
    with pytest.raises(AssertionError):
        _row(page, restricted)

    settings_page.developer_box.setChecked(True)

    assert context.settings.developer_mode is True
    assert restricted in {m.name for m in context.visible_mods}
    assert _row(page, restricted).mod_name == restricted


def test_display_name_drops_the_prefix(ctx):
    mod = ctx.visible_mods[0]
    assert display_name(mod) == mod.name.removeprefix("ue4ss-")


# --- paramètres ------------------------------------------------------------------

def test_settings_are_persisted(ctx, tmp_path):
    """Cocher une préférence l'écrit sur le disque, pas seulement en mémoire."""
    page = SettingsPage(ctx)
    page.advanced_box.setChecked(True)
    page.confirm_box.setChecked(False)

    from fe_launcher.core.settings import Settings
    reloaded = Settings.load(ctx.data_dir)
    assert reloaded.advanced_settings is True
    assert reloaded.confirm_profile_apply is False


def _ledger_text(page: SettingsPage) -> str:
    from PySide6.QtWidgets import QLabel
    return " | ".join(lbl.text() for lbl in page.ledger_card.findChildren(QLabel))


def test_ledger_section_lists_pending_entries(ctx):
    """Le journal affiché suit ce que le journal contient, libellé compris."""
    page = SettingsPage(ctx)
    assert "n'a encore rien modifié" in _ledger_text(page)

    mod = next(m for m in ctx.visible_mods if m.script is not None)
    ModsPage(ctx)._on_setting(mod, "VOID_DELAY_MS", 900)
    page.refresh()

    shown = _ledger_text(page)
    assert len(ctx.ledger.pending) == 1
    assert "VOID_DELAY_MS" in shown
    assert "1200" in shown and "900" in shown
    assert str(mod.script) in shown, "l'utilisateur doit voir QUEL fichier a bougé"
    assert "n'a encore rien modifié" not in shown


# --- désinstallation -------------------------------------------------------------

def test_uninstall_dialog_requires_the_exact_word(ctx):
    """Le bouton de validation ne s'arme que sur le mot exact."""
    from fe_launcher.core.settings import Settings
    dialog = UninstallDialog(ctx.ledger.uninstall_plan(), Settings.path(ctx.data_dir))
    assert not dialog.confirm.isEnabled()

    for wrong in ("", "supprimer", "SUPPRIME", "oui"):
        dialog.field.setText(wrong)
        assert not dialog.confirm.isEnabled(), f"« {wrong} » ne doit pas armer le bouton"

    dialog.field.setText(CONFIRM_WORD)
    assert dialog.confirm.isEnabled()


def test_uninstall_plan_lists_every_pending_change(ctx):
    """Le plan présenté couvre toutes les modifications en vigueur, sans résumé."""
    mod = next(m for m in ctx.visible_mods if m.script is not None)
    page = ModsPage(ctx)
    page._on_setting(mod, "VOID_DELAY_MS", 700)
    page._on_setting(mod, "CORE_TYPE", "waste")

    plan = ctx.ledger.uninstall_plan()
    assert len(plan) == len(ctx.ledger.pending) == 2
    assert all(text for _, text in plan)


def test_failed_undo_keeps_the_backups(ctx, monkeypatch):
    """Un échec d'annulation interdit la purge : sinon on perd de quoi réessayer.

    C'est la règle de sécurité centrale de la désinstallation. On la vérifie au niveau
    du journal, sans passer par la boîte de dialogue qui, elle, est bloquante.
    """
    mod = next(m for m in ctx.visible_mods if m.script is not None)
    ModsPage(ctx)._on_setting(mod, "VOID_DELAY_MS", 300)

    # Le fichier disparaît : l'annulation ne peut plus aboutir.
    mod.script.unlink()
    results = ctx.ledger.undo()
    assert any(not r.ok for r in results)
    # La page n'appelle purge_self() que si tout est passé : le journal reste debout.
    assert ctx.ledger.pending, "les entrées non annulées doivent rester au journal"
    assert ctx.ledger.path.is_file()
