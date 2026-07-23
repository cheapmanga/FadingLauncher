"""Branchement Steam : garde-fous et réversibilité."""
from __future__ import annotations

from pathlib import Path

import pytest

from fe_launcher.core import steamcfg
from fe_launcher.core.ledger import Ledger

VDF = '''"UserLocalConfigStore"
{
\t"Software" { "Valve" { "Steam" { "apps"
\t{
\t\t"2467880"
\t\t{
\t\t\t"LaunchOptions"\t\t"-existant"
\t\t}
\t\t"440"
\t\t{
\t\t\t"LaunchOptions"\t\t"-autre"
\t\t}
\t}}}}
}
'''


@pytest.fixture
def steam(tmp_path):
    cfg = tmp_path / "userdata" / "123" / "config" / "localconfig.vdf"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(VDF, encoding="utf-8")
    return tmp_path, cfg


def test_launch_line_cite_les_chemins_avec_espace():
    assert steamcfg.launch_line("/opt/FE Launcher/fe.exe") == '"/opt/FE Launcher/fe.exe" %command%'
    assert steamcfg.launch_line("/opt/fe.exe") == "/opt/fe.exe %command%"


def test_refuse_si_steam_tourne_ou_inconnu(steam, tmp_path):
    root, cfg = steam
    led = Ledger(tmp_path / "led")
    orig = cfg.read_text()
    for running in (True, None):
        r = steamcfg.wire("/opt/fe.exe", led, steam_running=running, steam_root=root)
        assert not r.ok
        assert r.line  # la ligne manuelle est toujours donnée
        assert cfg.read_text() == orig  # rien touché
    assert led.pending == []


def test_branche_et_preserve_les_autres_jeux(steam, tmp_path):
    root, cfg = steam
    led = Ledger(tmp_path / "led")
    r = steamcfg.wire("/opt/fe.exe", led, steam_running=False, steam_root=root)
    assert r.ok
    assert "/opt/fe.exe" in steamcfg.read_launch_options(cfg)
    assert '"-autre"' in cfg.read_text()  # l'autre jeu n'a pas bougé


def test_debranchement_restaure_a_loctet(steam, tmp_path):
    root, cfg = steam
    led = Ledger(tmp_path / "led")
    orig = cfg.read_text()
    steamcfg.wire("/opt/fe.exe", led, steam_running=False, steam_root=root)
    assert cfg.read_text() != orig
    steamcfg.unwire(led)
    assert cfg.read_text() == orig


def test_sans_config_steam_repli_manuel(tmp_path):
    led = Ledger(tmp_path / "led")
    r = steamcfg.wire("/opt/fe.exe", led, steam_running=False, steam_root=tmp_path)
    assert not r.ok
    assert r.line  # repli manuel fourni


def test_commande_transmise_par_steam():
    assert steamcfg.parse_forwarded_command(["fe.exe", "jeu.exe", "-a"]) == ["jeu.exe", "-a"]
    assert steamcfg.parse_forwarded_command(["fe.exe"]) is None
