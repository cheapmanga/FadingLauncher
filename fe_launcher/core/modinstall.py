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

import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .ledger import Ledger
from .paths import Ue4ssLayout

LEDGER_GROUP = "mod-install"
SHARED_DIRNAME = "shared"

# Même motif que mods._CONSOLE_RE : on le duplique pour ne pas créer de cycle d'import
# (mods importe indirectement modinstall via l'UI). Les deux doivent rester d'accord.
_CONSOLE_RE = re.compile(
    r'RegisterConsoleCommand(?:Global)?Handler\s*\(\s*["\']([^"\']+)["\']')


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

    @property
    def commands(self) -> list[str]:
        """Noms de commandes console que ce mod enregistre (scan du main.lua)."""
        return _console_commands(self.path / "Scripts" / "main.lua")


def _console_commands(script: Path) -> list[str]:
    """Commandes console (`RegisterConsoleCommand[Global]Handler("x", …)`) d'un script.

    Deux mods qui enregistrent le MÊME nom se disputent la table de handlers d'UE4SS.
    Sur ce jeu, ça ne « fait pas juste autre chose » : ça provoque un crash natif
    (EXCEPTION_ACCESS_VIOLATION dans UE4SS.dll) dès qu'on tape la commande. On les
    repère donc pour ne jamais activer deux fournisseurs du même nom à la fois.
    """
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return list(dict.fromkeys(_CONSOLE_RE.findall(text)))


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
    """Vrai si le mod est présent ET utilisable.

    Le seul test « le dossier existe » ne suffit pas : un dossier vidé de son script
    (réinstallation d'UE4SS par-dessus, annulation partielle, suppression à la main)
    passait pour installé. Résultat, le bouton d'installation répondait « tous les
    mods sont déjà installés » et ne reposait rien, pendant qu'UE4SS démarrait le
    dossier à cause de son `enabled.txt` et échouait sur « main.lua not found ».
    On exige donc la charge utile : le script Lua, ou une DLL pour les mods C++.
    """
    d = layout.mods_dir / name
    if not d.is_dir():
        return False
    return (d / "Scripts" / "main.lua").is_file() or any(d.rglob("*.dll"))


@dataclass
class InstallReport:
    ok: bool
    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    # Mods posés mais laissés DÉSACTIVÉS car un autre mod actif fournit déjà leur
    # commande console. name -> (commande partagée, mod gardé actif).
    deactivated: dict[str, tuple[str, str]] = field(default_factory=dict)
    message: str = ""


def _enabled_on_disk(layout: Ue4ssLayout, name: str) -> bool:
    return (layout.mods_dir / name / "enabled.txt").is_file()


def _resolve_command_activation(layout: Ue4ssLayout,
                                targets: list[str]) -> dict[str, tuple[str, str]]:
    """Décide quels mods poser DÉSACTIVÉS pour qu'aucune commande n'ait deux fournisseurs.

    Deux mods qui enregistrent la même commande console font crasher UE4SS sur ce jeu.
    On garde donc, par commande, un seul fournisseur actif. Priorité au mod déjà actif
    sur le disque (on ne débranche pas ce qui tourne), puis à celui qui fournit le PLUS
    de commandes (FEUnlocker-Plus, qui fait `core` ET `unlock`, l'emporte sur
    FECoreGiver, simple sous-ensemble `core`), départage alphabétique pour être stable.

    Retour : {mod à désactiver : (commande en cause, mod gardé actif)}.
    """
    # Fournisseurs par commande : mods de la cible + mods déjà actifs sur le disque.
    providers: dict[str, list[str]] = {}
    cmd_count: dict[str, int] = {}
    active_on_disk: set[str] = set()
    for m in bundled_mods():
        cmds = m.commands
        cmd_count[m.name] = len(cmds)
        in_target = m.name in targets
        on_disk = is_installed(layout, m.name) and _enabled_on_disk(layout, m.name)
        if on_disk:
            active_on_disk.add(m.name)
        if in_target or on_disk:
            for c in cmds:
                providers.setdefault(c, []).append(m.name)

    demote: dict[str, tuple[str, str]] = {}
    for cmd, mods in providers.items():
        if len(mods) < 2:
            continue
        # Le meilleur candidat à GARDER actif : déjà actif d'abord, puis + de commandes,
        # puis ordre alphabétique.
        keep = sorted(mods, key=lambda n: (n not in active_on_disk,
                                           -cmd_count.get(n, 0), n))[0]
        for n in mods:
            if n != keep and n not in active_on_disk:
                demote.setdefault(n, (cmd, keep))
    return demote


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
            # On NE copie PAS l'`enabled.txt` livré avec le mod : l'activation est
            # décidée ici par le drapeau `activate`, pas héritée du bundle. Sans ça,
            # `activate=False` était sans effet (le marqueur du bundle activait quand
            # même le mod), et deux fournisseurs d'une même commande console se
            # retrouvaient actifs — le crash natif qu'on cherche justement à éviter.
            if rel.name == "enabled.txt" and rel.parent == Path("."):
                continue
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

    # Résout les collisions de commande console AVANT de poser quoi que ce soit : les
    # mods perdants sont installés mais laissés désactivés, jamais deux fournisseurs
    # actifs pour un même nom (sinon crash natif d'UE4SS à l'usage de la commande).
    demote = _resolve_command_activation(layout, targets) if activate else {}

    report = InstallReport(ok=True)
    for name in targets:
        this_activate = activate and name not in demote
        r = install(layout, name, ledger, activate=this_activate)
        report.installed += r.installed
        report.skipped += r.skipped
        if r.installed and name in demote:
            report.deactivated[name] = demote[name]
        if not r.ok:
            report.ok = False

    msg = (f"{len(report.installed)} mod(s) installé(s), "
           f"{len(report.skipped)} déjà présent(s).")
    if report.deactivated:
        détail = ", ".join(f"{n} (commande « {cmd} » déjà fournie par {keep})"
                           for n, (cmd, keep) in report.deactivated.items())
        msg += (f"\n\n{len(report.deactivated)} mod(s) posé(s) mais laissé(s) "
                f"désactivé(s) pour éviter un conflit de commande : {détail}. "
                "Vous pouvez basculer lequel activer depuis la page Mods.")
    report.message = msg
    return report
