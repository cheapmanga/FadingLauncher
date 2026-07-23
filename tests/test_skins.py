"""Sélection de skin : catalogue, pilotage du mod, réversibilité."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fe_launcher.core import mods, portraits, skins
from fe_launcher.core.ledger import Ledger

REAL_FESKINS = Path("/home/pb/devDocker/antoine/mods/ue4ss-FESkins")


import os as _os
pytestmark = __import__("pytest").mark.skipif(not _os.path.isdir('/home/pb/devDocker/antoine/mods/ue4ss-FESkins'), reason="données locales absentes")

@pytest.fixture
def feskins(tmp_path):
    """Une install avec le VRAI mod FESkins (celui modifié pour le boot)."""
    from tests.conftest import make_install


    inst = make_install(tmp_path / "lib", full=True, mod_names=[])
    dst = inst.ue4ss.mods_dir / "ue4ss-FESkins"
    shutil.copytree(REAL_FESKINS, dst)
    mod = next(m for m in mods.load(inst.ue4ss) if m.name == "ue4ss-FESkins")
    return mod


def test_catalogue_aligne_sur_les_alias_du_mod(feskins):
    """Les alias du catalogue existent dans la table MESHES du mod (via ses commandes)."""
    text = feskins.script.read_text(encoding="utf-8")
    # chaque alias non-"one" doit apparaître comme clé dans le fichier du mod
    for entry in skins.CHARACTERS:
        if entry.alias in ("one", "hero"):
            continue
        assert f'"{entry.alias}"' in text, f"alias absent du mod : {entry.alias}"


def test_boot_constants_lisibles(feskins):
    st = skins.read_state(feskins)
    assert st is not None
    assert st == skins.SkinState()  # état neutre par défaut


def test_apply_puis_undo_revient_a_lorigine(feskins, tmp_path):
    led = Ledger(tmp_path / "led")
    origine = feskins.script.read_bytes()

    r = skins.apply(feskins, skins.SkinState(mesh="kheleb", hide_stick=True,
                                             outline="off"), led)
    assert r.ok and r.changed
    st = skins.read_state(feskins)
    assert st.mesh == "kheleb" and st.hide_stick and st.outline == "off"

    led.undo()
    assert feskins.script.read_bytes() == origine, "undo ne restaure pas le fichier"
    assert skins.read_state(feskins) == skins.SkinState()


def test_apply_sans_changement_ne_journalise_rien(feskins, tmp_path):
    led = Ledger(tmp_path / "led")
    r = skins.apply(feskins, skins.SkinState(), led)  # déjà l'état par défaut
    assert r.ok and not r.changed
    assert led.pending == []


def test_deform_note_seulement_hors_squelette_de_one():
    assert skins.deform_note("one") == ""
    assert skins.deform_note("kheleb") != ""


def test_portraits_couvrent_les_personnages_principaux():
    for alias in ("one", "bob", "rahne", "kheleb"):
        assert portraits.resolve(alias).found, f"portrait manquant : {alias}"
