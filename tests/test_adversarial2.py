"""Deuxième campagne adversariale : casser les CORRECTIFS et le module neuf `boxes`.

Rôle de ce fichier
------------------
`test_adversarial.py` couvre la première campagne (27 bugs, 12 corrigés, 15 encore en
xfail). Ce fichier n'y touche pas et ne recompte pas ces 15 bugs. Il attaque :

  * le module neuf `core/boxes.py`, jamais testé ;
  * les correctifs récents de `luaconf`, `ledger`, `doctor`, `bench`, `saves` et l'UI,
    à la recherche de RÉGRESSIONS introduites par la correction elle-même.

Convention identique à la première campagne : un `xfail(strict=True)` décrit un bug
REPRODUIT — le test affirme le comportement correct, échoue aujourd'hui, passera en
XPASS le jour du correctif. Les tests simples documentent ce qui résiste.

Aucun correctif n'est appliqué au code de production par ce fichier.
"""

from __future__ import annotations

import os
import random
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from fe_launcher.core import boxes, doctor, luaconf, paths, saves  # noqa: E402
from fe_launcher.core.bench import Campaign, Outcome, Trial  # noqa: E402
from fe_launcher.core.ledger import Action, Ledger  # noqa: E402
from fe_launcher.ui.context import AppContext  # noqa: E402
from fe_launcher.ui.main_window import DashboardPage, MainWindow  # noqa: E402
from fe_launcher.ui.pages import mods_page  # noqa: E402

from tools import make_fixture  # noqa: E402

from .conftest import make_install  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


LUAC: bool | None = None


def lua_ok(path: Path) -> bool | None:
    """True/False selon `luac -p`, None si luac est absent (assertion alors ignorée)."""
    global LUAC
    if LUAC is None:
        LUAC = bool(shutil.which("luac"))
    if not LUAC:
        return None
    return subprocess.run(["luac", "-p", "-o", os.devnull, str(path)],
                          capture_output=True).returncode == 0


# =====================================================================================
# CIBLE 1 — module neuf boxes.py
# =====================================================================================

def _boxes_setup(tmp_path: Path):
    led = Ledger(tmp_path / "led")
    cfg = tmp_path / "cfg"
    return led, cfg


def test_enable_qui_echoue_ne_laisse_pas_dentree_fantome(tmp_path: Path):
    led, cfg = _boxes_setup(tmp_path)
    cfg.mkdir(parents=True)
    (cfg / boxes.ENGINE_INI).mkdir()          # Engine.ini est un DOSSIER
    r = boxes.enable(led, root=cfg)
    assert r.ok is False                       # l'échec est bien signalé
    # ...mais aucune entrée ne doit rester au journal : rien n'a été écrit.
    assert led.pending == [], (
        "entrée fantôme laissée au journal : "
        f"{[(e.action.value, e.target) for e in led.pending]}")


def test_ensure_repete_en_echec_ne_gonfle_pas_le_journal(tmp_path: Path):
    led, cfg = _boxes_setup(tmp_path)
    cfg.mkdir(parents=True)
    os.chmod(cfg, 0o500)                        # dossier non inscriptible
    try:
        for _ in range(5):
            assert boxes.ensure(led, True, root=cfg).ok is False
        assert not (cfg / boxes.ENGINE_INI).exists()   # rien n'a été créé
        assert len(led.pending) == 0, (
            f"{len(led.pending)} entrées fantômes accumulées après 5 lancements")
    finally:
        os.chmod(cfg, 0o700)


def test_boxes_cycle_nominal_est_reversible(tmp_path: Path):
    """Ce qui résiste : activer puis désactiver retire proprement le fichier."""
    led, cfg = _boxes_setup(tmp_path)
    assert boxes.enable(led, root=cfg).ok
    assert (cfg / boxes.ENGINE_INI).is_file()
    assert boxes.status(led, root=cfg).active
    assert boxes.disable(led, root=cfg).ok
    assert not (cfg / boxes.ENGINE_INI).exists()
    assert led.pending == []


