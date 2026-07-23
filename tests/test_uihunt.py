"""Tests de régression « chasse aux incohérences d'interface » (QA).

Chaque test ici est né d'une revue manuelle des six pages, captures à l'appui. Deux
catégories :

* les **garde-fous** (tests qui passent) verrouillent un comportement correct constaté :
  le sélecteur d'install bascule vraiment, le verdict du banc ne désigne pas de gagnant
  sur du bruit, un mod C++ non compilé est distingué, la bibliothèque liste ses 15 saves ;

* les **bugs documentés** (`xfail`) reproduisent une incohérence trouvée à l'écran mais
  NON corrigée (interdiction de toucher au code de production) : ils décrivent le
  comportement voulu, échouent aujourd'hui, et repasseront au vert le jour du correctif —
  `strict=True` fait alors remonter un XPASS comme un échec, pour qu'on retire le marqueur.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from fe_launcher.core import paths, savelib  # noqa: E402
from fe_launcher.core.bench import Outcome  # noqa: E402
from fe_launcher.core.mods import ModState  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.main_window import DashboardPage  # noqa: E402
from fe_launcher.ui.pages.bench_page import BenchPage  # noqa: E402
from fe_launcher.ui.pages.mods_page import ModsPage  # noqa: E402
from fe_launcher.ui.pages.skins_page import SkinsPage  # noqa: E402
from fe_launcher.ui.theme import stylesheet  # noqa: E402

from .conftest import make_install  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet())
    return app


def _ctx(tmp_path: Path, install) -> AppContext:
    ctx = AppContext(data_dir=tmp_path / "appdata")
    ctx.installs = [install]
    ctx.select(install)
    return ctx


def _labels(widget) -> list[str]:
    return [l.text() for l in widget.findChildren(QLabel) if l.text()]


def _count_summary(page: DashboardPage) -> tuple[int, int]:
    """Extrait « X actif(s) sur Y » de la carte Mods du tableau de bord."""
    for text in _labels(page.mods_card):
        m = re.search(r"(\d+)\s+actif\(s\)\s+sur\s+(\d+)", text)
        if m:
            return int(m.group(1)), int(m.group(2))
    raise AssertionError("résumé de mods introuvable sur le tableau de bord")


# --- BUG 1 : la carte Mods du tableau de bord compte plus d'actifs que de total ------
# Cause : `enabled_mods` compte TOUS les mods activés (dont ue4ss-FEDevMenu, restreint),
# tandis que `visible_mods` exclut les mods restreints en mode normal. Un mod dev activé
# sur disque (ce que fait « Installer les mods fournis ») donne alors « 3 actif(s) sur 2 ».

def test_dashboard_active_never_exceeds_total(qapp, tmp_path):
    inst = make_install(tmp_path / "lib",
                        mod_names=["ue4ss-FEDevMenu", "ue4ss-FEMoonJump", "ue4ss-FESkins"])
    ctx = _ctx(tmp_path, inst)
    page = DashboardPage(ctx)
    active, total = _count_summary(page)
    assert active <= total, f"tableau de bord : {active} actif(s) sur {total}"


def test_dashboard_and_mods_page_agree_on_count(qapp, tmp_path):
    inst = make_install(tmp_path / "lib",
                        mod_names=["ue4ss-FEDevMenu", "ue4ss-FEMoonJump", "ue4ss-FESkins"])
    ctx = _ctx(tmp_path, inst)
    dash = DashboardPage(ctx)
    mods = ModsPage(ctx)
    dash_active, _ = _count_summary(dash)
    m = re.search(r"(\d+)\s+actif\(s\)\s+sur\s+(\d+)", mods.count_label.text())
    assert m, mods.count_label.text()
    assert dash_active == int(m.group(1))


# --- BUG 2 : la page Skins déborde horizontalement à la largeur par défaut ------------
# La galerie (5 vignettes fixes) impose une largeur minimale (~1032 px) supérieure à la
# zone de contenu disponible à 1120 px (912 px) et a fortiori au minimum 940 px (732 px) :
# barre de défilement horizontale, bandeau d'avertissement de lag tronqué, et colonne de
# détail (boutons « Appliquer »/« Rétablir ») repoussée hors champ.

def test_skins_page_fits_default_width(qapp, tmp_path):
    inst = make_install(tmp_path / "lib")
    ctx = _ctx(tmp_path, inst)
    page = SkinsPage(ctx)
    # Zone de contenu à la largeur de fenêtre par défaut (1120) moins la barre latérale.
    content_width = 1120 - 208
    assert page.minimumSizeHint().width() <= content_width, (
        f"Skins exige {page.minimumSizeHint().width()}px, "
        f"dispo {content_width}px à la largeur par défaut")


# --- Garde-fous : comportements corrects à ne pas casser ------------------------------

def test_install_picker_switches_active_install(qapp, tmp_path):
    """Basculer le sélecteur change l'install active ET rafraîchit le libellé UE4SS."""
    full = make_install(tmp_path / "full")           # chemin grec -> « Réparer »
    demo = make_install(tmp_path / "demo", full=False)  # ASCII + UE4SS -> « Réinstaller »
    ctx = AppContext(data_dir=tmp_path / "appdata")
    ctx.installs = [demo, full]
    ctx.select(full)

    page = DashboardPage(ctx)
    assert "Réparer" in page.ue4ss_btn.text()
    page.install_picker.setCurrentIndex(0)  # -> démo
    assert ctx.install.root == demo.root
    assert "Réinstaller" in page.ue4ss_btn.text(), \
        "le libellé du bouton UE4SS doit suivre l'install sélectionnée"


