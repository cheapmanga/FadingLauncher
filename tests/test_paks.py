"""Tests de la gestion des paks, sur de vraies arborescences temporaires.

L'accent est mis sur les cas destructeurs : triplet incomplet, pak de base protégé,
et surtout le rollback quand un renommage échoue au milieu des trois — c'est le seul
scénario qui puisse laisser l'installation dans un état qui empêche le jeu de démarrer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fe_launcher.core import paks
from tests.conftest import write_triplet


def test_scan_regroupe_le_triplet(tmp_path: Path) -> None:
    write_triplet(tmp_path, "AA_Alien_P", sizes=(10, 20, 30))
    (tmp_path / "notes.txt").write_text("bruit", encoding="utf-8")

    found = paks.scan(tmp_path)

    assert [p.name for p in found] == ["AA_Alien_P"]
    ps = found[0]
    assert ps.complete and ps.enabled
    assert ps.size == 60
    assert len(ps.parts) == 3
    assert ps.patch_suffix is True  # information seulement, cf. docstring du module


def test_scan_dossier_absent(tmp_path: Path) -> None:
    assert paks.scan(tmp_path / "nexistepas") == []


def test_triplet_incomplet_est_signale(tmp_path: Path) -> None:
    write_triplet(tmp_path, "Partiel", parts=(".pak", ".utoc"))

    ps = paks.scan(tmp_path)[0]

    assert not ps.complete
    assert ps.missing == [".ucas"]
    assert "incomplet" in ps.status


def test_activation_desactivation_des_trois_fichiers(tmp_path: Path) -> None:
    write_triplet(tmp_path, "MonMod")
    ps = paks.scan(tmp_path)[0]

    off = paks.set_enabled(ps, False)
    assert off.enabled is False
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "MonMod.pak.disabled", "MonMod.ucas.disabled", "MonMod.utoc.disabled",
    ]

    on = paks.set_enabled(off, True)
    assert on.enabled is True and on.complete
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "MonMod.pak", "MonMod.ucas", "MonMod.utoc",
    ]


def test_rollback_si_un_renommage_echoue(tmp_path: Path, monkeypatch) -> None:
    """Le 3e renommage échoue (fichier verrouillé par le jeu) : les 2 premiers doivent
    être annulés. Un triplet à moitié désactivé empêcherait le jeu de démarrer."""
    write_triplet(tmp_path, "MonMod")
    ps = paks.scan(tmp_path)[0]

    vrai_rename = Path.rename
    appels = {"n": 0}

    def rename_qui_lache(self: Path, target):
        appels["n"] += 1
        if appels["n"] == 3:
            raise OSError(32, "fichier utilisé par un autre processus")
        return vrai_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename_qui_lache)

    with pytest.raises(paks.PakError, match="rien n'a été modifié"):
        paks.set_enabled(ps, False)

    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "MonMod.pak", "MonMod.ucas", "MonMod.utoc",
    ]
    apres = paks.scan(tmp_path)[0]
    assert apres.enabled and apres.complete and not apres.half_disabled


def test_activer_un_triplet_incomplet_est_refuse(tmp_path: Path) -> None:
    write_triplet(tmp_path, "Partiel", parts=(".pak", ".utoc"), disabled=True)
    ps = paks.scan(tmp_path)[0]

    with pytest.raises(paks.IncompletePak):
        paks.set_enabled(ps, True)

    # ... mais le DÉSACTIVER reste permis : c'est une opération de réparation.
    write_triplet(tmp_path, "Partiel2", parts=(".pak", ".utoc"))
    ps2 = paks.find(paks.scan(tmp_path), "Partiel2")
    assert ps2 is not None
    assert paks.set_enabled(ps2, False).enabled is False


def test_pak_de_base_protege(tmp_path: Path) -> None:
    write_triplet(tmp_path, "UE_YGRO-Windows")
    ps = paks.scan(tmp_path)[0]
    assert ps.is_base

    with pytest.raises(paks.ProtectedPak):
        paks.set_enabled(ps, False)
    with pytest.raises(paks.ProtectedPak):
        paks.uninstall(ps)

    assert len(list(tmp_path.iterdir())) == 3  # rien n'a bougé


def test_installed_voit_les_paks_du_jeu(install) -> None:
    noms = [p.name for p in paks.installed(install)]
    assert "UE_YGRO-Windows" in noms


def test_install_pak_depuis_la_bibliotheque(tmp_path: Path, install) -> None:
    library = tmp_path / "bibliotheque"
    write_triplet(library, "AA_Alien_P", sizes=(11, 22, 33))
    source = paks.available(library)[0]

    installed = paks.install_pak(source, install)

    assert installed.complete and installed.enabled
    assert installed.size == 66
    assert (install.paks_dir / "AA_Alien_P.ucas").is_file()
    # Aucun fichier temporaire ne doit subsister.
    assert not list(install.paks_dir.glob("*.part"))

    # Réinstaller sans overwrite doit refuser.
    with pytest.raises(paks.PakError, match="déjà installé"):
        paks.install_pak(source, install)

    # Avec overwrite, ça passe.
    assert paks.install_pak(source, install, overwrite=True).complete


def test_install_pak_incomplet_refuse(tmp_path: Path, install) -> None:
    library = tmp_path / "bibliotheque"
    write_triplet(library, "Casse", parts=(".pak",))
    source = paks.available(library)[0]

    with pytest.raises(paks.IncompletePak):
        paks.install_pak(source, install)
    assert not list(install.paks_dir.glob("Casse*"))


def test_uninstall_supprime_les_trois(tmp_path: Path) -> None:
    write_triplet(tmp_path, "AJeter")
    ps = paks.scan(tmp_path)[0]

    paks.uninstall(ps)

    assert list(tmp_path.iterdir()) == []


def test_duplicates_repere_le_meme_contenu_sous_deux_noms(tmp_path: Path) -> None:
    """Cas réel : AA_Alien_P.* et pakchunk10-Windows.* sont le même contenu."""
    write_triplet(tmp_path, "AA_Alien_P", sizes=(10, 20, 30))
    write_triplet(tmp_path, "pakchunk10-Windows", sizes=(10, 20, 30))
    write_triplet(tmp_path, "Autre", sizes=(1, 2, 3))

    groupes = paks.duplicates(paks.scan(tmp_path))

    assert len(groupes) == 1
    assert {p.name for p in groupes[0]} == {"AA_Alien_P", "pakchunk10-Windows"}
