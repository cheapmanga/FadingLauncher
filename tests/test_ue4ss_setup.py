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
        z.writestr("UE4SS-settings.ini", b"[General]\n")
        z.writestr("Mods/mods.txt", b"")
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


def test_pick_asset_prefere_le_build_zdev():
    # Le build zDEV contient les templates de layout memoire indispensables au fork
    # UE 5.6.1 du jeu ; le standard, plus leger, ne demarre pas dessus.
    assets = [{"name": "UE4SS_v3.0.1.zip"}, {"name": "zDEV-UE4SS_v3.0.1.zip"},
              {"name": "zMapGenBP.zip"}]
    assert ue4ss_setup._pick_asset(assets)["name"] == "zDEV-UE4SS_v3.0.1.zip"


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
    # bundle desactive pour forcer le repli telechargement
    monkeypatch.setattr(ue4ss_setup, "has_bundle", lambda: False)
    monkeypatch.setattr(ue4ss_setup, "download_ue4ss",
                        lambda dest, **k: ue4ss_setup.DownloadResult(True, z, "vX", "ok"))
    led = Ledger(tmp_path / "led")
    rep = ue4ss_setup.run(inst, led, probe=lambda: False)
    assert any("Téléchargement" in s.label for s in rep.steps)
    assert paths.inspect(tmp_path / "steamapps" / "common" / "Project Ygro").has_ue4ss


# --- Réinstallation par-dessus une install qui contient déjà des mods ---------------
#
# Régression vécue en jeu (log UE4SS à l'appui) : réinstaller UE4SS supprimait les
# FICHIERS sous `ue4ss/` mais laissait les DOSSIERS. Chaque mod devenait une coquille
# vide que `modinstall.is_installed` prenait encore pour installée — le bouton
# « Installer les mods fournis » répondait « déjà installés » et ne reposait rien —
# pendant qu'UE4SS, voyant un `enabled.txt` survivant, échouait sur
# « Main script 'main.lua' not found ».

def _installed_with_mods(tmp_path):
    from fe_launcher.core import modinstall
    inst = _install_no_ue4ss(tmp_path)
    led = Ledger(tmp_path / "led")
    assert ue4ss_setup.install_from_bundle(inst, led, ue4ss_setup.SetupReport(True))
    inst = paths.inspect(inst.root)
    modinstall.install_all(inst.ue4ss, led)
    return inst, led


@pytest.mark.skipif(not ue4ss_setup.has_bundle(), reason="bundle UE4SS absent")
def test_reinstall_conserve_les_mods_installes(tmp_path):
    from fe_launcher.core import modinstall
    inst, led = _installed_with_mods(tmp_path)
    avant = [m.name for m in modinstall.bundled_mods()
             if modinstall.is_installed(inst.ue4ss, m.name)]
    assert avant, "la fixture doit contenir des mods installés"

    assert ue4ss_setup.install_from_bundle(inst, led, ue4ss_setup.SetupReport(True),
                                           replace=True)

    for name in avant:
        d = inst.ue4ss.mods_dir / name
        assert (d / "Scripts" / "main.lua").is_file(), \
            f"{name} a perdu son script lors de la réinstallation d'UE4SS"
        assert modinstall.is_installed(inst.ue4ss, name)


@pytest.mark.skipif(not ue4ss_setup.has_bundle(), reason="bundle UE4SS absent")
def test_reinstall_ne_laisse_aucun_dossier_vide(tmp_path):
    inst, led = _installed_with_mods(tmp_path)
    ue4ss_setup.install_from_bundle(inst, led, ue4ss_setup.SetupReport(True), replace=True)

    vides = [str(d.relative_to(inst.ue4ss.root))
             for d in inst.ue4ss.root.rglob("*")
             if d.is_dir() and not any(d.iterdir())]
    assert not vides, f"dossiers vides laissés par la réinstallation : {vides}"


def test_dossier_vide_n_est_pas_un_mod_installe(tmp_path):
    """Une coquille vide ne doit jamais compter comme installée."""
    from fe_launcher.core import modinstall
    make_fixture.build_install(tmp_path / "common", full=True, with_ue4ss=True)
    layout = paths.inspect(tmp_path / "common" / "Project Ygrό").ue4ss
    assert layout is not None

    sain = layout.mods_dir / "ue4ss-FEMoonJump"
    (sain / "Scripts").mkdir(parents=True, exist_ok=True)
    (sain / "Scripts" / "main.lua").write_text("-- ok", encoding="utf-8")
    assert modinstall.is_installed(layout, "ue4ss-FEMoonJump")

    ghost = layout.mods_dir / "ue4ss-FECoreGiver"
    (ghost / "Scripts").mkdir(parents=True)
    (ghost / "enabled.txt").write_bytes(b"")
    assert not modinstall.is_installed(layout, "ue4ss-FECoreGiver"), \
        "un dossier sans script ne doit pas bloquer la réinstallation du mod"
