"""Tests de l'interface de la bibliothèque de sauvegardes et de l'éditeur.

Ce que ces tests protègent
--------------------------
La page Sauvegardes offre désormais deux fonctions à fort pouvoir de nuisance : charger
une sauvegarde (qui écrase la partie en cours) et éditer un `.sav` (qui touche une vraie
sauvegarde). Ni l'une ni l'autre ne doit pouvoir agir sans passer par le module cœur
testé — `savelib` — dont la sûreté (filet de rollback, round-trip exact, journalisation)
est la raison d'être. Ces tests vérifient donc le CÂBLAGE, pas la logique métier :

1. la bibliothèque liste bien les sauvegardes embarquées (`bundled_saves`) ;
2. « Charger » passe par `apply_bundled` ;
3. l'éditeur lit `editable_fields` d'un vrai `.sav`, en tire des cases à cocher, et
   « Enregistrer » passe par `write_fields` ;
4. le bandeau « Avancé » construit la vue brute à la demande.

Les fichiers de test sont les vraies sauvegardes embarquées du launcher
(`fe_launcher/resources/saves`) : elles sont toujours présentes dans le dépôt, et
prouvent que le regroupement et l'aller-retour tiennent sur le format réel, pas sur un
`.sav` fabriqué pour l'occasion. L'affichage est hors écran (`QT_QPA_PLATFORM=offscreen`).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QPushButton  # noqa: E402

from fe_launcher.core import savelib  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.pages import saves_page as saves_mod_ui  # noqa: E402
from fe_launcher.ui.pages.saves_page import (  # noqa: E402
    BoolGroupRow, SaveEditor, SavesPage, ScalarFieldRow,
)

RESOURCE_SAVE = Path(__file__).resolve().parents[1] / "fe_launcher" / "resources" / "saves" / "ALL chests"


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def save_root(tmp_path: Path) -> Path:
    """Un dossier de sauvegardes jetable, garni d'une vraie sauvegarde embarquée."""
    root = tmp_path / "saveroot"
    root.mkdir()
    for f in RESOURCE_SAVE.glob("*.sav"):
        shutil.copy2(f, root / f.name)
    return root


@pytest.fixture
def ctx(qapp: QApplication, tmp_path: Path) -> AppContext:
    return AppContext(data_dir=tmp_path / "launcher-data")


@pytest.fixture
def page(ctx: AppContext, save_root: Path) -> SavesPage:
    p = SavesPage(ctx)
    p.set_save_root(save_root)
    return p


def _yes(monkeypatch) -> None:
    """Fait répondre « Oui » à toute confirmation, et rend les rapports muets.

    On neutralise à la fois `exec` (boîtes construites à la main) ET les fabriques
    statiques `information`/`warning`/`question` : ces dernières ouvrent un dialogue
    modal au niveau C++ que patcher `exec` ne suffit pas à débloquer — sans ça, un test
    resterait figé sur un rapport de succès.
    """
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: QMessageBox.StandardButton.Yes)
    for name in ("information", "warning", "question", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))


# --- Tâche 1 : bibliothèque de sauvegardes prêtes --------------------------------

def test_library_lists_the_fifteen_bundled_saves(page: SavesPage):
    """La bibliothèque affiche les 15 sauvegardes livrées, chacune avec un « Charger »."""
    assert len(savelib.bundled_saves()) == 15
    loaders = [b for b in page.library_card.findChildren(QPushButton)
               if b.text() == "Charger"]
    assert len(loaders) == 15


def test_load_button_goes_through_apply_bundled(page: SavesPage, monkeypatch):
    """Cliquer « Charger » passe par `savelib.apply_bundled`, avec le bon dossier."""
    _yes(monkeypatch)
    calls: list = []

    def spy(save, **kwargs):
        calls.append((save, kwargs))
        return savelib.ApplyReport(True, "chargé", warnings=[])

    monkeypatch.setattr(saves_mod_ui.savelib_mod, "apply_bundled", spy)

    loader = next(b for b in page.library_card.findChildren(QPushButton)
                  if b.text() == "Charger")
    loader.click()

    assert len(calls) == 1
    save, kwargs = calls[0]
    assert isinstance(save, savelib.BundledSave)
    assert kwargs["save_root"] == page.save_root
    assert kwargs["ledger"] is page.ctx.ledger


def test_apply_bundled_really_swaps_files_and_offers_rollback(page: SavesPage):
    """Bout en bout, sans espion : charger une sauvegarde écrit les .sav et arme le
    filet « Annuler le dernier chargement »."""
    target = next(b for b in savelib.bundled_saves() if b.name == "WONDER  Completed")
    report = page.apply_bundled(target)
    assert report.ok
    assert savelib.has_rollback(save_root=page.save_root)
    # Après application, la page propose bien l'annulation.
    undo = [b for b in page.library_card.findChildren(QPushButton)
            if b.text() == "Annuler le dernier chargement"]
    assert len(undo) == 1