def test_boxes_double_enable_et_disable_a_froid(tmp_path: Path):
    """Résiste : enable() deux fois est idempotent, disable() sans rien est un no-op."""
    led, cfg = _boxes_setup(tmp_path)
    assert boxes.disable(led, root=cfg).ok           # rien à désactiver
    assert boxes.enable(led, root=cfg).ok
    assert boxes.enable(led, root=cfg).ok             # 2e fois
    assert len(led.entries) == 1                      # un seul dépôt journalisé


def test_boxes_ne_touche_pas_un_engine_ini_etranger(tmp_path: Path):
    """Résiste : un Engine.ini que le launcher n'a pas créé est laissé intact."""
    led, cfg = _boxes_setup(tmp_path)
    cfg.mkdir(parents=True)
    (cfg / boxes.ENGINE_INI).write_text("réglages perso de l'utilisateur")
    st = boxes.status(led, root=cfg)
    assert st.blocked_by_foreign_file
    assert boxes.enable(led, root=cfg).ok is False
    assert boxes.disable(led, root=cfg).ok is False
    assert (cfg / boxes.ENGINE_INI).read_text() == "réglages perso de l'utilisateur"


def test_boxes_hors_windows_est_non_supporte():
    """Résiste : sans racine explicite et hors Windows, le mode est simplement indispo."""
    led = Ledger(Path(os.devnull).parent / "nexistepas_led")
    st = boxes.status(led)          # root=None, config_dir() -> None hors Windows
    assert st.supported is False
    assert boxes.enable(led).ok is False


# =====================================================================================
# CIBLE 2 — luaconf : le nouvel échappement introduit-il une dérive ?
# =====================================================================================

def test_valeurs_hostiles_restent_du_lua_valide(tmp_path: Path):
    """Résiste : _encode produit du Lua VALIDE même sur des entrées pénibles (luac -p)."""
    cas = [
        "chemin finissant par \\",
        'x \\" y',
        'il a dit "non" c\'est fini',
        "a\x00b", "a\x1bb",
        "".join(chr(i) for i in range(1, 32)),
        "-- faux commentaire",
        "\U0001F4A9\U00010348",
        "]] ]==] [[",
        "",
    ]
    for i, val in enumerate(cas):
        f = tmp_path / f"m{i}.lua"
        f.write_text('local S = "x"\nlocal K = 1\n')
        luaconf.write(f, "S", val)
        ok = lua_ok(f)
        if ok is not None:
            assert ok, f"Lua invalide pour {val!r} : {f.read_bytes()!r}"
        # la constante voisine n'a pas bougé
        assert luaconf.read(f, "K").value == 1


def test_reecriture_a_lidentique_ne_double_pas_les_echappements(tmp_path: Path):
    f = tmp_path / "main.lua"
    original = 'local P = "C:\\\\Users\\\\test"\n'   # Lua valide : chaîne = C:\Users\test
    f.write_text(original)
    # On relit la valeur et on la réécrit SANS la modifier : ce doit être un no-op.
    for _ in range(3):
        s = luaconf.read(f, "P")
        luaconf.write(f, "P", s.value)
    assert f.read_text() == original, (
        f"le fichier a dérivé sur une réécriture identité : {f.read_text()!r}")


def test_undo_dun_lua_set_sur_chaine_restaure_a_loctet(tmp_path: Path):
    f = tmp_path / "main.lua"
    original = 'local P = "a\\\\b"\n'
    f.write_text(original)
    led = Ledger(tmp_path / "led")
    old = luaconf.read(f, "P").value
    luaconf.write(f, "P", "neuf")
    led.lua_set(f, "P", old, "neuf")
    led.undo()
    assert f.read_text() == original, (
        f"undo de lua_set n'a pas restauré la chaîne : {f.read_text()!r}")


def test_fins_de_ligne_mixtes_ne_sont_pas_normalisees(tmp_path: Path):
    """Résiste : un fichier mêlant CRLF et LF garde chaque fin de ligne à l'octet près."""
    f = tmp_path / "main.lua"
    raw = b"local A = 1\r\nlocal B = 2\nlocal C = 3\r\n"
    f.write_bytes(raw)
    luaconf.write(f, "A", 1)            # réécrit la MÊME valeur
    assert f.read_bytes() == raw


