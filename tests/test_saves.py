"""Tests du gestionnaire de sauvegardes, sur les VRAIES sauvegardes du joueur.

Aucun `.sav` n'est fabriqué ici. Les 15 jeux de sauvegardes de `saves_drive/` sont
des états réels d'une partie réelle, ordonnés par progression : ils sont la seule
donnée capable de prouver que `summarize()` lit bien la progression, et pas un
nombre quelconque qui aurait l'air correct sur un fichier inventé.

Le poste de dev est sous Linux : `save_dir()` y vaut `None` par construction. Tous
les autres tests passent donc une racine explicite (`tmp_path`), ce qui est
exactement le mode de fonctionnement prévu pour être testable hors Windows.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fe_launcher.core import saves  # noqa: E402
from fe_launcher.core.ledger import Ledger  # noqa: E402

SAVES_DRIVE = Path("/home/pb/devDocker/antoine/saves_drive")
STEAM_ID = "76561199283983027"

# Chaîne strictement croissante en progression, vérifiée sur les compteurs réels.
# Les dossiers « CINDERVAULT Completed » et « WONDER  Completed » en sont exclus :
# ce sont des parties reprises depuis un autre point, leurs compteurs redescendent.
# Les y inclure ferait échouer un test qui a pourtant raison — la donnée n'est pas
# une progression continue, et le test doit dire la vérité sur la donnée.
PROGRESSION = [
    "CINDERVAULT + 1st QUARRY",
    "CINDERVAULT + 2nd QUARRY",
    "CINDERVAULT + QUARRY",
    "CINDERVAULT + QUARY + 1st YGDRAN",
    "CINDERVAULT + QUARY + 2nd YGDRAN",
    "CINDERVAULT + QUARY + YGDRAN",
    "CINDERVAULT + QUARY + YGDRAN + 1st WONDER",
    "CINDERVAULT + QUARY + YGDRAN + 2nd WONDER",
]

pytestmark = pytest.mark.skipif(
    not SAVES_DRIVE.is_dir(),
    reason="les sauvegardes de référence (saves_drive/) ne sont pas montées",
)


def real_save_dir(name: str) -> Path:
    return SAVES_DRIVE / name / STEAM_ID


@pytest.fixture
def game_saves(tmp_path: Path) -> Path:
    """Copie jetable d'un vrai dossier de sauvegardes, qu'on peut écraser sans risque.

    On ne teste JAMAIS une restauration directement dans saves_drive/ : ce sont les
    sauvegardes réelles du joueur, et un test qui les modifie serait exactement le
    genre de perte de données que ce module existe pour empêcher.
    """
    dest = tmp_path / "SaveGames" / STEAM_ID
    shutil.copytree(real_save_dir("CINDERVAULT + QUARRY"), dest)
    return dest


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "launcher-data")


def sha_of_dir(directory: Path) -> dict[str, bytes]:
    """Empreinte du contenu des `.sav` d'un dossier, pour comparer deux états."""
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*.sav"))}


# --- Emplacements et piège Steam Cloud -------------------------------------------

def test_save_dir_est_none_hors_windows():
    """Sur le poste de dev, il n'y a pas de %LOCALAPPDATA% : on ne devine pas un chemin."""
    assert sys.platform != "win32", "ce test décrit le comportement hors Windows"
    assert saves.save_dir() is None
    assert saves.slots_dir() is None


def test_slots_dir_est_un_sous_dossier_du_dossier_de_saves(tmp_path):
    """La planque doit être SOUS le dossier de saves : le pattern `*.sav` n'est pas récursif."""
    directory = saves.slots_dir(tmp_path)
    assert directory == tmp_path / saves.SLOTS_DIRNAME
    assert directory.parent == tmp_path


def test_les_fichiers_de_slot_ne_portent_pas_l_extension_sav(game_saves):
    """Un `.sav` de plus dans le dossier ferait dépasser ufs.maxnumfiles = 3."""
    slot = saves.snapshot("avant-boss", game_saves)

    assert list(slot.path.glob("*.sav")) == []
    assert {p.name for p in slot.files} == {
        "LastCheckpoint.savedata", "Achievements.savedata", "OptionsSlot.savedata"
    }
    # Et le dossier synchronisé par Steam contient toujours exactement 3 .sav.
    assert len(list(game_saves.glob("*.sav"))) == saves.UFS_MAX_NUM_FILES


