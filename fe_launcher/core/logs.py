"""Lecture d'`UE4SS.log` : rendre visibles les échecs qui ne se voient pas.

Pourquoi ce module existe
-------------------------
Le mode d'échec dominant de ce projet est le SILENCE. UE4SS meurt dans un fichier que
personne n'ouvre ; un mod déclaré « actif » n'a jamais démarré ; une constante réécrite
par le launcher n'a pas été relue. Le symptôme observé est toujours le même — « ça marche
pas », ou pire, « ça marche mais les mesures sont bizarres ».

Or `UE4SS.log` dit tout, et dans un format stable. C'est d'ailleurs lui qui a servi à
établir le mécanisme d'activation en deux passes, contre ce qu'affirmait la documentation.
Ce module le relit après une session de jeu et répond aux trois questions qui comptent :

    UE4SS a-t-il démarré ?      (sinon, aucun mod n'a pu se charger)
    Quels mods ont démarré ?    (et par quelle voie : mods.txt ou enabled.txt)
    Qu'est-ce qui a échoué ?    (erreur fatale, mod absent, plantage)

Ce n'est pas un analyseur générique : on ne reconnaît que des motifs réellement observés
dans les logs du PC de jeu (UE4SS v3.0.1). Une ligne inconnue est ignorée plutôt
qu'interprétée — inventer un diagnostic serait pire que de n'en donner aucun.

Limite assumée
--------------
Le fichier est réécrit à chaque lancement du jeu : il ne décrit que la DERNIÈRE session.
Pour comparer deux sessions, il faut l'archiver — d'où `archive()`.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .paths import Ue4ssLayout

LOG_NAME = "UE4SS.log"

# Motifs relevés sur de vrais logs. Ne pas en ajouter sans l'avoir observé.
_RE_START_MOD = re.compile(r"Starting (?:Lua|C\+\+) mod '([^']+)'")
_RE_ENABLED_TXT = re.compile(r"Mod '([^']+)' has enabled\.txt, starting mod")
_RE_DISABLED = re.compile(r"Mod '([^']+)' disabled in mods\.txt")
_RE_FATAL = re.compile(r"Fatal Error:\s*(.+)")
_RE_ERROR = re.compile(r"\bERROR\b:?\s*(.+)", re.IGNORECASE)
_RE_MOD_OUTPUT = re.compile(r"\[Lua\] \[([^\]]+)\]\s*(.*)")
_RE_TIMESTAMP = re.compile(r"^\[([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:.]+)\]")
# La dernière ligne d'init : si on l'a, UE4SS est allé au bout de son démarrage.
_RE_UE4SS_VERSION = re.compile(r"UE4SS\s+v?([\d.]+[^\s|]*)")


class Severity(Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass
class LogEvent:
    severity: Severity
    message: str
    line_no: int
    raw: str = ""


@dataclass
class ModLoad:
    """Un mod tel que le LOG dit qu'il s'est chargé — pas tel que le disque le suggère."""

    name: str
    via: str                  # 'mods.txt' | 'enabled.txt'
    #: Lignes que le mod a lui-même imprimées. C'est là que se lisent les valeurs
    #: réellement chargées — d'où l'intérêt pour vérifier un réglage piloté.
    output: list[str] = field(default_factory=list)


@dataclass
class LogReport:
    """Ce que la dernière session raconte."""

    path: Path | None
    exists: bool
    ue4ss_version: str = ""
    started: bool = False              # UE4SS est allé au bout de son init
    mods: list[ModLoad] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    events: list[LogEvent] = field(default_factory=list)
    modified: str = ""
    line_count: int = 0

    @property
    def errors(self) -> list[LogEvent]:
        return [e for e in self.events if e.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[LogEvent]:
        return [e for e in self.events if e.severity is Severity.WARN]

    @property
    def loaded_names(self) -> set[str]:
        return {m.name for m in self.mods}

    def output_of(self, mod_name: str) -> list[str]:
        """Lignes imprimées par un mod donné, sur son nom court ou son nom de dossier."""
        short = mod_name.removeprefix("ue4ss-")
        for m in self.mods:
            if m.name in (mod_name, short):
                return m.output
        # Les mods signent souvent leurs lignes d'un nom encore plus court
        # (`[FESkins]` pour `ue4ss-FESkins`) : on cherche aussi par sous-chaîne.
        out: list[str] = []
        for m in self.mods:
            if short.lower() in m.name.lower() or m.name.lower() in short.lower():
                out.extend(m.output)
        return out

    @property
    def headline(self) -> str:
        """Une phrase pour l'utilisateur, la plus importante d'abord."""
        if not self.exists:
            return ("Aucun journal UE4SS trouvé — soit UE4SS n'est pas installé, "
                    "soit le jeu n'a jamais été lancé avec.")
        if self.errors:
            return f"{len(self.errors)} erreur(s) pendant la dernière session."
        if not self.started:
            return ("UE4SS n'a pas terminé son démarrage : aucun mod n'a pu se charger.")
        n = len(self.mods)
        return f"Session normale — {n} mod(s) démarré(s), aucune erreur."


def log_path(layout: Ue4ssLayout) -> Path:
    return layout.root / LOG_NAME


def read(layout: Ue4ssLayout | None, *, path: Path | None = None) -> LogReport:
    """Analyse le journal de la dernière session."""
    target = path if path is not None else (log_path(layout) if layout else None)
    if target is None or not target.is_file():
        return LogReport(path=target, exists=False)

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
        stamp = datetime.fromtimestamp(target.stat().st_mtime,
                                       tz=timezone.utc).isoformat()
    except OSError:
        return LogReport(path=target, exists=False)

    report = LogReport(path=target, exists=True, modified=stamp)
    lines = text.splitlines()
    report.line_count = len(lines)
    by_name: dict[str, ModLoad] = {}
    # La sortie d'un mod arrive APRÈS sa ligne de démarrage : on retient le dernier
    # mod démarré pour lui rattacher ses lignes.
    last: ModLoad | None = None

    for i, line in enumerate(lines, start=1):
        if not report.ue4ss_version and (m := _RE_UE4SS_VERSION.search(line)):
            report.ue4ss_version = m.group(1)

        if m := _RE_START_MOD.search(line):
            last = by_name.setdefault(m.group(1), ModLoad(m.group(1), "mods.txt"))
            continue
        if m := _RE_ENABLED_TXT.search(line):
            last = by_name.setdefault(m.group(1), ModLoad(m.group(1), "enabled.txt"))
            continue
        if m := _RE_DISABLED.search(line):
            # UE4SS énumère parfois les mods deux fois (une passe à blanc puis la
            # vraie) : on dédoublonne, sinon « 6 désactivés » en annonce 3 en double.
            if m.group(1) not in report.disabled:
                report.disabled.append(m.group(1))
            continue

        if m := _RE_MOD_OUTPUT.search(line):
            owner = by_name.get(m.group(1))
            target_mod = owner or last
            if target_mod is not None and m.group(2).strip():
                target_mod.output.append(m.group(2).strip())
            continue

        if m := _RE_FATAL.search(line):
            report.events.append(LogEvent(Severity.ERROR, m.group(1).strip(), i, line))
            continue
        # `ERROR` seul est très fréquent en bruit d'init ; on ne le remonte qu'en
        # avertissement, pour ne pas noyer les erreurs fatales qui, elles, comptent.
        if m := _RE_ERROR.search(line):
            report.events.append(LogEvent(Severity.WARN, m.group(1).strip()[:200], i, line))

    report.mods = list(by_name.values())
    # UE4SS a démarré si au moins un mod a été lancé : c'est la dernière étape de son
    # init, et le seul marqueur présent dans TOUS les logs observés.
    report.started = bool(report.mods)
    return report


def explain(report: LogReport) -> list[str]:
    """Traduit le rapport en constats lisibles, du plus important au moins.

    On ne recopie pas le log : on répond à « qu'est-ce que je dois en retenir ».
    """
    out: list[str] = []
    if not report.exists:
        out.append(report.headline)
        return out

    for e in report.errors:
        if "multi-byte code page" in e.message:
            # Le seul message dont on connaît la cause exacte : autant la donner.
            out.append(
                "UE4SS est mort au démarrage à cause d'un caractère non-ASCII dans le "
                "chemin d'installation du jeu. Aucun mod n'a pu se charger. "
                "Le diagnostic du tableau de bord propose le correctif.")
        else:
            out.append(f"Erreur fatale : {e.message}")

    if not report.started and not report.errors:
        out.append("UE4SS n'a démarré aucun mod. Vérifiez qu'il est bien installé "
                   "et que la DLL proxy est en place.")

    if report.mods:
        via_txt = sum(1 for m in report.mods if m.via == "mods.txt")
        via_marker = len(report.mods) - via_txt
        out.append(f"{len(report.mods)} mod(s) démarré(s) : {via_txt} par mods.txt, "
                   f"{via_marker} par enabled.txt.")
    if report.disabled:
        out.append(f"{len(report.disabled)} mod(s) désactivé(s) dans mods.txt : "
                   + ", ".join(report.disabled))
    return out


def compare_expected(report: LogReport, expected: list[str]) -> tuple[list[str], list[str]]:
    """(attendus mais absents, démarrés sans être attendus).

    Sert à confronter ce que le launcher CROIT actif à ce qui a réellement démarré.
    C'est le seul moyen de détecter qu'un mod coché n'a jamais tourné — le cas
    typique étant un mod C++ sans DLL compilée, qui a bien son `enabled.txt`.
    """
    loaded = {n.lower() for n in report.loaded_names}
    want = {n.lower(): n for n in expected}
    missing = [orig for low, orig in want.items()
               if low not in loaded and low.removeprefix("ue4ss-") not in loaded]
    extra = [n for n in report.loaded_names
             if n.lower() not in want and f"ue4ss-{n.lower()}" not in want]
    return missing, extra


def find_setting(report: LogReport, mod_name: str, needle: str) -> str | None:
    """Cherche une valeur annoncée par un mod dans ses propres lignes de log.

    C'est la brique qui permettrait au banc d'essai de VÉRIFIER qu'il mesure bien ce
    qu'il croit : il écrit une constante dans le `.lua`, puis relit ici ce que le mod
    a réellement chargé. Aujourd'hui les mods n'impriment pas tous leurs réglages —
    la fonction rend None dans ce cas plutôt que de laisser croire à une confirmation.
    """
    for line in report.output_of(mod_name):
        if needle.lower() in line.lower():
            return line
    return None


def archive(report: LogReport, dest_dir: Path) -> Path | None:
    """Copie le journal pour le conserver : le jeu l'écrase au prochain lancement."""
    if not report.exists or report.path is None:
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (report.modified or datetime.now(timezone.utc).isoformat())
    safe = re.sub(r"[^0-9]", "", stamp)[:14]
    dest = dest_dir / f"UE4SS-{safe}.log"
    try:
        shutil.copy2(report.path, dest)
    except OSError:
        return None
    return dest
