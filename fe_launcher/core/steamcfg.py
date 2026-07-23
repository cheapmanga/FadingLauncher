"""Branchement du launcher sur Steam : l'option de lancement `%command%`.

But
---
Pour que « ouvrir le jeu sur Steam » ouvre en fait le launcher — qui applique les
réglages puis lance le vrai jeu — Steam doit avoir, dans les propriétés du jeu, une
option de lancement de la forme :

    "C:\\chemin\\FadingEchoLauncher.exe" %command%

Steam remplace `%command%` par la vraie ligne de commande du jeu ; le launcher la reçoit
en argument et décide quoi en faire (mode discret pour le stream, ou fenêtre complète).

Écriture automatique — et pourquoi elle est dangereuse
------------------------------------------------------
Cette option vit dans `localconfig.vdf`, un fichier que STEAM possède et réécrit à sa
fermeture. L'utilisateur a demandé que le launcher l'écrive lui-même. On l'a accepté,
mais entouré des mêmes garde-fous que le renommage du dossier grec, parce que c'est le
seul endroit de l'outil qui pourrait casser la config Steam :

  * refus si Steam tourne OU si son état est inconnu (une écriture pendant que Steam
    tourne est écrasée à sa fermeture, dans le meilleur cas ; corrompue dans le pire) ;
  * sauvegarde par le journal avant toute modification, donc annulable et défaite à la
    désinstallation ;
  * substitution CIBLÉE de la seule clé `LaunchOptions` du seul appid du jeu, sans
    reformater le reste du fichier ;
  * la ligne à coller à la main reste toujours disponible en repli (`launch_line`).

On ne parse pas le VDF en objet : on repère le bloc `"<appid>" { … }` et on y remplace
(ou insère) `LaunchOptions`. Un VDF est sensible à l'indentation et à l'ordre ; le
réécrire entièrement risquerait d'altérer des réglages sans rapport.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .ledger import Ledger
from .paths import APPID, _steam_root

LEDGER_GROUP = "steam-launch-option"

# Jeton que Steam substitue par la commande réelle du jeu.
COMMAND_TOKEN = "%command%"


def launch_line(launcher_exe: Path | str) -> str:
    """La ligne exacte à mettre dans « Options de lancement » de Steam."""
    exe = str(launcher_exe)
    quoted = f'"{exe}"' if " " in exe else exe
    return f"{quoted} {COMMAND_TOKEN}"


def _config_users_dir(steam_root: Path) -> Path:
    return steam_root / "userdata"


def find_localconfigs(steam_root: Path | None = None) -> list[Path]:
    """Tous les `localconfig.vdf` (un par compte Steam sur la machine).

    Il y a un dossier par SteamID sous `userdata/`. On ne devine pas lequel est
    l'utilisateur courant : on les retourne tous, et l'appelant écrit dans chacun ou
    laisse choisir. En pratique il n'y en a souvent qu'un.
    """
    root = steam_root or _steam_root()
    if root is None:
        return []
    users = _config_users_dir(root)
    if not users.is_dir():
        return []
    out = []
    for child in users.iterdir():
        cfg = child / "config" / "localconfig.vdf"
        if cfg.is_file():
            out.append(cfg)
    return out


# Repère `"<appid>" { ... }` — capture le bloc pour y chercher/écrire LaunchOptions.
def _app_block_span(text: str, appid: int) -> tuple[int, int] | None:
    """(début, fin) du corps `{...}` du bloc de l'appid, ou None s'il est absent.

    On équilibre les accolades à la main : une regex ne sait pas apparier des blocs
    imbriqués, et le bloc d'un jeu contient des sous-blocs.
    """
    m = re.search(rf'"{appid}"\s*\{{', text)
    if m is None:
        return None
    depth = 0
    start = m.end() - 1  # sur l'accolade ouvrante
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return (start + 1, i)  # corps entre les accolades
    return None


_LAUNCHOPT_RE = re.compile(r'"LaunchOptions"\s*"((?:[^"\\]|\\.)*)"')


def read_launch_options(cfg: Path, appid: int = APPID) -> str | None:
    """Valeur actuelle de LaunchOptions pour l'appid, ou None si absente/illisible."""
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    span = _app_block_span(text, appid)
    if span is None:
        return None
    body = text[span[0]:span[1]]
    m = _LAUNCHOPT_RE.search(body)
    return m.group(1) if m else None


@dataclass
class SteamCfgStatus:
    supported: bool               # au moins un localconfig.vdf trouvé
    configs: list[Path]
    current: str | None           # LaunchOptions actuel (du 1er config), None si absent
    wired: bool                   # le launcher est-il déjà branché ?
    message: str = ""


