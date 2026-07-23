"""Tests du module de diagnostic.

Toutes les fixtures sont de VRAIES arborescences fabriquées par tools/make_fixture.py,
pas des mocks : le Doctor ne fait que du système de fichiers, le mocker reviendrait à
tester le mock. Chaque contrôle est vérifié dans son cas positif ET dans son cas négatif
(install saine → aucun avertissement), parce qu'un Doctor qui crie tout le temps est
aussi inutile qu'un Doctor muet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fe_launcher.core import doctor, mods as mods_mod  # noqa: E402
from fe_launcher.core.doctor import Level  # noqa: E402
from fe_launcher.core.paths import APPID, Edition, inspect  # noqa: E402
from tools import make_fixture  # noqa: E402

# Un mod Lua qui dépend d'UEHelpers, ce que le mod d'exemple du fixture ne fait pas.
LUA_WITH_UEHELPERS = """\
-- Mod de test qui depend d'UEHelpers.
local UEHelpers = require("UEHelpers")
local DELAY_MS = 500   -- delai

RegisterKeyBind(Key.F9, function() end)
"""


# --- Fabriques de fixtures ------------------------------------------------------

def make(tmp_path: Path, *, full: bool = False, with_ue4ss: bool = True,
         mods: list[str] | None = None, manifest: bool = False):
    """Construit une install et retourne le GameInstall correspondant."""
    common = tmp_path / "steamapps" / "common"
    root = make_fixture.build_install(common, full=full, with_ue4ss=with_ue4ss,
                                      mods=mods if mods is not None else [])
    if manifest:
        make_fixture.build_steam_library(tmp_path / "steamapps", installdir=root.name)
    install = inspect(root, source="fixture")
    assert install is not None, "le fixture doit être reconnu comme une install"
    return install


def codes(diagnoses) -> set[str]:
    return {d.code for d in diagnoses}


def by_code(diagnoses, code: str):
    for d in diagnoses:
        if d.code == code:
            return d
    raise AssertionError(f"diagnostic absent : {code} (présents : {sorted(codes(diagnoses))})")


def add_lua_mod(install, name: str, source: str) -> Path:
    mod_dir = install.ue4ss.mods_dir / name
    (mod_dir / "Scripts").mkdir(parents=True, exist_ok=True)
    (mod_dir / "Scripts" / "main.lua").write_text(source, encoding="utf-8")
    (mod_dir / "enabled.txt").write_bytes(b"")
    return mod_dir


# --- Cas négatif : une install saine ne doit produire que des OK -----------------

def test_install_saine_que_des_ok(tmp_path):
    # Un seul mod : deux mods du fixture partagent la même touche, ce qui serait un
    # conflit légitime et pas une install saine.
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    result = doctor.run(install)

    assert result, "le Doctor doit toujours produire des constats"
    assert [d for d in result if d.level is not Level.OK] == []
    assert doctor.worst(result) is Level.OK
    assert "saine" in doctor.summary(result)


def test_install_saine_couvre_tous_les_controles(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    assert codes(doctor.run(install)) == {
        "path.ascii", "install.edition", "ue4ss.present", "ue4ss.layout",
        "ue4ss.proxy_ok", "ue4ss.uehelpers_ok", "mods.cpp_ok",
        "mods.no_conflict", "mods.txt_coherent",
    }


# --- 1. Chemin non-ASCII --------------------------------------------------------

def test_chemin_non_ascii_est_une_erreur(tmp_path):
    install = make(tmp_path, full=True, mods=["ue4ss-FESolo"])
    d = by_code(doctor.run(install), "path.non_ascii")

    assert d.level is Level.ERROR
    assert d.actionable and d.fix is not None
    # Le caractère fautif doit être nommé précisément, pas juste « caractère spécial ».
    assert "U+03CC" in d.detail
    # Les étapes manuelles doivent rappeler les deux points qui font échouer la manip.
    assert "installdir" in d.detail
    assert f"appmanifest_{APPID}" in d.detail
    assert "Quitter Steam" in d.detail or "Quitter" in d.detail
    assert "multi-byte" in d.why
    assert "mise à jour Steam" in d.why


def test_chemin_ascii_est_ok(tmp_path):
    install = make(tmp_path, full=False)
    d = by_code(doctor.run(install), "path.ascii")
    assert d.level is Level.OK
    assert d.fix is None


def test_ascii_name_translittere_l_omicron_tonos():
    assert doctor.ascii_name("Project Ygrό") == "Project Ygro"
    assert doctor.ascii_name("Fading Echo Demo") == "Fading Echo Demo"
    assert doctor.ascii_name("Café") == "Cafe"
    # Caractère qu'on ne sait pas rendre : on refuse plutôt que d'inventer un nom.
    assert doctor.ascii_name("Jeu 日本語") == ""


def test_fix_refuse_si_steam_tourne(tmp_path):
    install = make(tmp_path, full=True, manifest=True)
    res = doctor.fix_non_ascii_path(install, probe=lambda: True)

    assert not res.ok
    assert "Steam" in res.message
    assert install.root.is_dir(), "aucun renommage ne doit avoir eu lieu"


def test_fix_refuse_si_etat_de_steam_inconnu(tmp_path):
    """Le cas dangereux : ne pas savoir doit valoir un refus, pas un « probablement ok »."""
    install = make(tmp_path, full=True, manifest=True)
    res = doctor.fix_non_ascii_path(install, probe=lambda: None)

    assert not res.ok
    assert "vérifier" in res.message
    assert install.root.is_dir()


def test_fix_refuse_sans_manifeste(tmp_path):
    install = make(tmp_path, full=True, manifest=False)
    res = doctor.fix_non_ascii_path(install, probe=lambda: False)

    assert not res.ok
    assert "anifeste" in res.message
    assert install.root.is_dir(), "sans manifeste on ne renomme pas : Steam perdrait le jeu"


def test_fix_refuse_si_la_cible_existe_deja(tmp_path):
    install = make(tmp_path, full=True, manifest=True)
    install.root.with_name("Project Ygro").mkdir()

    res = doctor.fix_non_ascii_path(install, probe=lambda: False)
    assert not res.ok
    assert install.root.is_dir()


def test_fix_renomme_et_met_a_jour_le_manifeste(tmp_path):
    install = make(tmp_path, full=True, manifest=True)
    acf = doctor.manifest_for(install)
    assert acf is not None

    res = doctor.fix_non_ascii_path(install, probe=lambda: False)

    assert res.ok, res.message
    renamed = install.root.with_name("Project Ygro")
    assert renamed.is_dir()
    assert not install.root.exists()
    assert '"installdir"' in acf.read_text(encoding="utf-8")
    assert "Ygro" in acf.read_text(encoding="utf-8")
    assert "Ygrό" not in acf.read_text(encoding="utf-8")

    # Et l'install renommée est saine du point de vue du chemin.
    again = inspect(renamed, source="fixture")
    assert again is not None and not again.non_ascii_path


# --- 2. UE4SS absent ------------------------------------------------------------

def test_ue4ss_absent_est_un_avertissement_pas_une_erreur(tmp_path):
    install = make(tmp_path, full=False, with_ue4ss=False)
    result = doctor.run(install)
    d = by_code(result, "ue4ss.absent")

    assert d.level is Level.WARN
    assert doctor.worst(result) is Level.WARN
    assert "sans UE4SS" in d.why
    # Sans UE4SS, les contrôles qui en dépendent ne doivent pas être émis du tout.
    assert "ue4ss.uehelpers_missing" not in codes(result)
    assert "mods.no_conflict" not in codes(result)


# --- 3. UEHelpers manquant ------------------------------------------------------

def test_uehelpers_manquant_est_une_erreur_et_compte_les_mods(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    add_lua_mod(install, "ue4ss-FEAlpha", LUA_WITH_UEHELPERS)
    add_lua_mod(install, "ue4ss-FEBeta", LUA_WITH_UEHELPERS.replace("F9", "F10"))
    install.ue4ss.uehelpers.unlink()

    d = by_code(doctor.run(install), "ue4ss.uehelpers_missing")
    assert d.level is Level.ERROR
    # Le compte doit être réel, pas la constante « 19 » du projet.
    assert "2 mod(s)" in d.detail
    assert "ue4ss-FEAlpha" in d.detail and "ue4ss-FEBeta" in d.detail
    assert "ue4ss-FESolo" not in d.detail, "ce mod ne requiert pas UEHelpers"


def test_uehelpers_manquant_signale_meme_sans_dependant(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    install.ue4ss.uehelpers.unlink()

    d = by_code(doctor.run(install), "ue4ss.uehelpers_missing")
    assert d.level is Level.ERROR
    assert "Aucun mod" in d.detail


def test_uehelpers_present_compte_les_dependants(tmp_path):
    install = make(tmp_path, full=False)
    add_lua_mod(install, "ue4ss-FEAlpha", LUA_WITH_UEHELPERS)

    d = by_code(doctor.run(install), "ue4ss.uehelpers_ok")
    assert d.level is Level.OK
    assert "1 mod(s)" in d.detail


# --- 4. Mods C++ non compilés ---------------------------------------------------

def test_mod_cpp_sans_dll_est_signale_et_nomme(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    cpp = install.ue4ss.mods_dir / "ue4ss-FEOverlay"
    (cpp / "dlls").mkdir(parents=True)
    (cpp / "enabled.txt").write_bytes(b"")

    d = by_code(doctor.run(install), "mods.cpp_not_compiled")
    assert d.level is Level.WARN
    assert "ue4ss-FEOverlay" in d.detail
    assert d.fix is not None

    res = d.fix()
    assert res.ok, res.message
    reloaded = {m.name: m for m in mods_mod.load(install.ue4ss)}
    assert reloaded["ue4ss-FEOverlay"].state is mods_mod.ModState.DISABLED
    assert reloaded["ue4ss-FESolo"].state is mods_mod.ModState.ENABLED

    # Après correction, le contrôle repasse au vert.
    assert by_code(doctor.run(install), "mods.cpp_ok").level is Level.OK


def test_mod_cpp_compile_ne_declenche_rien(tmp_path):
    install = make(tmp_path, full=False)
    cpp = install.ue4ss.mods_dir / "ue4ss-FEOverlay"
    (cpp / "dlls").mkdir(parents=True)
    (cpp / "dlls" / "main.dll").write_bytes(b"MZ")
    (cpp / "enabled.txt").write_bytes(b"")

    assert by_code(doctor.run(install), "mods.cpp_ok").level is Level.OK


# --- 5. Conflits de touches et de commandes -------------------------------------

def test_conflit_de_touche_et_de_commande(tmp_path):
    # Les deux mods du fixture déclarent tous deux F7 et la commande `demo`.
    install = make(tmp_path, full=False, mods=["ue4ss-FEMoonJump", "ue4ss-FEInfiniteCore"])
    result = doctor.run(install)

    key = by_code(result, "mods.conflict.keybind.F7")
    cmd = by_code(result, "mods.conflict.command.demo")

    # Une touche partagée reste un AVERTISSEMENT (déclenche plusieurs actions), mais
    # une COMMANDE console partagée fait crasher le jeu sur ce moteur : c'est une ERREUR.
    assert key.level is Level.WARN and cmd.level is Level.ERROR
    assert "CRASH" in cmd.why or "crash" in cmd.why
    assert "toutes les actions" in key.why or "tous les callbacks" in key.why
    assert "campagne de mesure" in key.why
    assert len(key.options) == 2


def test_conflit_option_garde_un_seul_mod(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FEMoonJump", "ue4ss-FEInfiniteCore"])
    key = by_code(doctor.run(install), "mods.conflict.keybind.F7")

    keep = next(o for o in key.options if "ue4ss-FEMoonJump" in o.label)
    res = keep.run()
    assert res.ok, res.message

    states = {m.name: m.state for m in mods_mod.load(install.ue4ss)}
    assert states["ue4ss-FEMoonJump"] is mods_mod.ModState.ENABLED
    assert states["ue4ss-FEInfiniteCore"] is mods_mod.ModState.DISABLED
    assert by_code(doctor.run(install), "mods.no_conflict").level is Level.OK


def test_mods_desactives_ne_creent_pas_de_conflit(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FEMoonJump", "ue4ss-FEInfiniteCore"])
    (install.ue4ss.mods_dir / "ue4ss-FEInfiniteCore" / "enabled.txt").unlink()

    assert by_code(doctor.run(install), "mods.no_conflict").level is Level.OK


# --- 6. DLL proxy manquante -----------------------------------------------------

def test_dwmapi_manquant_est_un_avertissement(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    install.ue4ss.proxy_dll.unlink()

    d = by_code(doctor.run(install), "ue4ss.proxy_missing")
    assert d.level is Level.WARN
    assert "dwmapi.dll" in d.title
    assert "aucun log" in d.why.lower()


# --- 7. Disposition UE4SS -------------------------------------------------------

def test_layout_imbrique_pour_le_jeu_complet(tmp_path):
    install = make(tmp_path, full=True)
    d = by_code(doctor.run(install), "ue4ss.layout")
    assert d.level is Level.OK
    assert "imbriquée" in d.title
    assert install.ue4ss.nested


def test_layout_a_plat_pour_la_demo(tmp_path):
    install = make(tmp_path, full=False)
    d = by_code(doctor.run(install), "ue4ss.layout")
    assert d.level is Level.OK
    assert "à plat" in d.title
    assert not install.ue4ss.nested


# --- 8. mods.txt vs enabled.txt -------------------------------------------------

def test_mod_marque_zero_mais_actif_est_signale(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    mods_txt = install.ue4ss.mods_txt
    mods_txt.write_text(mods_txt.read_text(encoding="utf-8") + "ue4ss-FESolo : 0\n",
                        encoding="utf-8")

    d = by_code(doctor.run(install), "mods.txt_misleading")
    assert d.level is Level.WARN
    assert "ue4ss-FESolo" in d.detail
    assert "deux passes" in d.why
    assert len(d.options) == 2


def test_mod_marque_zero_option_desactivation_reelle(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    mods_txt = install.ue4ss.mods_txt
    mods_txt.write_text(mods_txt.read_text(encoding="utf-8") + "ue4ss-FESolo : 0\n",
                        encoding="utf-8")

    d = by_code(doctor.run(install), "mods.txt_misleading")
    res = next(o for o in d.options if "Désactiver réellement" in o.label).run()

    assert res.ok, res.message
    assert not (install.ue4ss.mods_dir / "ue4ss-FESolo" / "enabled.txt").exists()
    assert by_code(doctor.run(install), "mods.txt_coherent").level is Level.OK


def test_mod_marque_zero_option_nettoyage_mods_txt(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    mods_txt = install.ue4ss.mods_txt
    mods_txt.write_text(mods_txt.read_text(encoding="utf-8") + "ue4ss-FESolo : 0\n",
                        encoding="utf-8")

    d = by_code(doctor.run(install), "mods.txt_misleading")
    res = next(o for o in d.options if "mods.txt" in o.label).run()

    assert res.ok, res.message
    text = mods_txt.read_text(encoding="utf-8")
    assert "ue4ss-FESolo" not in text
    # Les autres lignes doivent être intactes : on n'a pas réécrit le fichier au propre.
    assert "CheatManagerEnablerMod : 1" in text
    assert "ActorDumperMod : 0" in text
    assert by_code(doctor.run(install), "mods.txt_coherent").level is Level.OK


def test_mod_marque_un_ne_declenche_rien(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    mods_txt = install.ue4ss.mods_txt
    mods_txt.write_text(mods_txt.read_text(encoding="utf-8") + "ue4ss-FESolo : 1\n",
                        encoding="utf-8")

    assert by_code(doctor.run(install), "mods.txt_coherent").level is Level.OK


# --- 9. Édition inconnue --------------------------------------------------------

def test_edition_inconnue_est_un_avertissement(tmp_path):
    install = make(tmp_path, full=True, mods=["ue4ss-FESolo"])
    (install.root / make_fixture.FULL_SHIM).unlink()
    reinspected = inspect(install.root, source="fixture")
    assert reinspected is not None and reinspected.edition is Edition.UNKNOWN

    d = by_code(doctor.run(reinspected), "install.edition_unknown")
    assert d.level is Level.WARN
    assert "shim" in d.why


def test_edition_connue_est_ok(tmp_path):
    d = by_code(doctor.run(make(tmp_path, full=True)), "install.edition")
    assert d.level is Level.OK and "jeu complet" in d.title


# --- Contrat général ------------------------------------------------------------

def test_les_erreurs_remontent_en_tete(tmp_path):
    install = make(tmp_path, full=True, mods=["ue4ss-FEMoonJump", "ue4ss-FEInfiniteCore"])
    install.ue4ss.uehelpers.unlink()
    levels = [d.level for d in doctor.run(install)]

    assert levels == sorted(levels, key=lambda l: {Level.ERROR: 0, Level.WARN: 1,
                                                   Level.OK: 2}[l])
    assert levels[0] is Level.ERROR
    assert doctor.worst(doctor.run(install)) is Level.ERROR


def test_tout_diagnostic_est_renseigne(tmp_path):
    """Un diagnostic sans `why` serait un message d'erreur de plus, pas un diagnostic."""
    install = make(tmp_path, full=True, mods=["ue4ss-FEMoonJump", "ue4ss-FEInfiniteCore"])
    install.ue4ss.proxy_dll.unlink()

    for d in doctor.run(install):
        assert d.code and d.title, d
        assert d.why, f"{d.code} n'explique pas pourquoi ça compte"
        assert isinstance(d.level, Level)
        if d.fix is not None:
            assert d.fix_label, f"{d.code} a un correctif sans libellé"


def test_run_accepte_un_inventaire_deja_charge(tmp_path):
    install = make(tmp_path, full=False, mods=["ue4ss-FESolo"])
    preloaded = mods_mod.load(install.ue4ss)

    assert codes(doctor.run(install, preloaded)) == codes(doctor.run(install))


def test_summary_est_en_francais_et_compte_juste(tmp_path):
    install = make(tmp_path, full=True, mods=["ue4ss-FESolo"])
    text = doctor.summary(doctor.run(install))
    assert "1 erreur(s)" in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