# --- Tâche 2 : éditeur graphique -------------------------------------------------

def test_editor_opens_default_checkpoint_and_shows_checkboxes(page: SavesPage):
    """L'éditeur ouvre le LastCheckpoint.sav courant et en tire des cases à cocher."""
    assert page.editor.path == page.save_root / "LastCheckpoint.sav"
    bool_groups = [r for r in page.editor._group_rows if isinstance(r, BoolGroupRow)]
    assert bool_groups, "des booléens agrégés doivent apparaître"
    assert all(isinstance(g.box, QCheckBox) for g in bool_groups)
    # Et au moins un scalaire éditable individuellement (ConnectedSource).
    assert any(isinstance(r, ScalarFieldRow) for r in page.editor._group_rows)


def test_editor_lists_editable_fields_of_a_real_save(ctx: AppContext):
    """`editable_fields` d'un vrai .sav alimente bien l'éditeur (rien à plat perdu)."""
    editor = SaveEditor(ctx)
    editor.set_path(RESOURCE_SAVE / "LastCheckpoint.sav")
    fields = savelib.editable_fields(RESOURCE_SAVE / "LastCheckpoint.sav")
    assert fields
    editor.advanced.set_expanded(True)
    assert len(editor._raw_rows) == len(fields)


def test_advanced_band_expands_lazily(ctx: AppContext):
    """La vue brute n'est construite qu'à l'ouverture du bandeau avancé."""
    editor = SaveEditor(ctx)
    editor.set_path(RESOURCE_SAVE / "LastCheckpoint.sav")
    assert editor._raw_rows == [], "rien ne doit être construit avant l'ouverture"
    editor.advanced.set_expanded(True)
    assert editor._raw_rows, "l'ouverture doit construire la vue brute"


def test_save_button_goes_through_write_fields(ctx: AppContext, monkeypatch):
    """« Enregistrer » rassemble les diffs et passe par `savelib.write_fields`."""
    _yes(monkeypatch)
    editor = SaveEditor(ctx)
    editor.set_path(RESOURCE_SAVE / "LastCheckpoint.sav")

    # On bascule un groupe partiellement activé : ça produit des diffs réels.
    group = next(g for g in editor._group_rows
                 if isinstance(g, BoolGroupRow) and 0 < sum(g._state.values()) < len(g._state))
    group._on_click()
    assert editor.collect_changes(), "le clic doit produire des modifications"

    seen: list = []

    def spy(path, changes, *, ledger=None):
        seen.append((Path(path), dict(changes), ledger))
        return True

    monkeypatch.setattr(saves_mod_ui.savelib_mod, "write_fields", spy)
    editor.save()

    assert len(seen) == 1
    path, changes, ledger = seen[0]
    assert path == RESOURCE_SAVE / "LastCheckpoint.sav"
    assert changes and all(isinstance(k, int) for k in changes)
    assert ledger is ctx.ledger


def test_save_really_writes_and_is_undoable(ctx: AppContext, save_root: Path):
    """Bout en bout : éditer un booléen change le fichier sur le disque, annulable."""
    target = save_root / "LastCheckpoint.sav"
    editor = SaveEditor(ctx)
    editor.set_path(target)

    before = {f.index: f.value for f in savelib.editable_fields(target)}
    group = next(g for g in editor._group_rows
                 if isinstance(g, BoolGroupRow) and 0 < sum(g._state.values()) < len(g._state))
    group._on_click()
    changes = editor.collect_changes()
    assert changes

    ok = savelib.write_fields(target, changes, ledger=ctx.ledger)
    assert ok
    after = {f.index: f.value for f in savelib.editable_fields(target)}
    assert any(after[i] != before[i] for i in changes), "le disque doit refléter l'édition"

    # Journalisé donc annulable : on retrouve l'état d'origine.
    results = ctx.ledger.undo()
    assert all(r.ok for r in results)
    restored = {f.index: f.value for f in savelib.editable_fields(target)}
    assert all(restored[i] == before[i] for i in changes)


def test_editor_without_save_root_is_still_usable(ctx: AppContext):
    """Sans dossier détecté, l'éditeur se construit sans planter et invite à choisir."""
    editor = SaveEditor(ctx)  # aucun chemin
    assert editor.path is None
    # Il ne lève pas et n'expose aucune ligne d'édition tant qu'aucun fichier n'est choisi.
    assert editor._group_rows == []
    assert editor._raw_rows == []