def test_avertit_si_le_quota_de_fichiers_sav_est_depasse(game_saves):
    assert saves.steam_cloud_notice(game_saves) == []

    (game_saves / "LastCheckpoint - Copie.sav").write_bytes(b"GVAS")
    notices = saves.steam_cloud_notice(game_saves)

    assert len(notices) == 1
    assert "LastCheckpoint - Copie.sav" in notices[0]
    assert saves.SLOTS_DIRNAME in notices[0]


# --- summarize() ------------------------------------------------------------------

def test_summarize_lit_la_progression_d_une_vraie_sauvegarde():
    summary = saves.summarize(real_save_dir("ALL chests") / "LastCheckpoint.sav")

    assert summary.ok
    assert summary.error == ""
    assert summary.class_name == "/Script/UE_YGRO.SaveGameData"
    # Valeur de référence relevée sur le fichier réel.
    assert summary.counter("bUnlocked") == (153, 163)
    assert summary.counter("bLooted") == (11, 11)
    assert "déverrouillés 153/163" in summary.headline
    assert summary.saved_at.startswith("20")


@pytest.mark.parametrize("marker", ["bUnlocked", "bDialPlayed", "HasActivatedAtLeastOnce"])
def test_les_compteurs_croissent_le_long_de_la_chaine_de_progression(marker):
    """Le test central : les compteurs doivent suivre la progression réelle du joueur.

    Si `summarize()` comptait n'importe quoi (par exemple le nombre de propriétés
    présentes plutôt que le nombre de booléens vrais), cette suite ne serait pas
    monotone. C'est ce qui rend ces 8 sauvegardes irremplaçables comme donnée de test.
    """
    values = [
        saves.summarize(real_save_dir(name) / "LastCheckpoint.sav").counter(marker)[0]
        for name in PROGRESSION
    ]

    assert all(a < b for a, b in zip(values, values[1:])), (
        f"{marker} doit croître strictement le long de la chaîne : {values}"
    )


