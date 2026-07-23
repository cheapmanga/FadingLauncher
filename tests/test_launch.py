"""Tests du lancement — intégralement en `dry_run`.

Le poste de dev n'a ni Windows, ni Steam, ni le jeu : on ne teste donc jamais un vrai
démarrage, seulement la commande construite, les avertissements produits et le
comportement dégradé quand Steam ou l'inspection des process sont indisponibles.
"""

from __future__ import annotations

import pytest

from fe_launcher.core import launch
from fe_launcher.core.launch import LaunchMode
from fe_launcher.core.paths import APPID


@pytest.fixture
def steam_ok(monkeypatch):
    """Simule un ouvreur d'URL disponible (absent de cette machine de dev)."""
    monkeypatch.setattr(launch, "_url_opener", lambda: "/usr/bin/xdg-open")


def test_appid_et_url(install) -> None:
    assert APPID == 2467880
    assert launch.STEAM_URL == "steam://rungameid/2467880"


def test_mode_par_defaut_est_steam(install, steam_ok) -> None:
    result = launch.launch(install, dry_run=True)

    assert result.mode is LaunchMode.STEAM
    assert launch.STEAM_URL in result.command
    assert result.ok and result.started is False   # dry_run : rien n'a été exécuté
    assert result.warnings == []                   # seul mode vérifié : aucune réserve


def test_seul_le_mode_steam_est_verifie() -> None:
    assert LaunchMode.STEAM.verified
    assert not LaunchMode.SHIM.verified
    assert not LaunchMode.ENGINE.verified
    assert "non vérifié" in LaunchMode.SHIM.label
    assert "non vérifié" in LaunchMode.ENGINE.label


def test_mode_shim_avertit_et_pointe_le_shim(install) -> None:
    result = launch.launch(install, LaunchMode.SHIM, dry_run=True)

    assert result.ok
    assert result.command[0].endswith("FadingEcho.exe")
    assert result.cwd == install.root
    assert any("jamais été vérifié" in w for w in result.warnings)


def test_mode_shim_demo(demo_install) -> None:
    result = launch.launch(demo_install, LaunchMode.SHIM, dry_run=True)
    assert result.command[0].endswith("FadingEchoDemo.exe")


def test_mode_engine_court_circuite_le_shim(install) -> None:
    result = launch.launch(install, LaunchMode.ENGINE, dry_run=True)

    assert result.command[0].endswith("UE_YGRO_Steam-Win64-Shipping.exe")
    assert result.cwd == install.engine_dir
    assert any("court-circuité" in w for w in result.warnings)


def test_arguments_marques_non_verifies(install) -> None:
    result = launch.launch(install, LaunchMode.ENGINE, args=("-log", "-windowed"),
                           dry_run=True)

    assert result.command[-2:] == ["-log", "-windowed"]
    assert any("non vérifiés sur ce jeu" in w for w in result.warnings)


def test_arguments_ignores_en_mode_steam(install, steam_ok) -> None:
    result = launch.launch(install, LaunchMode.STEAM, args=("-log",), dry_run=True)

    assert "-log" not in result.command
    assert any("ne sont pas transmis" in w for w in result.warnings)


def test_steam_indisponible_donne_une_erreur_lisible(install, monkeypatch) -> None:
    monkeypatch.setattr(launch, "_url_opener", lambda: None)
    monkeypatch.setattr(launch, "_steam_root", lambda: None)

    result = launch.launch(install, LaunchMode.STEAM, dry_run=True)

    assert not result.ok
    assert not result.started
    assert "Steam" in result.error
    assert "non vérifié" in result.error   # on oriente vers le repli, sans le survendre


def test_shim_absent(install, monkeypatch) -> None:
    install.shim_exe.unlink()
    result = launch.launch(install, LaunchMode.SHIM, dry_run=True)
    assert not result.ok and "introuvable" in result.error


def test_engine_absent(install) -> None:
    install.engine_exe.unlink()
    result = launch.launch(install, LaunchMode.ENGINE, dry_run=True)
    assert not result.ok and "moteur est introuvable" in result.error


def test_sans_installation_les_modes_directs_echouent() -> None:
    result = launch.launch(None, LaunchMode.SHIM, dry_run=True)
    assert not result.ok and "Aucune installation" in result.error


def test_command_line_lisible(install) -> None:
    result = launch.launch(install, LaunchMode.ENGINE, dry_run=True)
    assert result.command_line.startswith('"')  # chemin fixture avec espaces
    assert "UE_YGRO_Steam-Win64-Shipping.exe" in result.command_line


def test_is_running_degrade_proprement() -> None:
    """Sur le poste de dev, le jeu ne tourne pas : la réponse doit être False, sans
    exception, que l'inspection des process soit possible ou non."""
    probe = launch.probe_processes()

    assert isinstance(probe.supported, bool)
    assert probe.running is False
    assert launch.is_running() is False
    if not probe.supported:
        assert probe.reason  # on doit toujours pouvoir dire pourquoi on ne sait pas


def test_probe_sans_outil_systeme(monkeypatch) -> None:
    monkeypatch.setattr(launch.shutil, "which", lambda _: None)
    monkeypatch.setattr(launch.sys, "platform", "linux")

    probe = launch.probe_processes()

    assert probe.supported is False
    assert probe.running is False
    assert "pgrep" in probe.reason


def test_probe_gere_un_echec_systeme(monkeypatch) -> None:
    def boom(*a, **k):
        raise OSError("plus de descripteurs")

    monkeypatch.setattr(launch.shutil, "which", lambda _: "/usr/bin/pgrep")
    monkeypatch.setattr(launch.subprocess, "run", boom)

    probe = launch.probe_processes()
    assert probe.supported is False and "impossible" in probe.reason


def test_build_command_est_utilisable_sans_lancer(install) -> None:
    command, cwd, warnings = launch.build_command(install, LaunchMode.SHIM)
    assert command and cwd == install.root and warnings