def status(launcher_exe: Path | str, *,
           steam_root: Path | None = None, appid: int = APPID) -> SteamCfgStatus:
    configs = find_localconfigs(steam_root)
    if not configs:
        return SteamCfgStatus(
            supported=False, configs=[], current=None, wired=False,
            message="Aucune configuration Steam trouvée sur ce PC. Vous pouvez tout de "
                    "même coller la ligne à la main dans les propriétés du jeu.")
    current = read_launch_options(configs[0], appid)
    line = launch_line(launcher_exe)
    wired = current is not None and str(launcher_exe) in current
    if wired:
        msg = "Le launcher est déjà branché sur Steam."
    elif current:
        msg = (f"Une autre option de lancement est déjà présente : « {current} ». "
               f"Le branchement la remplacera (elle sera restaurable).")
    else:
        msg = "Le launcher n'est pas encore branché sur Steam."
    return SteamCfgStatus(supported=True, configs=configs, current=current,
                          wired=wired, message=msg)


def _replace_in_body(text: str, span: tuple[int, int], value: str) -> str:
    """Remplace ou insère LaunchOptions dans le corps du bloc app, sans toucher au reste."""
    start, end = span
    body = text[start:end]
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    if _LAUNCHOPT_RE.search(body):
        new_body = _LAUNCHOPT_RE.sub(f'"LaunchOptions"\t\t"{escaped}"', body, count=1)
    else:
        # Insertion en tête du corps, en imitant l'indentation d'une ligne voisine.
        indent = "\t\t\t\t\t\t"
        m = re.search(r'\n(\s+)"', body)
        if m:
            indent = m.group(1)
        new_body = f'\n{indent}"LaunchOptions"\t\t"{escaped}"' + body
    return text[:start] + new_body + text[end:]


@dataclass
class SteamCfgResult:
    ok: bool
    message: str
    line: str = ""              # la ligne manuelle, toujours fournie en repli


def wire(launcher_exe: Path | str, ledger: Ledger, *,
         steam_running: bool | None, steam_root: Path | None = None,
         appid: int = APPID) -> SteamCfgResult:
    """Branche le launcher dans Steam. Refuse si Steam n'est pas prouvé fermé.

    `steam_running` vient de `doctor.steam_processes_running()` : True, False ou None
    (inconnu). None et True refusent tous deux — on n'écrit que si l'on est CERTAIN que
    Steam est fermé, sinon l'écriture serait écrasée ou corromprait le fichier.
    """
    line = launch_line(launcher_exe)
    if steam_running is None:
        return SteamCfgResult(
            False,
            "Impossible de vérifier que Steam est fermé : branchement automatique "
            "refusé. Fermez Steam et collez la ligne ci-dessous à la main, ou réessayez.",
            line)
    if steam_running:
        return SteamCfgResult(
            False,
            "Steam est en cours d'exécution. Fermez-le complètement (icône de la barre "
            "des tâches → Quitter), puis réessayez — sinon Steam réécrit sa configuration "
            "en se fermant et le branchement est perdu.",
            line)

    configs = find_localconfigs(steam_root)
    if not configs:
        return SteamCfgResult(
            False,
            "Configuration Steam introuvable. Collez la ligne ci-dessous dans "
            "Propriétés du jeu → Options de lancement.",
            line)

    done = 0
    for cfg in configs:
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        span = _app_block_span(text, appid)
        if span is None:
            # Le jeu n'a jamais été lancé sur ce compte : pas de bloc à modifier.
            continue
        patched = _replace_in_body(text, span, line)
        if patched == text:
            done += 1  # déjà à jour
            continue
        # Passer par le journal : sauvegarde du fichier d'origine, donc annulable et
        # défait à la désinstallation.
        ledger.modify_file(cfg, patched.encode("utf-8"),
                           label=f"Steam : option de lancement ({cfg.parent.parent.name})",
                           group=LEDGER_GROUP)
        done += 1

    if done == 0:
        return SteamCfgResult(
            False,
            "Le jeu n'apparaît dans aucune configuration Steam (jamais lancé ?). "
            "Lancez-le une fois via Steam, ou collez la ligne à la main.",
            line)
    return SteamCfgResult(
        True,
        f"Launcher branché sur Steam. Au prochain « Jouer » depuis Steam, c'est le "
        f"launcher qui s'ouvrira. Pour revenir en arrière : page Paramètres → annuler, "
        f"ou videz les options de lancement dans Steam.",
        line)


def unwire(ledger: Ledger) -> SteamCfgResult:
    """Débranche : annule les écritures de branchement via le journal."""
    results = ledger.undo_group(LEDGER_GROUP)
    failed = [r for r in results if not r.ok]
    if failed:
        return SteamCfgResult(
            False, "Débranchement incomplet : " + " ; ".join(r.message for r in failed))
    return SteamCfgResult(True, "Launcher débranché de Steam.")


def parse_forwarded_command(argv: list[str]) -> list[str] | None:
    """Extrait la commande du jeu que Steam a passée au launcher via %command%.

    Steam lance `<launcher.exe> <exe du jeu> <args...>`. Tout ce qui suit le nom du
    launcher est la vraie commande à exécuter. None si rien n'a été transmis (le
    launcher a été ouvert directement, pas par Steam).
    """
    forwarded = argv[1:]
    return forwarded if forwarded else None