def test_summarize_ne_plante_pas_sur_un_fichier_corrompu(tmp_path):
    """Une sauvegarde corrompue est un cas de la vie réelle, pas un bug à faire remonter."""
    real = (real_save_dir("ALL chests") / "LastCheckpoint.sav").read_bytes()

    cases = {
        "tronque.sav": real[: len(real) // 3],          # coupure pendant l'écriture
        "vide.sav": b"",
        "pas_gvas.sav": b"\x00\x01\x02 ce n'est pas une sauvegarde",
        "entete_ok_corps_pourri.sav": real[:200] + bytes(5000),
    }
    for name, data in cases.items():
        path = tmp_path / name
        path.write_bytes(data)
        summary = saves.summarize(path)   # ne doit pas lever
        assert isinstance(summary, saves.SaveSummary)
        if not summary.ok:
            assert summary.error, f"{name} : un échec doit être expliqué"
            assert "illisible" in summary.headline

    absent = saves.summarize(tmp_path / "jamais-cree.sav")
    assert not absent.ok and absent.error == "fichier introuvable"


def test_summarize_degrade_proprement_sur_achievements():
    """Achievements.sav range tout dans un tableau opaque : aucun marqueur à compter.

    Le résumé doit le dire honnêtement plutôt que d'afficher des `0/0` trompeurs.
    """
    summary = saves.summarize(real_save_dir("ALL chests") / "Achievements.sav")

    assert summary.ok
    assert summary.counters == {}
    assert "aucun marqueur de progression" in summary.headline


# --- snapshot / restore / undo ----------------------------------------------------

def test_snapshot_copie_les_trois_fichiers_et_resume_la_progression(game_saves):
    slot = saves.snapshot("checkpoint quarry", game_saves, note="avant les vines")

    assert slot.complete
    assert slot.note == "avant les vines"
    assert slot.size > 1_000_000                      # LastCheckpoint fait ~1,9 Mo
    assert "déverrouillés 67/98" in slot.progress     # valeur réelle de ce dossier
    assert slot.path.name == "checkpoint-quarry"      # slug ASCII

    listed = saves.list_slots(game_saves)
    assert [s.name for s in listed] == ["checkpoint quarry"]
    assert listed[0].progress == slot.progress        # relu depuis slot.json


def test_snapshot_refuse_d_ecraser_un_slot_existant(game_saves):
    saves.snapshot("unique", game_saves)
    with pytest.raises(FileExistsError):
        saves.snapshot("unique", game_saves)


def test_snapshot_ne_touche_pas_aux_sauvegardes_du_jeu(game_saves):
    before = sha_of_dir(game_saves)
    saves.snapshot("lecture seule", game_saves)
    assert sha_of_dir(game_saves) == before


def test_restore_puis_undo_redonne_exactement_l_etat_de_depart(game_saves, ledger):
    """Le test qui justifie l'existence du Ledger dans ce module."""
    depart = sha_of_dir(game_saves)

    # Un slot pris sur un AUTRE état réel de la partie, bien plus avancé.
    slot_dir = saves.slots_dir(game_saves) / "avance"
    slot_dir.mkdir(parents=True)
    source = real_save_dir("ALL chests")
    for sav in saves.GAME_SAVE_FILES:
        shutil.copy2(source / sav, slot_dir / (Path(sav).stem + saves.SLOT_SUFFIX))
    slot = saves.list_slots(game_saves)[0]

    report = saves.restore(slot, game_saves, ledger=ledger, probe=lambda: False)

    assert report.ok
    assert sorted(report.restored) == sorted(saves.GAME_SAVE_FILES)
    # L'état du jeu est bien celui du slot, pas celui de départ.
    apres = sha_of_dir(game_saves)
    assert apres != depart
    assert apres["LastCheckpoint.sav"] == (source / "LastCheckpoint.sav").read_bytes()

    results = ledger.undo_group(report.group)
    assert all(r.ok for r in results), [r.message for r in results]
    assert sha_of_dir(game_saves) == depart


def test_restore_prend_toujours_un_instantane_de_l_etat_courant(game_saves, ledger):
    """Écraser une partie en cours sans filet est inacceptable — même sur demande."""
    depart = sha_of_dir(game_saves)
    slot = saves.snapshot("cible", game_saves)

    report = saves.restore(slot, game_saves, ledger=ledger, probe=lambda: False)

    assert report.backup is not None
    assert report.backup.name.startswith("avant-restauration-")
    assert report.backup.source == "auto-restauration"
    assert report.backup.complete
    # Le filet contient bien l'état d'AVANT, octet pour octet.
    for sav_name, data in depart.items():
        stored = report.backup.path / (Path(sav_name).stem + saves.SLOT_SUFFIX)
        assert stored.read_bytes() == data
    assert report.backup.name in report.message


def test_le_filet_automatique_est_lui_meme_restaurable(game_saves, ledger):
    """Boucle complète : je restaure par erreur, je remets l'état d'avant via le filet."""
    depart = sha_of_dir(game_saves)

    slot_dir = saves.slots_dir(game_saves) / "autre-etat"
    slot_dir.mkdir(parents=True)
    source = real_save_dir("CINDERVAULT + QUARY + YGDRAN")
    for sav in saves.GAME_SAVE_FILES:
        shutil.copy2(source / sav, slot_dir / (Path(sav).stem + saves.SLOT_SUFFIX))

    erreur = saves.restore(saves.list_slots(game_saves)[0], game_saves,
                           ledger=ledger, probe=lambda: False)
    assert sha_of_dir(game_saves) != depart

    retour = saves.restore(erreur.backup, game_saves, ledger=ledger, probe=lambda: False)
    assert retour.ok
    assert sha_of_dir(game_saves) == depart


def test_deux_restaurations_dans_la_meme_seconde_ne_se_marchent_pas_dessus(game_saves, ledger):
    """Régression : l'horodatage à la seconde faisait échouer la 2e restauration.

    C'est le scénario le plus courant après une erreur de manipulation — on restaure,
    on voit que ce n'est pas le bon slot, on restaure autre chose dans la foulée.
    """
    slot = saves.snapshot("cible", game_saves)

    premiers = [saves.restore(slot, game_saves, ledger=ledger, probe=lambda: False)
                for _ in range(3)]

    assert all(r.ok for r in premiers), [r.message for r in premiers]
    noms = {r.backup.name for r in premiers}
    assert len(noms) == 3, f"chaque filet doit avoir son propre nom : {noms}"


def test_restore_avertit_si_steam_tourne(game_saves, ledger):
    slot = saves.snapshot("cible", game_saves)

    report = saves.restore(slot, game_saves, ledger=ledger, probe=lambda: True)

    assert report.ok, "on avertit, on n'interdit pas"
    assert any("Steam Cloud" in w for w in report.warnings)
    assert any("quittez" in w.lower() for w in report.warnings)


def test_restore_avertit_aussi_quand_l_etat_de_steam_est_inconnu(game_saves, ledger):
    """`None` (cas du poste Linux, ou tasklist en échec) n'est pas un « non »."""
    slot = saves.snapshot("cible", game_saves)

    report = saves.restore(slot, game_saves, ledger=ledger, probe=lambda: None)

    assert report.ok
    assert any("Impossible de vérifier" in w for w in report.warnings)


def test_restore_d_un_slot_partiel_ne_supprime_pas_le_reste(game_saves, ledger):
    slot_dir = saves.slots_dir(game_saves) / "partiel"
    slot_dir.mkdir(parents=True)
    shutil.copy2(real_save_dir("ALL chests") / "LastCheckpoint.sav",
                 slot_dir / ("LastCheckpoint" + saves.SLOT_SUFFIX))
    slot = saves.list_slots(game_saves)[0]
    options_avant = (game_saves / "OptionsSlot.sav").read_bytes()

    report = saves.restore(slot, game_saves, ledger=ledger, probe=lambda: False)

    assert report.ok
    assert report.restored == ["LastCheckpoint.sav"]
    assert any("partiel" in w.lower() for w in report.warnings)
    assert (game_saves / "OptionsSlot.sav").read_bytes() == options_avant


def test_restore_d_un_slot_vide_echoue_sans_rien_toucher(game_saves, ledger):
    vide = saves.slots_dir(game_saves) / "vide"
    vide.mkdir(parents=True)
    slot = saves.list_slots(game_saves)[0]
    depart = sha_of_dir(game_saves)

    report = saves.restore(slot, game_saves, ledger=ledger, probe=lambda: False)

    assert not report.ok
    assert report.backup is None
    assert sha_of_dir(game_saves) == depart
    assert ledger.pending == []


# --- delete_slot ------------------------------------------------------------------

def test_delete_slot(game_saves):
    slot = saves.snapshot("a-jeter", game_saves)
    assert saves.delete_slot(slot) is True
    assert saves.list_slots(game_saves) == []
    assert saves.delete_slot(slot) is False


def test_delete_slot_ne_laisse_rien_au_journal(game_saves, ledger):
    slot = saves.snapshot("a-jeter", game_saves, ledger=ledger)
    saves.delete_slot(slot, ledger=ledger)

    # Plus rien à nettoyer : une désinstallation ne doit pas chercher un slot disparu.
    assert ledger.pending == []


def test_un_instantane_survit_a_la_desinstallation(game_saves, ledger):
    """Un instantané est une donnée du JOUEUR, pas une modification du jeu.

    Il ne doit donc JAMAIS être journalisé, même quand un journal est fourni : une
    entrée `CREATE_FILE` s'annule par une suppression, et la désinstallation effacerait
    les points de restauration — alors que son écran de confirmation promet noir sur
    blanc de ne pas toucher aux sauvegardes.
    """
    slot = saves.snapshot("avant-boss-final", game_saves, ledger=ledger)
    contenu = {p.name: p.read_bytes() for p in slot.files}
    assert contenu, "l'instantané doit contenir des fichiers"

    # Aucune entrée ne doit viser le slot.
    assert not [e for e in ledger.pending if slot.path.name in e.target]

    # Et une désinstallation complète le laisse intact, à l'octet près.
    ledger.undo()
    assert {p.name: p.read_bytes() for p in slot.files} == contenu