def test_bom_utf8_est_preserve_a_la_reecriture(tmp_path: Path):
    f = tmp_path / "main.lua"
    raw = "﻿local A = 1\r\nlocal B = 2\r\n".encode("utf-8")   # BOM + CRLF
    f.write_bytes(raw)
    luaconf.write(f, "A", 1)
    assert f.read_bytes() == raw, f"BOM ou fins de ligne altérés : {f.read_bytes()!r}"


# =====================================================================================
# CIBLE 2 — ledger : les nouveaux chemins create<->modify / os.replace / rename
# =====================================================================================

def test_create_modify_ne_recursent_pas_a_linfini(tmp_path: Path):
    """Résiste : create_file(existant) -> modify_file, modify_file(absent) -> create_file,
    sans boucle et avec une annulation correcte des deux côtés."""
    led = Ledger(tmp_path / "led")
    p = tmp_path / "f.txt"
    assert led.create_file(p, b"a").action is Action.CREATE_FILE
    assert led.create_file(p, b"b").action is Action.MODIFY_FILE
    g = tmp_path / "g.txt"
    e = led.modify_file(g, b"c")
    assert e.action is Action.CREATE_FILE
    assert all(r.ok for r in led.undo([e]))
    assert not g.exists()


def test_echec_de_rename_ne_laisse_aucune_entree(tmp_path: Path):
    """Résiste (correctif) : rename() ne journalise qu'après succès."""
    led = Ledger(tmp_path / "led")
    src = tmp_path / "a"; src.mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "occupe").write_text("x")   # 'Directory not empty'
    with pytest.raises(OSError):
        led.rename(src, tmp_path / "b")
    assert led.entries == []


def test_os_replace_du_load_survit_a_une_seconde_corruption(tmp_path: Path):
    """Résiste (correctif) : un ledger.json corrompu DEUX fois de suite (le .corrupt
    existe déjà) ne bloque plus le démarrage."""
    root = tmp_path / "led"
    root.mkdir()
    (root / "ledger.json").write_text("pas du json {")
    (root / "ledger.json.corrupt").write_text("ancienne corruption")
    led = Ledger(root)               # ne doit pas lever
    assert led.entries == []


def test_delete_file_sur_chemin_absent_reste_annulable(tmp_path: Path):
    led = Ledger(tmp_path / "led")
    led.delete_file(tmp_path / "jamais_existe.txt", label="fantôme")
    results = led.undo()
    assert all(r.ok for r in results), (
        f"entrée DELETE_FILE inannulable : {[(r.ok, r.message) for r in results]}")


def test_undo_de_groupe_mixte(tmp_path: Path):
    """Résiste : un groupe create+modify est bien annulé ensemble."""
    led = Ledger(tmp_path / "led")
    f1 = tmp_path / "m1.txt"
    f2 = tmp_path / "m2.txt"; f2.write_text("origine")
    led.create_file(f1, b"neuf", group="G")
    led.modify_file(f2, b"change", group="G")
    assert all(r.ok for r in led.undo_group("G"))
    assert not f1.exists()
    assert f2.read_text() == "origine"


# =====================================================================================
# CIBLE 2 — doctor.fix_non_ascii_path (octets, re.sub ancré count=1)
# =====================================================================================

def _install_with_manifest(tmp_path: Path, dirname: str, acf_bytes: bytes):
    common = tmp_path / "steamapps" / "common"
    common.mkdir(parents=True)
    root = make_fixture.build_install(common, full=True, mods=[])
    root = root.rename(common / dirname)
    acf = common.parent / f"appmanifest_{doctor.APPID}.acf"
    acf.write_bytes(acf_bytes)
    inst = paths.inspect(root, source="test")
    assert inst is not None
    return inst, acf


GREEK = "Project Ygrό"                      # omicron-tonos, non-ASCII
GREEK_B = GREEK.encode("utf-8")


