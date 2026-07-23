"""Installation des mods embarqués, avec UEHelpers, réversible."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fe_launcher.core import modinstall, mods, paths
from fe_launcher.core.ledger import Ledger
from tools import make_fixture

pytestmark = pytest.mark.skipif(
    not modinstall.bundled_mods(), reason="mods embarqués absents")


@pytest.fixture
def layout(tmp_path):
    make_fixture.build_install(tmp_path / "steamapps" / "common", full=True, mods=[])
    inst = paths.inspect(tmp_path / "steamapps" / "common" / "Project Ygrό")
    shutil.rmtree(inst.ue4ss.shared_dir, ignore_errors=True)  # forcer le déploiement UEHelpers
    return inst.ue4ss


def test_bibliotheque_liste_les_mods():
    bm = modinstall.bundled_mods()
    assert len(bm) >= 15
    assert all(m.is_lua for m in bm)


def test_install_deploie_uehelpers_et_active(layout, tmp_path):
    led = Ledger(tmp_path / "led")
    r = modinstall.install(layout, "ue4ss-FEInfiniteCore", led)
    assert r.ok
    assert layout.uehelpers.is_file()  # UEHelpers déployé au passage
    loaded = {m.name: m for m in mods.load(layout)}
    assert "ue4ss-FEInfiniteCore" in loaded
    assert loaded["ue4ss-FEInfiniteCore"].state is mods.ModState.ENABLED


def test_install_all_puis_undo_ne_laisse_pas_de_fantome(layout, tmp_path):
    led = Ledger(tmp_path / "led")
    modinstall.install_all(layout, led)
    assert len(mods.load(layout)) >= 15
    led.undo()
    after = mods.load(layout)
    assert not [m for m in after if m.kind is mods.ModKind.UNKNOWN]
    assert len(after) == 0


def test_install_ne_reinstalle_pas_un_mod_present(layout, tmp_path):
    led = Ledger(tmp_path / "led")
    modinstall.install(layout, "ue4ss-FESkins", led)
    r = modinstall.install(layout, "ue4ss-FESkins", led)  # 2e fois
    assert r.ok and "ue4ss-FESkins" in r.skipped
