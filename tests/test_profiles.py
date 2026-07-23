"""Tests des profils : capture, application, rapport détaillé et retour arrière.

Les scénarios prioritaires sont ceux où quelque chose se passe mal — mod absent,
constante disparue, pak manquant — parce que c'est là que l'exigence « ne jamais
interrompre l'application, tout rapporter » se vérifie.
"""

from __future__ import annotations

from pathlib import Path

from fe_launcher.core import luaconf, mods, paks, profiles
from fe_launcher.core.profiles import ActionStatus, Profile
from tests.conftest import write_triplet

MOD_A = "ue4ss-FEInfiniteCore"
MOD_B = "ue4ss-FEMoonJump"
MOD_C = "ue4ss-FESkins"


def _script(install, mod_name: str) -> Path:
    return install.ue4ss.mods_dir / mod_name / "Scripts" / "main.lua"


def _states(install) -> dict[str, mods.ModState]:
    return {m.name: m.state for m in mods.load(install.ue4ss)}


# --- Capture ---------------------------------------------------------------------

def test_capture_photographie_l_etat_courant(install) -> None:
    write_triplet(install.paks_dir, "AA_Alien_P")

    snap = profiles.capture(install, "état actuel")

    assert set(snap.mods_enabled) == {MOD_A, MOD_B, MOD_C}
    assert snap.lua_overrides[MOD_A]["CORE_TYPE"] == "water"
    assert snap.lua_overrides[MOD_A]["VOID_DELAY_MS"] == 1200
    assert snap.paks_enabled == ["AA_Alien_P"]  # le pak de base n'est jamais capturé
    assert snap.source_install == str(install.root)


def test_capture_sans_ue4ss(tmp_path: Path) -> None:
    from tests.conftest import make_install
    inst = make_install(tmp_path / "sansue4ss", with_ue4ss=False)

    snap = profiles.capture(inst, "vide")

    assert snap.mods_enabled == [] and snap.lua_overrides == {}


# --- Persistance -------------------------------------------------------------------

def test_save_load_list_delete(tmp_path: Path) -> None:
    directory = tmp_path / "profils"
    p = Profile(name="campagne ICG", description="mesure du glitch",
                mods_enabled=[MOD_A], lua_overrides={MOD_A: {"VOID_DELAY_MS": 400}},
                paks_enabled=["AA_Alien_P"], fps_lock=60)

    path = profiles.save(p, directory)
    assert path.name == "campagne-ICG.json"

    reloaded = profiles.load(path)
    assert reloaded.name == "campagne ICG"
    assert reloaded.lua_overrides == {MOD_A: {"VOID_DELAY_MS": 400}}
    assert reloaded.fps_lock == 60

    profiles.save(Profile(name="run propre"), directory)
    assert [x.name for x in profiles.list_profiles(directory)] == [
        "campagne ICG", "run propre",
    ]

    assert profiles.delete(directory, "campagne ICG") is True
    assert profiles.delete(directory, "campagne ICG") is False
    assert len(profiles.list_profiles(directory)) == 1


def test_list_profiles_ignore_un_json_corrompu(tmp_path: Path) -> None:
    directory = tmp_path / "profils"
    profiles.save(Profile(name="bon"), directory)
    (directory / "casse.json").write_text("{ pas du json", encoding="utf-8")

    listed = profiles.list_profiles(directory)

    assert [p.name for p in listed] == ["bon"]


# --- Application ---------------------------------------------------------------------

def test_apply_active_desactive_et_ecrit_le_lua(install) -> None:
    profile = Profile(
        name="exploration OOB",
        mods_enabled=[MOD_B],
        lua_overrides={MOD_B: {"CORE_TYPE": "glitch", "VOID_DELAY_MS": 400,
                               "SPAWN_IN_ME": False}},
    )

    report = profiles.apply(profile, install)

    assert report.ok, report.summary()
    states = _states(install)
    assert states[MOD_B] is mods.ModState.ENABLED
    assert states[MOD_A] is mods.ModState.DISABLED   # absent du profil => désactivé
    assert states[MOD_C] is mods.ModState.DISABLED

    script = _script(install, MOD_B)
    assert luaconf.read(script, "CORE_TYPE").value == "glitch"
    assert luaconf.read(script, "VOID_DELAY_MS").value == 400
    assert luaconf.read(script, "SPAWN_IN_ME").value is False
    # Réécriture chirurgicale : le commentaire de domaine doit survivre.
    assert "water|waste|fire|glitch" in script.read_text(encoding="utf-8")


def test_apply_ne_retourne_pas_un_booleen(install) -> None:
    report = profiles.apply(Profile(name="test"), install)

    assert isinstance(report, profiles.ApplyReport)
    assert all(isinstance(a, profiles.Action) for a in report.actions)
    assert "Profil « test »" in report.summary()


def test_mod_absent_n_interrompt_pas_l_application(install) -> None:
    profile = Profile(
        name="profil partagé",
        mods_enabled=[MOD_A, "ue4ss-FEQuiNExistePas"],
        lua_overrides={MOD_A: {"CORE_TYPE": "fire"},
                       "ue4ss-FEQuiNExistePas": {"X": 1}},
    )

    report = profiles.apply(profile, install)

    assert not report.ok
    manques = [a for a in report.failures if "FEQuiNExistePas" in a.target]
    assert len(manques) == 2                      # le mod ET ses réglages
    assert "absent" in manques[0].detail.lower()
    # Le reste a bien été appliqué malgré l'échec.
    assert _states(install)[MOD_A] is mods.ModState.ENABLED
    assert luaconf.read(_script(install, MOD_A), "CORE_TYPE").value == "fire"