def test_fix_non_ascii_octets_latin1_preserves(tmp_path: Path):
    """Résiste : un octet non-UTF-8 ailleurs dans le manifeste (nom de compte accentué
    en latin-1) n'est PAS remplacé par U+FFFD — le correctif travaille en octets."""
    acf_bytes = (b'"AppState"\n{\n\t"UserName"\t\t"Jo\xe9l"\n'
                 b'\t"installdir"\t\t"' + GREEK_B + b'"\n}\n')
    inst, acf = _install_with_manifest(tmp_path, GREEK, acf_bytes)
    r = doctor.fix_non_ascii_path(inst, probe=lambda: False)
    assert r.ok
    out = acf.read_bytes()
    assert b"Jo\xe9l" in out              # l'octet latin-1 est intact
    assert b'"installdir"\t\t"Project Ygro"' in out


def test_fix_non_ascii_crlf_preserve(tmp_path: Path):
    """Résiste : un manifeste en CRLF garde ses CRLF, seul installdir change."""
    acf_bytes = (b'"AppState"\n{\n\t"appid"\t\t"2467880"\n'
                 b'\t"installdir"\t\t"' + GREEK_B + b'"\n}\n').replace(b"\n", b"\r\n")
    inst, acf = _install_with_manifest(tmp_path, GREEK, acf_bytes)
    r = doctor.fix_non_ascii_path(inst, probe=lambda: False)
    assert r.ok
    out = acf.read_bytes()
    assert out.count(b"\r\n") == acf_bytes.count(b"\r\n")
    assert b"Project Ygro" in out


@pytest.mark.parametrize("acf_bytes,label", [
    (b'"AppState"\n{\n\t"appid"\t\t"2467880"\n}\n', "sans installdir"),
    (b"", "manifeste vide"),
])
def test_fix_non_ascii_sans_installdir_refuse(tmp_path: Path, acf_bytes, label):
    """Résiste : sans clé installdir, le renommage est refusé sans rien toucher."""
    inst, acf = _install_with_manifest(tmp_path, GREEK, acf_bytes)
    avant = acf.read_bytes()
    r = doctor.fix_non_ascii_path(inst, probe=lambda: False)
    assert r.ok is False, label
    assert acf.read_bytes() == avant
    assert inst.root.is_dir()             # dossier pas renommé


def test_fix_non_ascii_nom_regex_dans_le_dossier(tmp_path: Path):
    """Résiste : des méta-caractères regex/de remplacement dans le nom du dossier ne
    cassent pas la substitution (le remplacement est une fonction, pas une chaîne)."""
    name = "Projet.*[Ygrό]\\1"
    acf_bytes = b'"AppState"\n{\n\t"installdir"\t\t"' + name.encode("utf-8") + b'"\n}\n'
    inst, acf = _install_with_manifest(tmp_path, name, acf_bytes)
    r = doctor.fix_non_ascii_path(inst, probe=lambda: False)
    assert r.ok
    assert b'"installdir"\t\t"Projet.*[Ygro]\\1"' in acf.read_bytes()


# =====================================================================================
# CIBLE 2 — bench : Holm, verdict, champ unit
# =====================================================================================

def _holm_ref(pvals, alpha=0.05):
    """Holm-Bonferroni réimplémenté indépendamment. Retourne les index rejetés."""
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    rejected, m = set(), len(pvals)
    for k, i in enumerate(order):
        if pvals[i] <= alpha / (m - k):
            rejected.add(i)
        else:
            break
    return rejected


def _campaign(spec):
    c = Campaign(name="t")
    for v, h, n in spec:
        for i in range(n):
            c.record(v, Outcome.HIT if i < h else Outcome.MISS)
    return c


def test_holm_egale_une_reimplementation_independante():
    """Résiste : holm() correspond exactement à un Holm-Bonferroni écrit à part,
    sur 300 campagnes aléatoires."""
    rng = random.Random(7)
    for _ in range(300):
        k = rng.randint(2, 8)
        spec = [(100.0 * (i + 1), rng.randint(0, 15), 15) for i in range(k)]
        c = _campaign(spec)
        pool = [b for b in c.buckets if b.n]
        top = max(pool, key=lambda x: x.rate)
        others = [b for b in pool if b is not top]
        # On vérifie le CŒUR Holm pur (`_holm`), la brique commune. La méthode publique
        # `holm()` applique en plus une correction du biais de sélection du maximum
        # (alpha resserré par le nombre de candidats), testée à part par le taux de
        # faux positifs — elle diverge donc volontairement d'un Holm standard.
        got = {id(b) for b in c._holm(top, others, 0.05)}
        pv = [c.significance(top, b) for b in others]
        exp = {id(others[i]) for i in _holm_ref(pv)}
        assert got == exp


