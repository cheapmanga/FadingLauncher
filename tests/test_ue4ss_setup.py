"""Installation UE4SS + correctif grec, réversible."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from fe_launcher.core import paths, ue4ss_setup
from fe_launcher.core.ledger import Ledger

from tools import make_fixture


def _fake_ue4ss_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("dwmapi.dll", b"DLL")
        z.writestr("ue4ss/UE4SS-settings.ini", b"[General]\n")
        z.writestr("ue4ss/Mods/mods.txt", b"")
        z.writestr("../evil.txt", b"zip-slip")  # doit être rejeté
    return path


def _install_no_ue4ss(dest: Path):
    make_fixture.build_install(dest / "steamapps" / "common", full=True, with_ue4ss=False)
    make_fixture.build_steam_library(dest / "steamapps", installdir="Project Ygrό")
    return paths.inspect(dest / "steamapps" / "common" / "Project Ygrό")


def test_zip_invalide_rejete(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("random.txt", b"pas ue4ss")
    assert not ue4ss_setup.looks_like_ue4ss_zip(bad)


def test_setup_complet_installe_et_corrige_et_est_reversible(tmp_path):
    inst = _install_no_ue4ss(tmp_path)
    assert not inst.has_ue4ss and inst.non_ascii_path
    z = _fake_ue4ss_zip(tmp_path / "ue4ss.zip")
    led = Ledger(tmp_path / "led")

    rep = ue4ss_setup.run(inst, led, ue4ss_zip=z, probe=lambda: False)
    assert rep.ok
    # dossier renommé en ASCII + UE4SS présent
    ascii_root = tmp_path / "steamapps" / "common" / "Project Ygro"
    assert ascii_root.is_dir()
    inst2 = paths.inspect(ascii_root)
    assert inst2.has_ue4ss
    # zip-slip bloqué
    assert not any(tmp_path.rglob("evil.txt"))

    # tout se défait
    led.undo()
    assert (tmp_path / "steamapps" / "common" / "Project Ygrό").is_dir()


def test_refuse_si_steam_tourne(tmp_path):
    inst = _install_no_ue4ss(tmp_path)
    z = _fake_ue4ss_zip(tmp_path / "ue4ss.zip")
    led = Ledger(tmp_path / "led")
    rep = ue4ss_setup.run(inst, led, ue4ss_zip=z, probe=lambda: True)  # Steam ouvert
    # le correctif de chemin échoue (mais UE4SS a pu s'installer avant le renommage)
    fix_step = next(s for s in rep.steps if "non-ASCII" in s.label)
    assert not fix_step.ok


def test_pick_asset_prefere_le_build_standard():
    assets = [{"name": "zDEV-UE4SS_v3.0.1.zip"}, {"name": "UE4SS_v3.0.1.zip"},
              {"name": "zMapGenBP.zip"}]
    assert ue4ss_setup._pick_asset(assets)["name"] == "UE4SS_v3.0.1.zip"


def test_download_echoue_proprement_sans_reseau(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("pas de réseau")
    monkeypatch.setattr(ue4ss_setup.urllib.request, "urlopen", boom)
    r = ue4ss_setup.download_ue4ss(tmp_path)
    assert not r.ok and r.path is None


def test_run_telecharge_si_pas_de_zip(tmp_path, monkeypatch):
    inst = _install_no_ue4ss(tmp_path)
    (tmp_path / "dl").mkdir()
    z = _fake_ue4ss_zip(tmp_path / "dl" / "UE4SS_vX.zip")
    # simule un téléchargement réussi qui renvoie notre faux zip
    monkeypatch.setattr(ue4ss_setup, "download_ue4ss",
                        lambda dest, **k: ue4ss_setup.DownloadResult(True, z, "vX", "ok"))
    led = Ledger(tmp_path / "led")
    rep = ue4ss_setup.run(inst, led, probe=lambda: False)
    assert any("Téléchargement" in s.label for s in rep.steps)
    assert paths.inspect(tmp_path / "steamapps" / "common" / "Project Ygro").has_ue4ss
