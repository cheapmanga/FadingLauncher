"""Lancement du jeu, en assumant qu'on ne sait presque rien de la façon dont il démarre.

Ce module est volontairement prudent, parce que les faits vérifiés sont peu nombreux :

1. VÉRIFIÉ — l'AppID Steam est 2467880, et `steam://rungameid/2467880` est le chemin
   par lequel le jeu est réellement lancé aujourd'hui. C'est le SEUL dont on sache
   qu'il fonctionne.
2. VÉRIFIÉ — l'exe lancé par Steam n'est pas l'exe du moteur. C'est un shim
   (`FadingEcho.exe`, ~180 Ko ; `FadingEchoDemo.exe` pour la démo) posé à la racine
   de l'install, qui démarre `UE_YGRO\\Binaries\\Win64\\UE_YGRO_Steam-Win64-Shipping.exe`
   (~176 Mo).
3. NON VÉRIFIÉ — ce que fait le shim entre les deux. Initialisation de l'API Steam,
   choix d'un RHI, crash reporter : on n'en sait rien.
4. NON VÉRIFIÉ — si le jeu exige que Steam tourne. L'exe s'appelle `..._Steam_...`,
   ce qui *suggère* une dépendance à steam_api64, mais ça n'a pas été testé.
5. NON VÉRIFIÉ — AUCUN argument de ligne de commande. Ni `-log`, ni `-windowed`, ni
   `-nosplash`. Ce sont des arguments UE standards, mais standard ne veut pas dire
   présent : un jeu Shipping peut les avoir désactivés. Rien n'a été essayé sur FE.

D'où la hiérarchie des modes de lancement exposée ici : STEAM est le défaut et le seul
mode « sûr ». SHIM et ENGINE sont des modes DÉGRADÉS, à présenter comme tels dans l'UI
(cf. `LaunchMode.verified` et `LaunchResult.warnings`) — surtout pas comme trois
options équivalentes dans une liste déroulante.

Le poste de dev n'a ni Windows ni le jeu : `dry_run=True` construit et retourne la
commande sans rien exécuter, et c'est par là que passe la totalité des tests.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .procutil import run_hidden
from .paths import (APPID, DEMO_SHIM, FULL_SHIM, UE_EXE, Edition, GameInstall,
                    _steam_root)

STEAM_URL = f"steam://rungameid/{APPID}"

# Noms de process à surveiller pour savoir si le jeu tourne. Le shim peut avoir rendu
# la main avant que l'exe moteur n'apparaisse (ou l'inverse), donc on cherche les trois.
PROCESS_NAMES = (UE_EXE, FULL_SHIM, DEMO_SHIM)


class LaunchMode(Enum):
    """Comment démarrer le jeu. Les trois ne se valent PAS — voir `verified`."""

    #  Passe par Steam. Steam se charge du shim, des DRM éventuels, de l'overlay et
    #  des variables d'environnement de l'API Steam. Seul chemin connu comme marchant.
    STEAM = "steam"
    #  Exécute directement le shim de la racine. Reproduit ce que Steam exécute, mais
    #  sans l'environnement que Steam installe autour. NON VÉRIFIÉ.
    SHIM = "shim"
    #  Exécute directement l'exe moteur, en court-circuitant le shim. On ne sait pas ce
    #  que le shim fait, donc on ne sait pas ce qu'on saute. NON VÉRIFIÉ.
    ENGINE = "engine"

    @property
    def verified(self) -> bool:
        return self is LaunchMode.STEAM

    @property
    def label(self) -> str:
        return {
            LaunchMode.STEAM: "Via Steam (recommandé)",
            LaunchMode.SHIM: "Directement le lanceur du jeu (non vérifié)",
            LaunchMode.ENGINE: "Directement le moteur, sans le lanceur (non vérifié)",
        }[self]


@dataclass
class LaunchResult:
    """Ce qui a été tenté, ce qui a marché, et tout ce dont on n'est pas sûr.

    On ne retourne jamais un simple booléen : `started` ne dit que « le process a été
    créé ». Il ne dit pas que le jeu s'affichera — sur un mode non vérifié, il peut
    très bien se fermer une seconde plus tard sans rien afficher.
    """

    mode: LaunchMode
    command: list[str]
    cwd: Path | None = None
    dry_run: bool = False
    started: bool = False
    pid: int | None = None
    error: str = ""                                   # message utilisateur, français
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.started or (self.dry_run and not self.error)

    @property
    def command_line(self) -> str:
        """Commande lisible, à afficher dans l'UI ou à copier dans un rapport de bug."""
        return " ".join(f'"{c}"' if " " in c else c for c in self.command)


# --- Disponibilité de Steam -----------------------------------------------------

