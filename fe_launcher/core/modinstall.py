"""Installation des mods embarqués dans le dossier du jeu.

Le launcher embarque une collection de mods Lua prêts à l'emploi. Ce module les copie
dans le dossier `Mods/` de l'installation UE4SS, de façon réversible (via le journal).

Pourquoi embarquer les mods
---------------------------
Sans ça, le launcher sait lire et activer des mods déjà présents, mais n'en fournit
aucun : sur une machine neuve, il n'a rien à proposer. En les embarquant, « installer un
mod » devient un clic, comme « installer UE4SS ».

UEHelpers, la dépendance oubliable
----------------------------------
Presque tous les mods Lua font `require("UEHelpers")`. Sans le dossier
`Mods/shared/UEHelpers/`, ils échouent tous au chargement — c'est le piège classique. On
déploie donc UEHelpers en même temps, une fois, et on refuse d'installer un mod si on ne
peut pas garantir sa présence.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .ledger import Ledger
from .paths import Ue4ssLayout

LEDGER_GROUP = "mod-install"
SHARED_DIRNAME = "shared"


def _bundled_dir() -> Path:
    """Dossier des mods embarqués, compatible mode compilé (.exe)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "fe_launcher" / "resources" / "mods"
    return Path(__file__).resolve().parent.parent / "resources" / "mods"


@dataclass
class BundledMod:
    """Un mod livré avec le launcher."""

    name: str
    path: Path
    description: str = ""

    @property
    def is_lua(self) -> bool:
        return (self.path / "Scripts" / "main.lua").is_file()


def _first_doc_line(script: Path) -> str:
    try:
        for line in script.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
            s = line.strip()
            if s.startswith("--"):
                t = s.lstrip("-").strip()
                if len(t) > 12 and not set(t) <= set("=-_ #*"):
                    return t
    except OSError:
        pass
    return ""


def bundled_mods() -> list[BundledMod]:
    """Tous les mods embarqués, triés (FE d'abord), hors dossier `shared`."""
    base = _bundled_dir()
    if not base.is_dir():
        return []
    out: list[BundledMod] = []
    for d in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir() or d.name == SHARED_DIRNAME:
            continue
        script = d / "Scripts" / "main.lua"
        out.append(BundledMod(name=d.name, path=d,
                              description=_first_doc_line(script) if script.is_file() else ""))
    # Les mods du projet (ue4ss-FE*) avant les autres.
    out.sort(key=lambda m: (not m.name.lower().startswith("ue4ss-fe"), m.name.lower()))
    return out


def bundled_mod(name: str) -> BundledMod | None:
    return next((m for m in bundled_mods() if m.name == name), None)


def is_installed(layout: Ue4ssLayout, name: str) -> bool:
    return (layout.mods_dir / name).is_dir()


@dataclass
class InstallReport:
    ok: bool
    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    message: str = ""


def _deploy_uehelpers(layout: Ue4ssLayout, ledger: Ledger) -> bool:
    """Copie UEHelpers dans Mods/shared/ s'il n'y est pas déjà."""
    if layout.uehelpers.is_file():
        return True
    src = _bundled_dir() / SHARED_DIRNAME
    if not src.is_dir():
        return False
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            ledger.create_file(layout.shared_dir / rel, f.read_bytes(),
                               label=f"UEHelpers : {rel}", group=LEDGER_GROUP)
    return layout.uehelpers.is_file()


def install(layout: Ue4ssLayout, name: str, ledger: Ledger, *,
            activate: bool = True) -> InstallReport:
    """Installe un mod embarqué dans le jeu, avec UEHelpers si nécessaire.

    Ne réinstalle pas un mod déjà présent (on ne veut pas écraser une version que
    l'utilisateur aurait ajustée). Copie chaque fichier via le journal, donc réversible.
    """
    mod = bundled_mod(name)
    if mod is None:
        return InstallReport(False, message=f"Mod embarqué introuvable : {name}")
    if is_installed(layout, name):
        return InstallReport(True, skipped=[name],
                             message=f"« {name} » est déjà installé.")

    if not _deploy_uehelpers(layout, ledger):
        return InstallReport(False,
                             message="Impossible de déployer UEHelpers, dont les mods "
                                     "dépendent. Installation annulée.")

    for f in mod.path.rglob("*"):
        if f.is_file():
            rel = f.relative_to(mod.path)
            ledger.create_file(layout.mods_dir / name / rel, f.read_bytes(),
                               label=f"mod {name} : {rel}", group=LEDGER_GROUP)
    if activate:
        # Marqueur d'activation UE4SS : la présence du fichier suffit (cf. mods.py).
        marker = layout.mods_dir / name / "enabled.txt"
        if not marker.is_file():
            ledger.create_file(marker, b"", label=f"activation de {name}",
                               group=LEDGER_GROUP)

    return InstallReport(True, installed=[name],
                         message=f"« {name} » installé" + (" et activé." if activate else "."))


def install_all(layout: Ue4ssLayout, ledger: Ledger, *,
                names: list[str] | None = None, activate: bool = True,
                include_restricted: bool = False) -> InstallReport:
    """Installe plusieurs mods embarqués. Rapport agrégé.

    Par défaut, EXCLUT les mods restreints (FEDevMenu) : le masquer dans l'interface ne
    sert à rien si l'installation groupée le pose et l'active quand même sur le disque.
    Il ne s'installe qu'avec `include_restricted=True` (mode développeur, choix explicite).
    """
    from . import moddocs  # import tardif : évite un cycle
    if names is not None:
        targets = names
    else:
        targets = [m.name for m in bundled_mods()
                   if include_restricted or not moddocs.is_restricted(m.name)]
    report = InstallReport(ok=True)
    for name in targets:
        r = install(layout, name, ledger, activate=activate)
        report.installed += r.installed
        report.skipped += r.skipped
        if not r.ok:
            report.ok = False
    report.message = (f"{len(report.installed)} mod(s) installé(s), "
                      f"{len(report.skipped)} déjà présent(s).")
    return report
