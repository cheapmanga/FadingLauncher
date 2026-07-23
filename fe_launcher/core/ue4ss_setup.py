"""Installation d'UE4SS et correctif du chemin grec, en une seule opération.

Ce module répond au bouton « Installer UE4SS » : il enchaîne, dans le bon ordre, tout ce
qu'il faut pour qu'un possesseur du jeu complet passe d'une install nue à une install
qui charge les mods.

    1. déposer UE4SS (dwmapi.dll + dossier ue4ss/) dans Binaries/Win64 ;
    2. corriger le chemin grec `Project Ygrό` qui, sinon, tue UE4SS au démarrage.

L'ordre compte : on installe UE4SS AVANT de renommer, parce que le renommage change le
chemin d'install ; l'inverse obligerait à retrouver le nouveau dossier.

Tout passe par le journal, donc l'ensemble est réversible et défait à la désinstallation.
La source d'UE4SS est un fichier .zip que l'utilisateur fournit (ou qui a été téléchargé
au préalable) : on ne code pas d'URL en dur, les liens de la build zDEV utilisée changent,
et un téléchargement silencieux d'un binaire injecté dans le jeu mérite que l'utilisateur
choisisse explicitement son fichier.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import doctor
from .ledger import Ledger
from .paths import GameInstall

LEDGER_GROUP = "ue4ss-setup"

# Fichiers/dossiers qui prouvent qu'une archive est bien UE4SS.
_UE4SS_MARKERS = ("dwmapi.dll", "UE4SS-settings.ini")

# Dépôt officiel d'UE4SS. On télécharge l'asset .zip de la dernière release plutôt que de
# coder une URL en dur : les numéros de version changent, l'API des releases non.
UE4SS_RELEASES_API = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/latest"


@dataclass
class DownloadResult:
    ok: bool
    path: Path | None
    version: str = ""
    message: str = ""


def _pick_asset(assets: list[dict]) -> dict | None:
    """Choisit le meilleur .zip d'une release UE4SS.

    On préfère le build standard `UE4SS_v*.zip` : plus léger (~5 Mo) et suffisant pour
    des mods Lua, qui sont les seuls qu'on embarque. Les variantes `z*` (zDEV, zCustom,
    zMapGen) sont des extras — on ne les prend qu'à défaut de build standard.
    """
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    if not zips:
        return None
    standard = [a for a in zips
                if a["name"].lower().startswith("ue4ss_")
                and not a["name"].lower().startswith("z")]
    return (standard or zips)[0]


def download_ue4ss(dest_dir: Path, *, timeout: int = 60) -> DownloadResult:
    """Télécharge la dernière release d'UE4SS depuis GitHub, dans `dest_dir`.

    L'utilisateur n'a plus rien à fournir : le launcher va chercher UE4SS tout seul.
    Échoue proprement (sans lever) en cas d'absence de réseau ou d'API indisponible —
    l'assistant propose alors de fournir un .zip à la main en repli.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(
            UE4SS_RELEASES_API,
            headers={"User-Agent": "fe-launcher",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            release = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return DownloadResult(False, None,
                              message=f"Téléchargement impossible (pas de réseau ?) : {exc}")

    asset = _pick_asset(release.get("assets", []))
    if asset is None:
        return DownloadResult(False, None, release.get("tag_name", ""),
                              "Aucune archive UE4SS dans la dernière release.")

    out = dest_dir / asset["name"]
    try:
        req = urllib.request.Request(asset["browser_download_url"],
                                     headers={"User-Agent": "fe-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as r, out.open("wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        return DownloadResult(False, None, release.get("tag_name", ""),
                              f"Échec du téléchargement de l'archive : {exc}")

    if not looks_like_ue4ss_zip(out):
        return DownloadResult(False, None, release.get("tag_name", ""),
                              "L'archive téléchargée ne ressemble pas à UE4SS.")
    return DownloadResult(True, out, release.get("tag_name", ""),
                          f"UE4SS {release.get('tag_name', '')} téléchargé.")


@dataclass
class SetupStep:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class SetupReport:
    ok: bool
    steps: list[SetupStep] = field(default_factory=list)
    message: str = ""

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.steps.append(SetupStep(label, ok, detail))


def looks_like_ue4ss_zip(zip_path: Path) -> bool:
    """L'archive contient-elle bien UE4SS ? Évite d'extraire n'importe quoi dans le jeu."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = "\n".join(z.namelist()).lower()
    except (OSError, zipfile.BadZipFile):
        return False
    return all(m.lower() in names for m in _UE4SS_MARKERS)


def _safe_members(z: zipfile.ZipFile, dest: Path) -> list[zipfile.ZipInfo]:
    """Membres de l'archive dont l'extraction reste SOUS `dest`.

    Un zip peut contenir des chemins `../…` ou absolus (zip-slip) qui écriraient hors
    du dossier cible. On rejette ces membres plutôt que de leur faire confiance.
    """
    dest = dest.resolve()
    out = []
    for info in z.infolist():
        target = (dest / info.filename).resolve()
        if target == dest or dest in target.parents:
            out.append(info)
    return out


def install_ue4ss(install: GameInstall, zip_path: Path, ledger: Ledger,
                  report: SetupReport) -> bool:
    """Extrait UE4SS dans Binaries/Win64. Chaque fichier créé est journalisé.

    On n'écrase JAMAIS un UE4SS déjà présent : si `UE4SS-settings.ini` existe, on
    considère l'install faite et on ne touche à rien (la config de l'utilisateur pourrait
    être personnalisée).
    """
    if install.has_ue4ss:
        report.add("UE4SS déjà présent", True, "aucune réinstallation.")
        return True
    if not looks_like_ue4ss_zip(zip_path):
        report.add("Archive UE4SS invalide", False,
                   "le .zip ne contient pas dwmapi.dll + UE4SS-settings.ini.")
        return False

    win64 = install.engine_dir
    try:
        with zipfile.ZipFile(zip_path) as z:
            members = _safe_members(z, win64)
            for info in members:
                if info.is_dir():
                    continue
                target = win64 / info.filename
                data = z.read(info)
                # create_file écrit puis journalise : réversible, et refuse d'écraser un
                # fichier existant sans le sauvegarder.
                ledger.create_file(target, data,
                                   label=f"UE4SS : {info.filename}", group=LEDGER_GROUP)
    except (OSError, zipfile.BadZipFile) as exc:
        report.add("Extraction d'UE4SS", False, str(exc))
        return False

    report.add("UE4SS installé", True, f"extrait dans {win64.name}\\")
    _deploy_signatures(win64, ledger, report)
    return True


def _bundled_signatures_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "fe_launcher" / "resources" / "ue4ss_signatures"
    return Path(__file__).resolve().parent.parent / "resources" / "ue4ss_signatures"


def _deploy_signatures(win64: Path, ledger: Ledger, report: SetupReport) -> None:
    """Dépose les signatures custom nécessaires à Fading Echo à côté d'UE4SS-settings.ini.

    Pourquoi c'est indispensable : sur Fading Echo, le scan automatique d'UE4SS ne trouve
    PAS `StaticConstructObject_Internal` (vérifié sur le log réel : il est résolu « <- Lua
    Script », donc par une signature custom). Sans elle, tout mod qui fait apparaître un
    objet — les cores, par exemple — échoue. Le zip standard d'UE4SS ne la contient pas.

    UE4SS cherche ces fichiers dans `UE4SS_Signatures/` À CÔTÉ de son `UE4SS-settings.ini`.
    On repère donc où le settings a atterri (à plat dans Win64, ou dans Win64/ue4ss) et on
    dépose la signature là.
    """
    src = _bundled_signatures_dir()
    if not src.is_dir():
        return
    # Où est UE4SS-settings.ini ? c'est le dossier de travail d'UE4SS.
    for base in (win64 / "ue4ss", win64):
        if (base / "UE4SS-settings.ini").is_file():
            target_dir = base / "UE4SS_Signatures"
            for sig in src.glob("*.lua"):
                ledger.create_file(target_dir / sig.name, sig.read_bytes(),
                                   label=f"signature UE4SS : {sig.name}", group=LEDGER_GROUP)
            report.add("Signatures Fading Echo", True,
                       "StaticConstructObject déployée (spawn d'objets).")
            return


def run(install: GameInstall, ledger: Ledger, *,
        ue4ss_zip: Path | None = None,
        download_dir: Path | None = None,
        allow_download: bool = True,
        probe=doctor.steam_processes_running) -> SetupReport:
    """Installe UE4SS puis corrige le chemin grec au besoin.

    UE4SS est TÉLÉCHARGÉ automatiquement depuis GitHub si aucune archive n'est fournie et
    que le jeu n'en a pas encore — l'utilisateur n'a rien à donner. Un `ue4ss_zip` fourni
    prend le pas sur le téléchargement (utile hors ligne ou pour une version précise).

    Retourne un rapport détaillé étape par étape.
    """
    report = SetupReport(ok=True)

    # 1. UE4SS : archive fournie, sinon téléchargement automatique.
    if not install.has_ue4ss and ue4ss_zip is None and allow_download:
        dest = download_dir or (Path(ledger.root) / "downloads")
        dl = download_ue4ss(dest)
        report.add("Téléchargement d'UE4SS", dl.ok, dl.message)
        if dl.ok:
            ue4ss_zip = dl.path
        else:
            report.ok = False

    if ue4ss_zip is not None:
        if not install_ue4ss(install, Path(ue4ss_zip), ledger, report):
            report.ok = False
    elif not install.has_ue4ss:
        report.add("UE4SS à installer", False,
                   "aucune archive et téléchargement indisponible. Réessayez avec une "
                   "connexion, ou fournissez le .zip d'UE4SS.")

    # 2. Correctif du chemin grec, uniquement s'il est nécessaire.
    if install.non_ascii_path:
        result = doctor.fix_non_ascii_path(install, probe=probe, ledger=ledger)
        report.add("Correctif du chemin non-ASCII", result.ok, result.message)
        if not result.ok:
            report.ok = False
    else:
        report.add("Chemin d'install", True, "déjà en ASCII, aucun correctif nécessaire.")

    done = sum(1 for s in report.steps if s.ok)
    report.message = (f"{done}/{len(report.steps)} étape(s) réussie(s). "
                      + ("Relancez le jeu via le launcher." if report.ok
                         else "Certaines étapes ont échoué — voir le détail."))
    return report
