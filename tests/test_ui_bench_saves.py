"""Tests des pages Banc d'essai et Sauvegardes.

Ce que ces tests cherchent à prouver
------------------------------------
Pour le banc d'essai, l'important n'est pas que la page s'affiche : c'est qu'elle ne
mente pas. Le scénario central reproduit le piège que le module de mesure existe pour
empêcher — 3 réussites sur 15 contre 6 sur 15 — et vérifie que la page affiche « aucun
écart significatif » plutôt que de désigner un gagnant. Une page qui compilerait sans
erreur mais afficherait « 500 ms est le meilleur palier » serait un échec complet, et
c'est précisément ce qu'un test de fumée ne verrait pas.

Pour les sauvegardes, les tests tournent sur les VRAIS fichiers de `saves_drive/`,
copiés dans un dossier jetable. Fabriquer un faux `.sav` prouverait seulement qu'on sait
copier des octets qu'on a écrits soi-même ; les vraies sauvegardes prouvent que le
résumé de progression et l'aller-retour instantané → restauration tiennent sur le
format réel.

L'affichage se fait hors écran (`QT_QPA_PLATFORM=offscreen`) : le poste de dev n'a pas
de serveur graphique, et ces tests doivent tourner partout.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest



os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget  # noqa: E402

from tests.conftest import make_install  # noqa: E402
from fe_launcher.core import luaconf, savelib, saves as saves_mod  # noqa: E402
from fe_launcher.core.bench import Outcome  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.pages.bench_page import BenchPage, parse_steps  # noqa: E402
from fe_launcher.ui.pages.saves_page import SavesPage  # noqa: E402

SAVES_DRIVE = Path("/home/pb/devDocker/antoine/saves_drive")
STEAM_ID = "76561199283983027"


import os as _os
pytestmark = __import__("pytest").mark.skipif(not _os.path.isdir('/home/pb/devDocker/antoine/saves_drive'), reason="données locales absentes")

@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ctx(qapp: QApplication, tmp_path: Path) -> AppContext:
    """Contexte complet : install jetable avec ses mods, données du launcher isolées."""
    context = AppContext(data_dir=tmp_path / "launcher-data")
    context.select(make_install(tmp_path / "lib"))
    return context


@pytest.fixture
def bench(ctx: AppContext) -> BenchPage:
    return BenchPage(ctx)


def cell(page: BenchPage, row: int, col: int) -> str:
    item = page.table.item(row, col)
    return "" if item is None else item.text()


def press(page: BenchPage, key: Qt.Key, modifier=Qt.KeyboardModifier.NoModifier) -> None:
    QApplication.sendEvent(page, QKeyEvent(QKeyEvent.Type.KeyPress, key, modifier))


# --- Banc d'essai : saisie des paliers -------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("150/300/500/800", [150, 300, 500, 800]),
    ("150 300  500", [150, 300, 500]),
    ("150, 300; 500", [150, 300, 500]),
    ("800/150/300", [150, 300, 800]),      # trié
    ("300/300/150", [150, 300]),           # dédoublonné
    ("", []),
    ("abc", []),
])
def test_parse_steps_tolere_les_separateurs(text, expected):
    assert parse_steps(text) == expected


def test_page_demarre_avec_des_paliers_par_defaut(bench: BenchPage):
    assert [b.value for b in bench.campaign.buckets] == [150, 300, 500, 800]
    assert bench.table.rowCount() == 4
    assert bench.current == 150


def test_palier_vide_retirable_mais_palier_mesure_conserve(bench: BenchPage):
    bench.campaign.record(300, Outcome.HIT)
    bench.steps_edit.setText("150")
    bench._sync_from_fields()
    # 300 porte un essai : il survit. 500 et 800 sont vides : ils disparaissent.
    assert [b.value for b in bench.campaign.buckets] == [150, 300]


# --- Banc d'essai : le tableau et le verdict suivent la saisie --------------------

def test_saisie_met_a_jour_le_tableau(bench: BenchPage):
    assert cell(bench, 0, 3) == "0"          # colonne n
    bench.record(Outcome.HIT)
    bench.record(Outcome.MISS)
    bench.record(Outcome.MISS)
    assert cell(bench, 0, 2) == "1"          # HIT
    assert cell(bench, 0, 3) == "3"          # n
    assert cell(bench, 0, 4) == "33%"        # taux
    assert cell(bench, 0, 5).startswith("[")  # intervalle de confiance affiché


def test_essai_a_jeter_ne_compte_pas_au_denominateur(bench: BenchPage):
    bench.record(Outcome.HIT)
    bench.record(Outcome.VOID)
    assert cell(bench, 0, 3) == "1"          # n : l'essai jeté n'y figure pas
    assert cell(bench, 0, 6) == "1"          # colonne Rejetés
    assert bench.campaign.bucket(150).n == 1


def test_annulation_du_dernier_essai(bench: BenchPage):
    bench.record(Outcome.HIT)
    bench.record(Outcome.MISS)
    bench.undo_last()
    assert cell(bench, 0, 3) == "1"
    assert cell(bench, 0, 2) == "1"
    # Annuler dans le vide ne doit pas lever : sur une série de 20, ça arrive.
    bench.undo_last()
    bench.undo_last()
    assert cell(bench, 0, 3) == "0"


def test_raccourcis_clavier(bench: BenchPage):
    press(bench, Qt.Key.Key_H)
    press(bench, Qt.Key.Key_M)
    press(bench, Qt.Key.Key_J)
    bucket = bench.campaign.bucket(150)
    assert (bucket.hits, bucket.n, bucket.voided) == (1, 2, 1)
    press(bench, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert bench.campaign.bucket(150).voided == 0


def test_le_palier_courant_est_marque_dans_le_tableau(bench: BenchPage):
    assert cell(bench, 0, 0).startswith("▶")
    assert not cell(bench, 1, 0).startswith("▶")
    bench.step_combo.setCurrentIndex(1)
    assert bench.current == 300
    assert cell(bench, 1, 0).startswith("▶")


def test_verdict_refuse_de_designer_un_gagnant_sur_du_bruit(bench: BenchPage):
    """Le scénario qui justifie toute la page : 3/15 contre 6/15, p ≈ 0,43."""
    for i in range(15):
        bench.campaign.record(300, Outcome.HIT if i < 3 else Outcome.MISS)
        bench.campaign.record(500, Outcome.HIT if i < 6 else Outcome.MISS)
    bench.refresh()

    verdict = bench.verdict_label.text()
    assert "Aucun écart significatif" in verdict
    assert "plus d'essais" in verdict
    # Le taux le plus élevé n'est mis en avant nulle part ailleurs que dans ce
    # verdict, qui le relativise lui-même.
    assert bench.campaign.verdict() == verdict


def test_verdict_conclut_quand_l_ecart_est_reel(bench: BenchPage):
    for i in range(20):
        bench.campaign.record(300, Outcome.MISS)
        bench.campaign.record(500, Outcome.HIT if i < 18 else Outcome.MISS)
    bench.refresh()
    verdict = bench.verdict_label.text()
    assert "significativement" in verdict
    assert "500" in verdict


def test_prochain_palier_conseille_equilibre_les_effectifs(bench: BenchPage):
    for _ in range(5):
        bench.campaign.record(150, Outcome.MISS)
    bench.refresh()
    assert "300" in bench.suggest_label.text()


# --- Banc d'essai : framerate ----------------------------------------------------

def test_avertissement_framerate_non_verrouille(bench: BenchPage):
    assert bench.campaign.fps_lock == 0
    assert "non comparables entre sessions" in bench.fps_notice.text()
    assert "frames" not in cell(bench, 0, 1)
    assert cell(bench, 0, 1) == "—"          # pas de conversion possible sans fps


def test_framerate_verrouille_convertit_en_frames(bench: BenchPage):
    bench.fps_combo.setCurrentIndex(
        next(i for i in range(bench.fps_combo.count())
             if bench.fps_combo.itemData(i) == 60.0))
    assert bench.campaign.fps_lock == 60.0
    assert "non comparables" not in bench.fps_notice.text()
    assert cell(bench, 0, 1) == "9.0"        # 150 ms à 60 fps = 9 frames


# --- Banc d'essai : pilotage du mod ----------------------------------------------

def script_of(ctx: AppContext, name: str) -> Path:
    mod = next(m for m in ctx.mods if m.name == name)
    assert mod.script is not None
    return mod.script


def test_changer_de_palier_ecrit_dans_le_mod_et_journalise(bench: BenchPage, ctx: AppContext):
    script = script_of(ctx, "ue4ss-FEInfiniteCore")
    assert luaconf.read(script, "VOID_DELAY_MS") is not None

    bench.step_combo.setCurrentIndex(2)       # 500 ms
    assert luaconf.read(script, "VOID_DELAY_MS").value == 500

    entries = [e for e in ctx.ledger.pending if e.payload.get("name") == "VOID_DELAY_MS"]
    assert entries, "l'écriture doit être journalisée pour rester annulable"
    assert entries[-1].payload["new"] == 500


def test_page_utilisable_sans_le_mod(qapp: QApplication, tmp_path: Path):
    """Sans FEInfiniteCore, la saisie manuelle doit rester possible — sans plantage."""
    context = AppContext(data_dir=tmp_path / "data")
    context.select(make_install(tmp_path / "lib2", mod_names=["ue4ss-FEMoonJump"]))
    page = BenchPage(context)

    assert "SAISIE MANUELLE" in page.mod_badge.text()
    assert not page.autopush.isEnabled()
    assert page.hit_btn.isEnabled()
    page.record(Outcome.HIT)
    assert cell(page, 0, 2) == "1"


# --- Banc d'essai : persistance et export ----------------------------------------

def test_enregistrer_puis_recharger_une_campagne(bench: BenchPage, ctx: AppContext):
    bench.name_edit.setText("Essai Quarry")
    bench.setup_edit.setText("Quarry, Human One")
    bench._sync_from_fields()
    bench.record(Outcome.HIT)
    bench.record(Outcome.MISS)
    bench._save()

    path = bench.campaigns_dir / "Essai-Quarry.json"
    assert path.is_file()

    other = BenchPage(ctx)
    assert other.load_file(path)
    assert other.campaign.name == "Essai Quarry"
    assert other.setup_edit.text() == "Quarry, Human One"
    assert other.campaign.bucket(150).n == 2
    assert cell(other, 0, 2) == "1"


def test_copier_la_grille(bench: BenchPage):
    bench.record(Outcome.HIT)
    bench._copy_grid()
    text = QApplication.clipboard().text()
    assert "CAMPAGNE" in text
    assert "IC 95%" in text
    assert bench.campaign.verdict() in text


# --- Sauvegardes -----------------------------------------------------------------

needs_saves = pytest.mark.skipif(
    not SAVES_DRIVE.is_dir(),
    reason="les sauvegardes de référence (saves_drive/) ne sont pas montées")


@pytest.fixture
def game_saves(tmp_path: Path) -> Path:
    """Copie jetable d'un vrai dossier de sauvegardes.

    On ne travaille JAMAIS directement dans saves_drive/ : ce sont les sauvegardes
    réelles du joueur, et un test qui les écrase serait exactement la perte de données
    que ce module existe pour empêcher.
    """
    dest = tmp_path / "SaveGames" / STEAM_ID
    shutil.copytree(SAVES_DRIVE / "CINDERVAULT + QUARRY" / STEAM_ID, dest)
    return dest


@pytest.fixture
def saves_page(ctx: AppContext) -> SavesPage:
    return SavesPage(ctx)


def test_page_reste_utilisable_sans_dossier_detecte(saves_page: SavesPage):
    """Sous Linux `save_dir()` vaut None : la page doit le dire, pas sembler cassée."""
    assert saves_mod.save_dir() is None
    assert saves_page.save_root is None
    assert not saves_page.snapshot_btn.isEnabled()
    assert saves_page.take_snapshot("sans dossier") is None
    # Le bouton grisé ne suffit pas : la page doit expliquer pourquoi et quoi faire.
    texts = [w.text() for w in saves_page.location_card.findChildren(QLabel)]
    assert any("Désignez le dossier à la main" in t for t in texts)


def test_dossier_designe_a_la_main_est_memorise(saves_page: SavesPage, tmp_path: Path):
    manual = tmp_path / "ailleurs"
    manual.mkdir()
    saves_page.set_save_root(manual)
    assert saves_page.save_root == manual
    assert saves_page.snapshot_btn.isEnabled()


@needs_saves
def test_instantane_sur_de_vraies_sauvegardes(saves_page: SavesPage, game_saves: Path):
    saves_page.set_save_root(game_saves)
    slot = saves_page.take_snapshot("avant-boss", "juste avant le pont")
    assert slot is not None
    assert slot.complete
    assert slot.note == "juste avant le pont"
    # La progression est lue une fois, à la copie, sur le vrai fichier GVAS.
    assert "checkpoints" in slot.progress
    # Les instantanés vivent hors de portée du pattern `*.sav` de Steam Cloud.
    assert slot.path.parent.name == saves_mod.SLOTS_DIRNAME
    assert not any(p.suffix == ".sav" for p in slot.path.iterdir())
    assert len(saves_mod.list_slots(game_saves)) == 1


@needs_saves
def test_snapshot_puis_restauration_rend_les_octets_exacts(saves_page: SavesPage,
                                                           game_saves: Path):
    saves_page.set_save_root(game_saves)
    original = (game_saves / "LastCheckpoint.sav").read_bytes()
    slot = saves_page.take_snapshot("point-de-retour")
    assert slot is not None

    # On simule une progression : le jeu écrase le checkpoint.
    later = SAVES_DRIVE / "CINDERVAULT + QUARY + YGDRAN" / STEAM_ID / "LastCheckpoint.sav"
    shutil.copyfile(later, game_saves / "LastCheckpoint.sav")
    assert (game_saves / "LastCheckpoint.sav").read_bytes() != original

    report = saves_page.restore_slot(slot)
    assert report is not None and report.ok
    assert (game_saves / "LastCheckpoint.sav").read_bytes() == original

    # Le filet : l'état écrasé a été mis de côté avant l'écriture.
    assert report.backup is not None
    assert report.backup.source == "auto-restauration"
    backup_file = report.backup.path / "LastCheckpoint.savedata"
    assert backup_file.read_bytes() != original

    # Et la restauration reste annulable d'un bloc.
    saves_page.ctx.ledger.undo_group(report.group)
    assert (game_saves / "LastCheckpoint.sav").read_bytes() != original


@needs_saves
def test_restauration_avertit_pour_steam_cloud(saves_page: SavesPage, game_saves: Path):
    saves_page.set_save_root(game_saves)
    slot = saves_page.take_snapshot("avec-avertissement")
    assert slot is not None
    report = saves_page.restore_slot(slot)
    assert report is not None
    # Hors Windows on ne peut pas savoir si Steam tourne — et « on ne sait pas » doit
    # produire un avertissement, jamais un silence rassurant.
    assert report.warnings
    assert any("Steam" in w for w in report.warnings)


@needs_saves
def test_sav_en_trop_signale_dans_la_page(saves_page: SavesPage, game_saves: Path):
    (game_saves / "LastCheckpoint.avant-boss.sav").write_bytes(b"copie a la main")
    saves_page.set_save_root(game_saves)
    notices = saves_mod.steam_cloud_notice(game_saves)
    assert notices and "LastCheckpoint.avant-boss.sav" in notices[0]
    labels = [w.text() for w in saves_page.cloud_card.findChildren(object)
              if hasattr(w, "text") and isinstance(w.text(), str)]
    assert any("avant-boss.sav" in t for t in labels)


@needs_saves
def test_suppression_d_un_instantane(saves_page: SavesPage, game_saves: Path):
    saves_page.set_save_root(game_saves)
    slot = saves_page.take_snapshot("a-jeter")
    assert slot is not None
    saves_mod.delete_slot(slot, ledger=saves_page.ctx.ledger)
    saves_page.refresh()
    assert saves_mod.list_slots(game_saves) == []
    # Les fichiers du jeu ne sont pas touchés par la suppression d'un instantané.
    assert (game_saves / "LastCheckpoint.sav").is_file()


def test_bibliotheque_est_une_grille_responsive(saves_page: SavesPage, tmp_path: Path):
    """Les saves s'affichent en cartes qui se replient selon la largeur (FlowLayout).

    Régression du look : la bibliothèque était une pile d'une carte par ligne. On veut
    une galerie qui montre plus de colonnes quand la fenêtre s'élargit.
    """
    from fe_launcher.ui.widgets import FlowLayout
    save_root = tmp_path / "saves"
    save_root.mkdir()
    for n in saves_mod.GAME_SAVE_FILES:
        (save_root / n).write_bytes(b"\x00" * 16)
    saves_page.set_save_root(save_root)

    cards = [w for w in saves_page.findChildren(QFrame) if w.objectName() == "SaveCard"]
    assert len(cards) == len(savelib.bundled_saves()) >= 15

    # Le reflow se mesure directement sur le FlowLayout : plus large => moins haut.
    flow = next(w.layout() for w in saves_page.findChildren(QWidget)
                if isinstance(w.layout(), FlowLayout))
    tall = flow.heightForWidth(300)     # étroit : une colonne, haut
    wide = flow.heightForWidth(1100)    # large : plusieurs colonnes, bas
    assert wide < tall, "la grille doit se replier : plus de largeur => moins de hauteur"
