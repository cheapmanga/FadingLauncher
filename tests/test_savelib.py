"""Bibliothèque de sauvegardes : chargement à filet unique, édition sûre."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fe_launcher.core import savelib
from fe_launcher.core.ledger import Ledger

pytestmark = pytest.mark.skipif(
    not savelib.bundled_saves(), reason="sauvegardes embarquées absentes")


@pytest.fixture
def save_root(tmp_path):
    root = tmp_path / "SaveGames" / "7656"
    root.mkdir(parents=True)
    for n in ("LastCheckpoint.sav", "Achievements.sav", "OptionsSlot.sav"):
        (root / n).write_bytes(b"COURANT " + n.encode())
    return root


def test_bibliotheque_liste_les_saves_embarquees():
    lib = savelib.bundled_saves()
    assert len(lib) >= 10
    assert all(s.complete for s in lib)
    assert any(s.progress for s in lib)  # au moins un résumé de progression lu


def test_chargement_met_de_cote_puis_remplace(save_root, tmp_path):
    led = Ledger(tmp_path / "led")
    save = savelib.bundled_saves()[0]
    r = savelib.apply_bundled(save, save_root=save_root, steam_id="7656",
                              ledger=led, probe=lambda: False)
    assert r.ok
    assert savelib.has_rollback(save_root, "7656")
    # l'état courant est bien dans le filet
    rb = save_root / savelib.ROLLBACK_DIRNAME / "LastCheckpoint.sav"
    assert rb.read_bytes().startswith(b"COURANT")


def test_filet_unique_le_second_chargement_detruit_le_premier(save_root, tmp_path):
    led = Ledger(tmp_path / "led")
    lib = savelib.bundled_saves()
    savelib.apply_bundled(lib[0], save_root=save_root, steam_id="7656",
                          ledger=led, probe=lambda: False)
    (save_root / "LastCheckpoint.sav").write_bytes(b"NOUVEL ETAT")
    savelib.apply_bundled(lib[1], save_root=save_root, steam_id="7656",
                          ledger=led, probe=lambda: False)
    rb = save_root / savelib.ROLLBACK_DIRNAME / "LastCheckpoint.sav"
    assert rb.read_bytes() == b"NOUVEL ETAT"  # l'ancien filet a été écrasé


def test_edition_sure_round_trip_exact(tmp_path):
    src = savelib.bundled_saves()[0].path / "LastCheckpoint.sav"
    work = tmp_path / "edit.sav"
    shutil.copy(src, work)
    orig = work.read_bytes()

    fields = savelib.editable_fields(work)
    assert len(fields) > 100
    b = next(f for f in fields if f.is_bool)
    assert savelib.write_fields(work, {b.index: not b.value})
    assert savelib.editable_fields(work)[b.index].value == (not b.value)
    # restaurer redonne l'octet exact
    savelib.write_fields(work, {b.index: b.value})
    assert work.read_bytes() == orig


def test_write_fields_refuse_un_index_hors_bornes(tmp_path):
    work = tmp_path / "e.sav"
    shutil.copy(savelib.bundled_saves()[0].path / "LastCheckpoint.sav", work)
    assert savelib.write_fields(work, {999999: 1}) is False
