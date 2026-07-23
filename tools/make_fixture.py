"""Génère une fausse installation de Fading Echo pour tester le launcher sans le jeu.

Le poste de dev n'a ni le jeu ni Windows. Toute la logique de détection de chemins,
d'activation de mods et de diagnostic doit donc pouvoir tourner contre une arborescence
fabriquée, reproduisant fidèlement les deux layouts réellement observés dans les logs
UE4SS du PC de jeu (cf. glitch-hunting/AZAMA logs et tout/fini/).

Deux layouts, vérifiés sur logs :
  DEMO    <root>/UE_YGRO/Binaries/Win64/{UE4SS-settings.ini, Mods/}
  COMPLET <root>/UE_YGRO/Binaries/Win64/ue4ss/{UE4SS-settings.ini, Mods/}

Le nom du dossier du jeu complet contient un omicron tonos grec (U+03CC) qui casse
UE4SS sur une machine en page de codes 850/1252 — le fixture le reproduit tel quel
pour que le Doctor puisse être testé sur le vrai cas.

Usage:
    python tools/make_fixture.py <dest> [--variant demo|full|both]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Le vrai nom d'install du jeu complet, avec l'omicron tonos grec U+03CC (UTF-8 cf 8c).
# Source : pics_snapshot.json "installdir", et les logs UE4SS du PC de jeu.
FULL_DIRNAME = "Project Ygrό"
DEMO_DIRNAME = "Fading Echo Demo"

# Le shim lancé par Steam n'est PAS l'exe UE (183 Ko contre 176 Mo).
FULL_SHIM = "FadingEcho.exe"
DEMO_SHIM = "FadingEchoDemo.exe"
UE_EXE = "UE_YGRO_Steam-Win64-Shipping.exe"

APPID = 2467880

# Contenu minimal réaliste d'UE4SS-settings.ini. Les clés [Debug] sont celles
# dont les noms sont sourcés ; on ne fabrique pas de clés non vérifiées.
SETTINGS_INI = """\
[Overrides]
ModsFolderPath =

[General]
EnableHotReloadSystem = 0
UseCache = 1
InvalidObjectIndex = 0
GuiConsoleEnabled = 1
GuiConsoleVisible = 1

[EngineVersionOverride]
MajorVersion =
MinorVersion =

[Debug]
SimpleConsoleEnabled = 1
DebugConsoleEnabled = 1
DebugConsoleVisible = 1
RenderMode = ExternalThread
"""

# mods.txt : les mods livrés avec UE4SS, avec ordre de chargement et flag 0/1.
# Reproduit la structure réellement observée dans le log du PC de jeu.
MODS_TXT = """\
CheatManagerEnablerMod : 1
ActorDumperMod : 0
ConsoleCommandsMod : 1
ConsoleEnablerMod : 1
SplitScreenMod : 0
LineTraceMod : 1
BPML_GenericFunctions : 1
BPModLoaderMod : 1
jsbLuaProfilerMod : 0
FadingEchoTrainer : 1
Keybinds : 1
"""

# Un mod Lua d'exemple, avec des constantes de config en tête au format que le
# launcher doit savoir réécrire (`local NOM = valeur -- commentaire`).
SAMPLE_MOD_LUA = """\
-- Mod d'exemple pour les tests du launcher.
local VOID_DELAY_MS = 1200         -- delai grab -> void
local CORE_TYPE     = "water"      -- water|waste|fire|glitch
local SPAWN_IN_ME   = true         -- true = core spawne a ma position
local RISE_SPEED    = 700.0        -- vitesse de montee

RegisterKeyBind(Key.F7, function() end)
RegisterConsoleCommandGlobalHandler("demo", function() end)
"""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _stub_exe(path: Path, size: int) -> None:
    """Écrit un faux exe. La taille distingue le shim (~180 Ko) de l'exe UE (~176 Mo),
    mais on reste petit sur disque : seul l'ordre de grandeur importe pour les tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * (size - 2))


def build_install(dest: Path, *, full: bool, with_ue4ss: bool = True,
                  mods: list[str] | None = None) -> Path:
    """Fabrique une install. Retourne la racine du jeu."""
    root = dest / (FULL_DIRNAME if full else DEMO_DIRNAME)
    win64 = root / "UE_YGRO" / "Binaries" / "Win64"

    _stub_exe(root / (FULL_SHIM if full else DEMO_SHIM), 4096)
    _stub_exe(win64 / UE_EXE, 8192)

    # Content/Paks : là où vont les paks custom (seul chemin sourcé).
    (root / "UE_YGRO" / "Content" / "Paks").mkdir(parents=True, exist_ok=True)
    _stub_exe(root / "UE_YGRO" / "Content" / "Paks" / "UE_YGRO-Windows.pak", 2048)

    if with_ue4ss:
        # LA différence structurante entre les deux layouts.
        ue4ss_root = win64 / "ue4ss" if full else win64
        _write(ue4ss_root / "UE4SS-settings.ini", SETTINGS_INI)
        _write(ue4ss_root / "Mods" / "mods.txt", MODS_TXT)
        # dwmapi.dll = la DLL proxy qui charge UE4SS.
        _stub_exe(win64 / "dwmapi.dll", 1024)
        # UEHelpers : sans lui, 19 mods sur 20 échouent au chargement.
        _write(ue4ss_root / "Mods" / "shared" / "UEHelpers" / "UEHelpers.lua",
               "-- stub UEHelpers\nreturn {}\n")

        for name in (mods or []):
            mod_dir = ue4ss_root / "Mods" / name
            _write(mod_dir / "Scripts" / "main.lua", SAMPLE_MOD_LUA)
            (mod_dir / "enabled.txt").write_bytes(b"")  # marqueur vide

    return root


def build_steam_library(dest: Path, *, installdir: str) -> None:
    """Fabrique le manifeste Steam qui permet de retrouver l'install."""
    steamapps = dest
    _write(steamapps / f"appmanifest_{APPID}.acf",
           '"AppState"\n'
           '{\n'
           f'\t"appid"\t\t"{APPID}"\n'
           '\t"name"\t\t"Fading Echo"\n'
           f'\t"installdir"\t\t"{installdir}"\n'
           '}\n')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dest", type=Path, help="dossier de destination")
    ap.add_argument("--variant", choices=("demo", "full", "both"), default="both")
    ap.add_argument("--clean", action="store_true", help="vider la destination d'abord")
    args = ap.parse_args(argv)

    dest: Path = args.dest
    if args.clean and dest.exists():
        shutil.rmtree(dest)

    common = dest / "steamapps" / "common"
    sample_mods = ["ue4ss-FEInfiniteCore", "ue4ss-FEMoonJump", "ue4ss-FESkins"]

    made = []
    if args.variant in ("demo", "both"):
        made.append(build_install(common, full=False, mods=sample_mods))
    if args.variant in ("full", "both"):
        made.append(build_install(common, full=True, mods=sample_mods))
        build_steam_library(dest / "steamapps", installdir=FULL_DIRNAME)

    for root in made:
        print(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