@dataclass(frozen=True)
class SteamStatus:
    installed: bool
    root: Path | None
    #  Peut-on ouvrir une URL steam:// ? Sur Windows le handler est enregistré par
    #  Steam lui-même ; sur Linux (dev) il faut un ouvreur d'URL type xdg-open.
    can_open_url: bool
    reason: str = ""


def steam_status() -> SteamStatus:
    """Steam est-il installé, et peut-on lui passer une URL `steam://` ?

    Sert à ne pas proposer le mode STEAM quand il est certain d'échouer, et surtout à
    expliquer POURQUOI plutôt que de laisser l'utilisateur devant un lancement muet.
    """
    root = _steam_root()
    if sys.platform == "win32":
        # Le protocole steam:// est enregistré à l'install de Steam. On ne lit pas la
        # base de registres pour le vérifier : si Steam est là, le handler l'est aussi.
        can = root is not None
        return SteamStatus(
            installed=root is not None,
            root=root,
            can_open_url=can,
            reason="" if can else "Steam est introuvable sur ce PC.",
        )

    opener = _url_opener()
    return SteamStatus(
        installed=root is not None,
        root=root,
        can_open_url=opener is not None,
        reason="" if opener else "Aucun ouvreur d'URL (xdg-open) disponible.",
    )