def test_bench_verdict_reports_no_winner_on_noise(qapp, tmp_path):
    """3/15 vs 6/15 est du bruit (Fisher p≈0,43) : aucun « gagnant » ne doit être désigné."""
    inst = make_install(tmp_path / "lib")
    ctx = _ctx(tmp_path, inst)
    page = BenchPage(ctx)
    page.steps_edit.setText("150 / 300")
    page._sync_from_fields()

    page.current = 150.0
    for _ in range(3):
        page.record(Outcome.HIT)
    for _ in range(12):
        page.record(Outcome.MISS)
    page.current = 300.0
    for _ in range(6):
        page.record(Outcome.HIT)
    for _ in range(9):
        page.record(Outcome.MISS)
    page.refresh()

    verdict = page.verdict_label.text().lower()
    assert "significatif" in verdict
    assert "hasard" in verdict or "plus d'essais" in verdict
    for banned in ("gagnant", "meilleur palier", "le meilleur"):
        assert banned not in verdict, f"le verdict ne doit pas désigner un {banned!r}"


def test_broken_cpp_mod_is_flagged(qapp, tmp_path):
    """Un mod C++ activé sans DLL compilée porte l'état BROKEN (badge « INCOMPLET »)."""
    inst = make_install(tmp_path / "lib",
                        mod_names=["ue4ss-FEMoonJump"])  # un mod lua sain à côté
    # mod C++ non compilé : dossier dlls/ + dllmain.cpp, sans main.dll, marqué actif.
    brk = inst.ue4ss.mods_dir / "ue4ss-FECheatUtils"
    (brk / "dlls").mkdir(parents=True)
    (brk / "dllmain.cpp").write_text("// cpp", encoding="utf-8")
    (brk / "enabled.txt").write_bytes(b"")

    ctx = _ctx(tmp_path, inst)
    broken = [m for m in ctx.mods if m.name == "ue4ss-FECheatUtils"]
    assert broken and broken[0].state is ModState.BROKEN

    page = ModsPage(ctx)
    # La page distingue les mods sans contenu exécutable dans son compteur.
    assert "incomplet" in page.count_label.text().lower()


def test_emptied_mod_folder_is_broken_not_enabled(qapp, tmp_path):
    """Un dossier de mod vidé de son script est INCOMPLET, jamais annoncé actif.

    Régression vécue en jeu : réinstaller UE4SS par-dessus avait vidé
    `ue4ss-FECoreGiver/` en laissant son `enabled.txt`. UE4SS répondait « Main script
    'main.lua' not found » pendant que le launcher affichait le mod comme ACTIF.
    """
    inst = make_install(tmp_path / "lib", mod_names=["ue4ss-FEMoonJump"])
    ghost = inst.ue4ss.mods_dir / "ue4ss-FECoreGiver"
    (ghost / "Scripts").mkdir(parents=True)   # dossier présent, main.lua absent
    (ghost / "enabled.txt").write_bytes(b"")

    ctx = _ctx(tmp_path, inst)
    mod = next(m for m in ctx.mods if m.name == "ue4ss-FECoreGiver")
    assert mod.state is ModState.BROKEN, "un dossier sans script ne doit pas passer actif"
    assert mod not in ctx.enabled_mods


def test_bundled_library_lists_fifteen_saves(qapp, tmp_path):
    """La bibliothèque de sauvegardes embarquées en compte bien 15."""
    assert len(savelib.bundled_saves()) == 15
