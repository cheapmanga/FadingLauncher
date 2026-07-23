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

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import doctor
from .ledger import Ledger
from .paths import GameInstall

LEDGER_GROUP = "ue4ss-setup"

# Fichiers/dossiers qui prouvent qu'une archive est bien UE4SS.
_UE4SS_MARKERS = ("dwmapi.dll", "UE4SS-settings.ini")


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
    return True


def run(install: GameInstall, ledger: Ledger, *,
        ue4ss_zip: Path | None = None,
        probe=doctor.steam_processes_running) -> SetupReport:
    """Installe UE4SS (si un zip est fourni) puis corrige le chemin grec au besoin.

    Retourne un rapport détaillé étape par étape : l'utilisateur voit ce qui a été fait
    et ce qui a échoué, plutôt qu'un simple succès/échec.
    """
    report = SetupReport(ok=True)

    # 1. UE4SS, seulement si l'utilisateur a fourni une archive.
    if ue4ss_zip is not None:
        if not install_ue4ss(install, Path(ue4ss_zip), ledger, report):
            report.ok = False
    elif not install.has_ue4ss:
        report.add("UE4SS à installer", False,
                   "aucune archive fournie. Indiquez le .zip d'UE4SS pour l'installer.")

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