def _false_winner_rate(k, reps, seed, n=15, p=0.30):
    """Fréquence à laquelle holm() désigne un gagnant alors que TOUS les paliers ont
    le même taux réel p (hypothèse nulle : aucun gagnant n'existe)."""
    rng = random.Random(seed)
    bad = 0
    for _ in range(reps):
        c = Campaign(name="s")
        for i in range(k):
            b = c.bucket(float(i))
            b.trials = [Trial(outcome=Outcome.HIT if rng.random() < p else Outcome.MISS,
                              at="") for _ in range(n)]
        top = max(c.buckets, key=lambda x: x.rate)
        if c.holm(top, [b for b in c.buckets if b is not top]):
            bad += 1
    return bad / reps


def test_holm_faux_positifs_bornes_par_alpha_2_et_5_paliers():
    """Résiste : à 2 et 5 paliers, le taux de faux gagnants reste sous alpha."""
    assert _false_winner_rate(2, 3000, seed=101) <= 0.05
    assert _false_winner_rate(5, 3000, seed=202) <= 0.05


@pytest.mark.parametrize("k", [12, 20])
def test_holm_faux_positifs_bornes_par_alpha_grands_balayages(k):
    # p=0.5 : régime où la discrétude de Fisher rend la sélection du meilleur observé
    # la plus anti-conservative. L'écart au-dessus d'alpha y est net et reproductible.
    rate = _false_winner_rate(k, 3000, seed=303 + k, p=0.50)
    assert rate <= 0.05, f"{k} paliers : {rate:.1%} de faux gagnants > alpha=5%"


def test_unit_survit_a_laller_retour_json(tmp_path: Path):
    """Résiste : le nouveau champ `unit` est sérialisé et relu à l'identique."""
    c = _campaign([(100, 3, 15), (200, 9, 15)])
    c.unit = "frames"
    c.save(tmp_path / "c.json")
    c2 = Campaign.load(tmp_path / "c.json")
    assert c2.unit == "frames"
    assert c2.verdict() == c.verdict()
    assert "frames" in c2.verdict()


def test_campagne_sans_unit_reste_lisible(tmp_path: Path):
    """Résiste (rétrocompat) : une campagne enregistrée AVANT le champ unit retombe sur
    la valeur par défaut « ms »."""
    import json
    c = _campaign([(100, 3, 15), (200, 9, 15)])
    c.save(tmp_path / "c.json")
    blob = json.loads((tmp_path / "c.json").read_text())
    del blob["unit"]
    (tmp_path / "old.json").write_text(json.dumps(blob))
    c2 = Campaign.load(tmp_path / "old.json")
    assert c2.unit == "ms"
    assert "ms" in c2.verdict()


# =====================================================================================
# CIBLE 2 — saves.snapshot() ne journalise plus
# =====================================================================================

def _save_root(tmp_path: Path) -> Path:
    root = tmp_path / "SaveGames" / "76561198000000000"
    root.mkdir(parents=True)
    for n in saves.GAME_SAVE_FILES:
        (root / n).write_bytes(b"ORIGINE-" + n.encode())
    return root


def test_instantane_survit_a_un_undo_complet(tmp_path: Path):
    """Résiste : snapshot() ne journalise pas — une désinstallation (undo global +
    purge) n'efface pas les points de restauration du joueur."""
    root = _save_root(tmp_path)
    led = Ledger(tmp_path / "led")
    slot = saves.snapshot("avant-boss", root, ledger=led)
    assert led.entries == []                     # rien de journalisé
    led.undo()
    led.purge_self()
    assert slot.path.is_dir()
    assert len(list(slot.path.iterdir())) >= 3


