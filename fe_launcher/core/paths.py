"""Découverte de l'installation de Fading Echo et de la disposition d'UE4SS.

Tout ce module repose sur des faits vérifiés dans les logs UE4SS du PC de jeu
(glitch-hunting/AZAMA logs et tout/fini/) et le dump PICS Steam. Les points qui
n'ont PAS pu être vérifiés sont signalés en commentaire — ne pas les durcir sans
les avoir testés sur une vraie install.

Fait structurant n°1 : la disposition d'UE4SS DIFFÈRE entre la démo et le jeu complet.
    DEMO    ...\\Fading Echo Demo\\UE_YGRO\\Binaries\\Win64\\           (à plat)
    COMPLET ...\\Project Ygrό\\UE_YGRO\\Binaries\\Win64\\ue4ss\\        (sous-dossier)
Ne jamais coder `ue4ss\\` en dur : on cherche UE4SS-settings.ini aux deux endroits.

Fait structurant n°2 : l'exe lancé par Steam n'est pas l'exe du moteur. Steam lance
un shim (FadingEcho.exe, ~180 Ko) qui démarre UE_YGRO_Steam-Win64-Shipping.exe (~176 Mo).
Ce que fait exactement le shim n'est PAS documenté — d'où le mode de lancement par
défaut via Steam, qui est le seul chemin dont on sait qu'il fonctionne.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

APPID = 2467880

UE_EXE = "UE_YGRO_Steam-Win64-Shipping.exe"
FULL_SHIM = "FadingEcho.exe"
DEMO_SHIM = "FadingEchoDemo.exe"
SETTINGS_INI = "UE4SS-settings.ini"

# Sous-chemin du moteur, commun aux deux éditions.
ENGINE_SUBPATH = Path("UE_YGRO") / "Binaries" / "Win64"
PAKS_SUBPATH = Path("UE_YGRO") / "Content" / "Paks"


class Edition(Enum):
    DEMO = "demo"
    FULL = "full"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Ue4ssLayout:
    """Où vit UE4SS pour une install donnée."""

    root: Path            # dossier contenant UE4SS-settings.ini
    mods_dir: Path        # <root>/Mods
    settings_ini: Path
    mods_txt: Path        # <root>/Mods/mods.txt (peut ne pas exister)
    shared_dir: Path      # <root>/Mods/shared — contient UEHelpers
    proxy_dll: Path       # dwmapi.dll, dans Win64 quelle que soit la disposition
    nested: bool          # True si layout `ue4ss/` (jeu complet), False si à plat (démo)

    @property
    def uehelpers(self) -> Path:
        return self.shared_dir / "UEHelpers" / "UEHelpers.lua"

    @property
    def installed(self) -> bool:
        return self.settings_ini.is_file()


@dataclass(frozen=True)
class GameInstall:
    """Une installation de Fading Echo localisée sur disque."""

    root: Path                     # dossier racine (celui qui porte le shim)
    edition: Edition
    engine_dir: Path               # ...\UE_YGRO\Binaries\Win64
    engine_exe: Path
    shim_exe: Path | None
    paks_dir: Path
    ue4ss: Ue4ssLayout | None = None
    source: str = "unknown"        # comment on l'a trouvée (steam, manuel, fixture)

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def has_ue4ss(self) -> bool:
        return self.ue4ss is not None and self.ue4ss.installed

    @property
    def non_ascii_path(self) -> bool:
        """Le chemin contient-il un caractère hors ASCII ?

        C'est LA cause du crash `No mapping for the Unicode character exists in the
        target multi-byte code page` : UE4SS convertit son propre chemin en multi-byte
        pour initialiser Lua, et l'omicron grec de `Project Ygrό` n'existe pas en
        page de codes 850/1252. Vérifié : la démo (ASCII pur) charge la même install
        d'UE4SS sans erreur.
        """
        return any(ord(ch) > 127 for ch in str(self.root))

    def offending_chars(self) -> list[tuple[str, str, str]]:
        """(caractère, U+XXXX, nom unicode) pour chaque caractère non-ASCII du chemin."""
        out = []
        for ch in str(self.root):
            if ord(ch) > 127:
                try:
                    name = unicodedata.name(ch)
                except ValueError:
                    name = "?"
                out.append((ch, f"U+{ord(ch):04X}", name))
        return out


def _detect_ue4ss(engine_dir: Path) -> Ue4ssLayout | None:
    """Cherche UE4SS aux deux emplacements possibles, imbriqué d'abord.

    On teste `ue4ss/` en premier parce que c'est la disposition du jeu complet ;
    si les deux existent (install bâtarde), l'imbriquée l'emporte, ce qui correspond
    à ce que fait UE4SS lui-même d'après les logs.
    """
    for nested in (True, False):
        root = engine_dir / "ue4ss" if nested else engine_dir
        if (root / SETTINGS_INI).is_file():
            mods = root / "Mods"
            return Ue4ssLayout(
                root=root,
                mods_dir=mods,
                settings_ini=root / SETTINGS_INI,
                mods_txt=mods / "mods.txt",
                shared_dir=mods / "shared",
                proxy_dll=engine_dir / "dwmapi.dll",
                nested=nested,
            )
    return None


def _edition_of(root: Path) -> tuple[Edition, Path | None]:
    if (root / FULL_SHIM).is_file():
        return Edition.FULL, root / FULL_SHIM
    if (root / DEMO_SHIM).is_file():
        return Edition.DEMO, root / DEMO_SHIM
    # Repli sur le nom du dossier : la démo est en ASCII pur, le jeu complet non.
    if "demo" in root.name.lower():
        return Edition.DEMO, None
    return Edition.UNKNOWN, None


def inspect(root: Path, *, source: str = "manuel") -> GameInstall | None:
    """Construit un GameInstall depuis une racine supposée. None si ce n'en est pas une."""
    root = Path(root)
    engine_dir = root / ENGINE_SUBPATH
    engine_exe = engine_dir / UE_EXE
    if not engine_exe.is_file():
        return None

    edition, shim = _edition_of(root)
    return GameInstall(
        root=root,
        edition=edition,
        engine_dir=engine_dir,
        engine_exe=engine_exe,
        shim_exe=shim,
        paks_dir=root / PAKS_SUBPATH,
        ue4ss=_detect_ue4ss(engine_dir),
        source=source,
    )


# --- Découverte via Steam -------------------------------------------------------

_VDF_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')
_ACF_INSTALLDIR_RE = re.compile(r'"installdir"\s+"([^"]+)"')


def _steam_root() -> Path | None:
    """Racine de l'install Steam. Windows uniquement en pratique."""
    if sys.platform == "win32":
        try:
            import winreg  # noqa: PLC0415 — import conditionnel volontaire
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for value in ("SteamPath", "InstallPath"):
                            try:
                                p = Path(winreg.QueryValueEx(k, value)[0])
                                if p.is_dir():
                                    return p
                            except OSError:
                                continue
                except OSError:
                    continue
        except ImportError:
            pass
        for guess in (Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")):
            if guess.is_dir():
                return guess
        return None

    # Linux/dev : utile surtout pour les tests, le launcher cible Windows.
    for guess in (Path.home() / ".steam" / "steam",
                  Path.home() / ".local" / "share" / "Steam"):
        if guess.is_dir():
            return guess
    return None


def steam_libraries(steam_root: Path) -> list[Path]:
    """Tous les dossiers `steamapps`, bibliothèques secondaires comprises.

    Le jeu est typiquement sur une autre partition que Steam (E:\\SteamLibrary dans
    les logs du PC de jeu), donc lire libraryfolders.vdf n'est pas optionnel.
    """
    libs = [steam_root / "steamapps"]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for m in _VDF_PATH_RE.finditer(text):
            p = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
            if p.is_dir() and p not in libs:
                libs.append(p)
    return [p for p in libs if p.is_dir()]


def from_manifest(steamapps: Path, appid: int = APPID) -> Path | None:
    """Racine du jeu d'après appmanifest_<appid>.acf, ou None."""
    acf = steamapps / f"appmanifest_{appid}.acf"
    if not acf.is_file():
        return None
    try:
        m = _ACF_INSTALLDIR_RE.search(acf.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not m:
        return None
    root = steamapps / "common" / m.group(1)
    return root if root.is_dir() else None


def discover(extra_roots: list[Path] | None = None) -> list[GameInstall]:
    """Trouve toutes les installs de FE : manifeste Steam, scan des bibliothèques,
    puis racines fournies à la main. Dédoublonné, ordre stable."""
    found: dict[Path, GameInstall] = {}

    def add(root: Path, source: str) -> None:
        inst = inspect(root, source=source)
        if inst is not None:
            found.setdefault(inst.root.resolve(), inst)

    steam = _steam_root()
    if steam is not None:
        for steamapps in steam_libraries(steam):
            root = from_manifest(steamapps, APPID)
            if root is not None:
                add(root, "steam:manifest")
            # La démo a son propre appid, non documenté dans nos sources : on scanne
            # `common/` par nom plutôt que de deviner un appid.
            common = steamapps / "common"
            if common.is_dir():
                try:
                    entries = list(common.iterdir())
                except OSError:
                    entries = []
                for child in entries:
                    if child.is_dir() and (
                        "fading echo" in child.name.lower()
                        or child.name.startswith("Project Ygr")
                    ):
                        add(child, "steam:scan")

    for root in (extra_roots or []):
        add(Path(root), "manuel")

    return list(found.values())