def test_constante_disparue_est_signalee_sans_bloquer(install) -> None:
    profile = Profile(
        name="obsolete",
        mods_enabled=[MOD_A],
        lua_overrides={MOD_A: {"CONSTANTE_DISPARUE": 3, "CORE_TYPE": "waste"}},
    )

    report = profiles.apply(profile, install)

    echecs = [a for a in report.failures if a.target.endswith("CONSTANTE_DISPARUE")]
    assert len(echecs) == 1
    assert "introuvable" in echecs[0].detail
    assert luaconf.read(_script(install, MOD_A), "CORE_TYPE").value == "waste"


def test_pak_manquant_est_rapporte(install) -> None:
    report = profiles.apply(Profile(name="p", paks_enabled=["AA_Alien_P"]), install)

    echecs = [a for a in report.failures if a.kind == "pak"]
    assert len(echecs) == 1 and "bibliothèque" in echecs[0].detail


def test_apply_gere_les_paks_sans_toucher_a_ceux_du_jeu(install) -> None:
    write_triplet(install.paks_dir, "AA_Alien_P")
    write_triplet(install.paks_dir, "AutreMod")

    report = profiles.apply(Profile(name="p", paks_enabled=["AA_Alien_P"]), install)

    etat = {p.name: p.enabled for p in paks.installed(install)}
    assert etat["AA_Alien_P"] is True
    assert etat["AutreMod"] is False
    assert etat["UE_YGRO-Windows"] is True        # pak de base : jamais touché
    assert not [a for a in report.actions
                if a.kind == "pak" and a.target == "UE_YGRO-Windows"]


def test_fps_et_save_sont_annonces_comme_non_implementes(install) -> None:
    report = profiles.apply(Profile(name="p", fps_lock=60, save_slot="slot1"), install)

    kinds = {a.kind: a for a in report.skipped}
    assert kinds["fps"].status is ActionStatus.SKIPPED
    assert "non implémenté" in kinds["fps"].detail
    assert "non implémentée" in kinds["save"].detail


def test_conflit_de_touches_detecte_apres_application(install) -> None:
    """FEInfiniteCore et FEMoonJump se disputent F7 — le profil doit le dire."""
    report = profiles.apply(
        Profile(name="conflit", mods_enabled=[MOD_A, MOD_B]), install)

    f7 = [c for c in report.conflicts if c.resource == "F7"]
    assert len(f7) == 1
    assert set(f7[0].mods) == {MOD_A, MOD_B}
    assert "F7" in report.summary()
    # Un conflit n'est pas un échec d'écriture : l'application reste `ok`.
    assert report.ok


def test_sans_ue4ss_l_echec_est_explicite(tmp_path: Path) -> None:
    from tests.conftest import make_install
    inst = make_install(tmp_path / "sansue4ss", with_ue4ss=False)

    report = profiles.apply(Profile(name="p", mods_enabled=[MOD_A]), inst)

    assert not report.ok
    assert "UE4SS n'est pas installé" in report.failures[0].detail


# --- Retour arrière -------------------------------------------------------------------

def test_revert_restaure_mods_paks_et_lua(install) -> None:
    write_triplet(install.paks_dir, "AA_Alien_P")
    avant_states = _states(install)
    avant_lua = _script(install, MOD_A).read_text(encoding="utf-8")

    profile = Profile(
        name="campagne ICG",
        mods_enabled=[MOD_C],
        lua_overrides={MOD_A: {"VOID_DELAY_MS": 400, "CORE_TYPE": "glitch"}},
    )
    report = profiles.apply(profile, install)
    assert report.snapshot is not None
    assert luaconf.read(_script(install, MOD_A), "VOID_DELAY_MS").value == 400
    assert {p.name: p.enabled for p in paks.installed(install)}["AA_Alien_P"] is False

    back = profiles.revert(report, install)

    assert back.ok, back.summary()
    assert _states(install) == avant_states
    assert _script(install, MOD_A).read_text(encoding="utf-8") == avant_lua
    assert {p.name: p.enabled for p in paks.installed(install)}["AA_Alien_P"] is True


def test_revert_sans_instantane(install) -> None:
    report = profiles.apply(Profile(name="p"), install, snapshot=False)
    assert report.snapshot is None

    back = profiles.revert(report, install)

    assert not back.ok
    assert "retour arrière impossible" in back.failures[0].detail


def test_rapport_serialisable_pour_survivre_a_une_fermeture(install, tmp_path: Path) -> None:
    profile = Profile(name="campagne ICG", mods_enabled=[MOD_A, MOD_B],
                      lua_overrides={MOD_A: {"VOID_DELAY_MS": 400}})
    report = profiles.apply(profile, install)
    path = tmp_path / "rapport.json"
    report.save(path)

    relu = profiles.ApplyReport.load(path)

    assert relu.profile == "campagne ICG"
    assert len(relu.actions) == len(report.actions)
    assert [c.resource for c in relu.conflicts] == [c.resource for c in report.conflicts]
    assert relu.snapshot is not None

    # Le rapport rechargé doit suffire à revenir en arrière.
    back = profiles.revert(relu, install)
    assert back.ok, back.summary()
    assert luaconf.read(_script(install, MOD_A), "VOID_DELAY_MS").value == 1200