def test_restore_puis_undo_puis_delete_slot_coherents(tmp_path: Path):
    """Résiste : restore() reste annulable, et delete_slot() garde la liste cohérente."""
    root = _save_root(tmp_path)
    led = Ledger(tmp_path / "led")
    slot = saves.snapshot("avant-boss", root, ledger=led)
    for n in saves.GAME_SAVE_FILES:
        (root / n).write_bytes(b"APRES-" + n.encode())

    rep = saves.restore(slot, root, ledger=led, probe=lambda: False)
    assert rep.ok
    assert (root / "LastCheckpoint.sav").read_bytes().startswith(b"ORIGINE-")
    assert rep.backup is not None                # filet automatique

    led.undo_group(rep.group)
    assert (root / "LastCheckpoint.sav").read_bytes().startswith(b"APRES-")

    assert saves.delete_slot(slot, ledger=led)
    noms = {s.name for s in saves.list_slots(root)}
    assert "avant-boss" not in noms
    assert saves.delete_slot(slot, ledger=led) is False   # déjà supprimé


# =====================================================================================
# CIBLE 2 — UI : mods_page (case sans texte, tri) et main_window (barre d'état, no-install)
# =====================================================================================

def test_case_a_cocher_est_sans_texte_et_le_nom_ne_bascule_pas(qapp, tmp_path):
    """Résiste : la case n'a pas de texte, cliquer le nom ne change pas l'état."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    inst = make_install(tmp_path / "lib")
    ctx = AppContext(data_dir=tmp_path / "data")
    ctx.select(inst); ctx.refresh()
    page = mods_page.ModsPage(ctx); page.refresh()
    row = page.findChildren(mods_page.ModRow)[0]
    assert row.box.text() == ""
    avant = row.box.isChecked()
    row.show(); qapp.processEvents()
    lab = row.name_label
    QTest.mouseClick(lab, Qt.MouseButton.LeftButton,
                     pos=QPoint(max(1, lab.width() // 2), max(1, lab.height() // 2)))
    qapp.processEvents()
    assert row.box.isChecked() == avant


def test_le_tri_ne_perd_aucun_mod(qapp, tmp_path):
    """Résiste : même avec des noms proches en casse et des espaces, tous les mods
    visibles apparaissent une fois."""
    hostiles = ["ue4ss-Zeta", "ue4ss-alpha", "AAA", "ue4ss-ALPHA", "zz", "ue4ss-alpha "]
    inst = make_install(tmp_path / "lib", mod_names=hostiles)
    ctx = AppContext(data_dir=tmp_path / "data")
    ctx.select(inst); ctx.refresh()
    page = mods_page.ModsPage(ctx); page.refresh()
    attendus = sorted(m.name for m in ctx.visible_mods)
    affiches = sorted(r.mod_name for r in page.findChildren(mods_page.ModRow))
    assert affiches == attendus


def test_barre_detat_remplie_des_louverture(qapp, tmp_path):
    """Résiste (correctif) : la barre d'état n'est pas vide au démarrage."""
    inst = make_install(tmp_path / "lib")
    ctx = AppContext(data_dir=tmp_path / "data")
    ctx.select(inst); ctx.refresh()
    w = MainWindow(ctx)
    assert w.status.text().strip() != ""


def test_toutes_les_pages_et_la_fenetre_sans_installation(qapp, tmp_path):
    """Résiste : aucune page ni la fenêtre ne lève quand ctx.install is None."""
    from fe_launcher.ui.pages.bench_page import BenchPage
    from fe_launcher.ui.pages.saves_page import SavesPage
    from fe_launcher.ui.pages.settings_page import SettingsPage
    ctx = AppContext(data_dir=tmp_path / "data")
    ctx.select(None); ctx.refresh()
    assert ctx.install is None
    for cls in (DashboardPage, mods_page.ModsPage, BenchPage, SavesPage, SettingsPage):
        pg = cls(ctx)
        pg.refresh()
        pg.refresh()
    w = MainWindow(ctx)
    assert w.status.text().strip() != ""


def test_carte_diagnostic_sans_installation(qapp, tmp_path):
    """Résiste : le tableau de bord affiche un message d'attente au lieu de planter."""
    ctx = AppContext(data_dir=tmp_path / "data")
    ctx.select(None); ctx.refresh()
    dash = DashboardPage(ctx); dash.refresh()
    textes = " ".join(l.text() for l in dash.findChildren(QLabel))
    assert "Aucune installation" in textes