def _url_opener() -> str | None:
    for candidate in ("xdg-open", "open"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


# --- Construction de la commande -------------------------------------------------

class LaunchError(RuntimeError):
    """Le lancement est impossible à préparer (message déjà en français)."""


def build_command(
    install: GameInstall | None,
    mode: LaunchMode = LaunchMode.STEAM,
    args: tuple[str, ...] = (),
) -> tuple[list[str], Path | None, list[str]]:
    """(commande, dossier de travail, avertissements) pour un mode donné.

    Séparé de `launch()` pour que l'UI puisse afficher la commande exacte AVANT
    d'exécuter quoi que ce soit, et pour que les tests n'aient jamais besoin du jeu.

    Lève LaunchError si le mode est impossible (exe absent, Steam absent...).
    """
    warnings: list[str] = []
    if not mode.verified:
        warnings.append(
            f"Mode « {mode.label} » : ce mode n'a jamais été vérifié sur Fading Echo. "
            "Si le jeu ne démarre pas ou se ferme aussitôt, relancez via Steam."
        )
    if args:
        # On n'a testé AUCUN argument sur ce jeu. On les transmet parce que
        # l'utilisateur les demande, pas parce qu'on pense qu'ils marchent.
        warnings.append(
            "Arguments de ligne de commande non vérifiés sur ce jeu : "
            f"{' '.join(args)} — ils peuvent être ignorés, ou empêcher le démarrage."
        )

    # La DÉMO est une autre app Steam, dont l'appid n'est pas 2467880. Lancer via
    # `steam://rungameid/2467880` démarrerait le JEU COMPLET, pas la démo — et le launcher
    # lirait ensuite le mauvais journal. Pour la démo, on lance donc le shim directement
    # (son `steam_appid.txt` à côté de l'exe lui permet de se connecter à Steam). C'est le
    # seul chemin possible sans connaître son appid.
    if (mode is LaunchMode.STEAM and install is not None
            and install.edition is Edition.DEMO and install.shim_exe is not None):
        warnings.append(
            "Démo : lancée directement (le launcher ne connaît pas son identifiant "
            "Steam). Si elle ne démarre pas, lancez-la depuis Steam."
        )
        return [str(install.shim_exe)], install.shim_exe.parent, warnings

    if mode is LaunchMode.STEAM:
        status = steam_status()
        if not status.can_open_url:
            raise LaunchError(
                (status.reason or "Steam est indisponible.")
                + " Installez Steam, ou utilisez un mode de lancement direct "
                  "(non vérifié) depuis les options."
            )
        if args:
            # `steam://rungameid/<id>//<args>/` circule sur les forums mais n'est pas
            # documenté par Valve et n'a pas été testé ici : on ne le fabrique pas.
            warnings.append(
                "En mode Steam, les arguments ne sont pas transmis au jeu : "
                "Steam ne propose pas de voie documentée pour cela."
            )
        if sys.platform == "win32":
            # `start ""` : le premier argument de `start` est le titre de la fenêtre,
            # il faut donc un titre vide, sinon l'URL est prise pour le titre.
            return ["cmd", "/c", "start", "", STEAM_URL], None, warnings
        opener = _url_opener()
        assert opener is not None  # garanti par can_open_url
        return [opener, STEAM_URL], None, warnings

    if install is None:
        raise LaunchError("Aucune installation de Fading Echo sélectionnée.")

    if mode is LaunchMode.SHIM:
        if install.shim_exe is None or not install.shim_exe.is_file():
            raise LaunchError(
                f"Le lanceur du jeu ({FULL_SHIM} / {DEMO_SHIM}) est introuvable "
                f"dans {install.root}."
            )
        # cwd = racine de l'install : c'est de là que Steam lance le shim, et un exe UE
        # résout ses chemins relatifs depuis son dossier de travail.
        return [str(install.shim_exe), *args], install.root, warnings

    if not install.engine_exe.is_file():
        raise LaunchError(f"L'exécutable du moteur est introuvable : {install.engine_exe}")
    warnings.append(
        "Le lanceur du jeu est court-circuité. Ce qu'il fait n'est pas documenté ; "
        "des fonctions dépendant de Steam peuvent manquer."
    )
    return [str(install.engine_exe), *args], install.engine_dir, warnings


def launch(
    install: GameInstall | None,
    mode: LaunchMode = LaunchMode.STEAM,
    args: tuple[str, ...] = (),
    dry_run: bool = False,
) -> LaunchResult:
    """Démarre le jeu. Retourne toujours un LaunchResult, ne lève pas.

    `mode` vaut STEAM par défaut : c'est le seul mode dont on sait qu'il fonctionne.
    `args` est transmis tel quel aux modes directs ; AUCUN argument n'a été vérifié sur
    ce jeu (ni `-log`, ni `-windowed`) — le résultat porte un avertissement en ce sens.
    `dry_run=True` construit la commande et s'arrête là : rien n'est exécuté.
    """
    try:
        command, cwd, warnings = build_command(install, mode, args)
    except LaunchError as exc:
        return LaunchResult(mode=mode, command=[], dry_run=dry_run, error=str(exc))

    result = LaunchResult(mode=mode, command=command, cwd=cwd,
                          dry_run=dry_run, warnings=warnings)
    if dry_run:
        return result

    if is_running():
        result.warnings.append(
            "Fading Echo semble déjà en cours d'exécution — un second lancement "
            "risque de ne rien faire."
        )

    # Détaché : fermer le launcher ne doit pas tuer le jeu. Les drapeaux n'existent
    # que sur Windows, d'où le getattr (le module tourne aussi sur le poste de dev).
    # CREATE_NO_WINDOW en plus : le lancement Steam passe par `cmd /c start`, qui
    # ferait clignoter une fenêtre de console sans ce drapeau. Le jeu, lui, crée sa
    # propre fenêtre — le drapeau ne masque que la console intermédiaire.
    flags = 0
    if sys.platform == "win32":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        proc = subprocess.Popen(  # noqa: S603 — commande construite par nos soins
            command,
            cwd=str(cwd) if cwd else None,
            creationflags=flags,
            close_fds=True,
        )
    except FileNotFoundError:
        result.error = f"Commande introuvable : {command[0]}"
    except OSError as exc:
        result.error = f"Échec du lancement : {exc}"
    else:
        result.started = True
        result.pid = proc.pid
        if mode is LaunchMode.STEAM:
            # Le pid est celui de `start`/`xdg-open`, pas celui du jeu : il meurt
            # immédiatement. Ne jamais l'utiliser pour surveiller le jeu.
            result.pid = None
    return result


# --- Détection « le jeu tourne-t-il ? » -----------------------------------------

@dataclass(frozen=True)
class ProcessProbe:
    """Résultat d'une inspection des process. `supported=False` = on ne sait pas."""

    supported: bool
    names: tuple[str, ...] = ()
    reason: str = ""

    @property
    def running(self) -> bool:
        return bool(self.names)


def probe_processes() -> ProcessProbe:
    """Cherche les process du jeu. Ne lève jamais, et dit quand elle ne sait pas.

    Sur le poste de dev (Linux, sans le jeu), il n'y a rien à trouver : la fonction
    doit dégrader proprement et non planter. `supported=False` signifie « impossible
    de conclure » et NE doit pas être présenté comme « le jeu ne tourne pas ».
    """
    try:
        if sys.platform == "win32":
            out = run_hidden(
                ["tasklist", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        else:
            # Proton lance bien l'exe Windows sous son nom : pgrep le voit. Sur un poste
            # sans le jeu, on obtient simplement une liste vide.
            if shutil.which("pgrep") is None:
                return ProcessProbe(False, reason="`pgrep` indisponible sur ce système.")
            out = run_hidden(
                ["pgrep", "-a", "-i", "-f", "|".join(PROCESS_NAMES)],
                capture_output=True, text=True, timeout=10, check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return ProcessProbe(False, reason=f"Inspection des process impossible : {exc}")

    haystack = (out.stdout or "").lower()
    found = tuple(name for name in PROCESS_NAMES if name.lower() in haystack)
    return ProcessProbe(True, names=found)


def is_running() -> bool:
    """Le jeu tourne-t-il ? False si on ne peut pas le savoir (dégradation).

    Volontairement pessimiste : quand l'inspection est impossible, on répond False pour
    ne jamais bloquer un lancement légitime. Une UI qui veut nuancer doit appeler
    `probe_processes()` et lire `supported`.
    """
    return probe_processes().running
