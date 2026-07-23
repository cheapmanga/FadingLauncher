"""Mode « boîtes » : afficher les collisions, murs invisibles et volumes de trigger.

Ce que fait ce module
---------------------
Il dépose un `Engine.ini` de débogage dans le dossier de configuration du jeu, puis le
retire quand on désactive l'option. Le jeu lit ce fichier au démarrage : le mode doit
donc être posé AVANT le lancement, jamais pendant.

    %LOCALAPPDATA%\\UE_YGRO\\Saved\\Config\\Windows\\Engine.ini

Le chemin est dérivé de `%LOCALAPPDATA%`, jamais écrit en dur avec un nom d'utilisateur :
l'outil est destiné à être partagé, et un chemin codé sur un compte précis ne
fonctionnerait que sur une seule machine.

Pourquoi ce fichier est court
-----------------------------
Le fichier d'origine du projet faisait 305 lignes, dont environ 115 étaient des variables
de console **qui n'existent pas dans Unreal** — deux blocs manifestement engendrés par
combinaison mécanique (`r.VT.MaxTextureAddressU`, `r.AOGlobalDistanceFieldUseDistance
FieldVolumetricClouds`…), avec des doublons contradictoires. Unreal ignore silencieusement
une variable inconnue : ces lignes ne cassaient rien, mais elles ne faisaient rien non plus
et noyaient les quelques réglages réellement actifs.

Ne sont conservées ici que des variables réelles, chacune justifiée. Si une ligne est
ajoutée un jour, elle doit l'être avec sa raison d'être — pas « au cas où ».

Ce qui n'est PAS garanti
------------------------
Le jeu est distribué en configuration *Shipping*. Unreal y compile hors du binaire une
partie des chemins de rendu de débogage, et plusieurs variables portent l'attribut
`ECVF_Cheat`, ignoré en Shipping sans le moindre message d'erreur. Ces réglages sont donc
**les bons candidats connus**, pas une garantie d'affichage. C'est dit à l'utilisateur
dans l'interface plutôt que promis : un outil qui promet un résultat qu'il ne contrôle pas
fait perdre plus de temps qu'il n'en fait gagner.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .ledger import Action, Ledger

CONFIG_SUBPATH = Path("UE_YGRO") / "Saved" / "Config" / "Windows"
ENGINE_INI = "Engine.ini"
LEDGER_GROUP = "boxes-engine-ini"

# En-tête écrit dans le fichier : sans elle, quelqu'un qui retrouve ce fichier dans six
# mois n'a aucun moyen de savoir d'où il sort ni s'il peut le supprimer.
_HEADER = """\
; Engine.ini déposé par le Fading Echo Launcher — mode « boîtes ».
;
; Rend visibles les collisions, murs invisibles et volumes de trigger.
; Ce fichier est retiré automatiquement quand l'option est désactivée dans le launcher,
; ou lors de sa désinstallation. Vous pouvez aussi le supprimer à la main sans risque :
; le jeu recrée ce dont il a besoin au prochain démarrage.
;
; Attention : le jeu est distribué en configuration Shipping, où Unreal ignore une partie
; des réglages de débogage. Ces variables sont les bons candidats connus, pas une
; garantie que l'affichage fonctionnera.
"""

# Uniquement des variables Unreal réelles, chacune avec sa raison d'être.
_BODY = """
[/Script/Engine.RendererSettings]
; Autorise les modes de vue de débogage, désactivés par défaut hors éditeur.
r.AllowDebugViewmodes=1
; Force leur disponibilité même quand le moteur les juge inutiles.
r.ForceDebugViewModes=2

[/Script/Engine.Engine]
; Autorise les messages de débogage à l'écran (utile pour voir ce qui répond).
bEnableOnScreenDebugMessages=True

[ConsoleVariables]
; Dessin de débogage du moteur physique Chaos : c'est lui qui trace les volumes.
p.EnableDebugDraw=1
p.DrawDebugHelpers=1
; Trace les requêtes de collision — rend visibles les volumes de trigger interrogés.
r.DebugDrawAllSceneQueries=1
; Sans ça, les messages ci-dessus sont calculés mais jamais affichés.
r.AllowScreenMessages=1
"""

TEMPLATE = _HEADER + _BODY


@dataclass
class BoxesStatus:
    """État du mode « boîtes » sur cette machine."""

    supported: bool                 # False hors Windows
    config_dir: Path | None
    ini_path: Path | None
    present: bool                   # un Engine.ini existe
    ours: bool                      # ...et c'est le nôtre (présent au journal)
    message: str = ""

    @property
    def active(self) -> bool:
        return self.present and self.ours

    @property
    def blocked_by_foreign_file(self) -> bool:
        """Un Engine.ini existe et ne vient pas de nous : on n'y touche pas."""
        return self.present and not self.ours


def config_dir() -> Path | None:
    """Dossier de configuration du jeu, ou None si on ne peut pas le déterminer."""
    if sys.platform != "win32":
        # Poste de développement : le dossier n'existe pas. Les fonctions acceptent
        # une racine explicite pour rester testables.
        return None
    local = os.environ.get("LOCALAPPDATA")
    # Exiger un chemin ABSOLU : une valeur relative (héritée d'un environnement bancal)
    # déposerait l'Engine.ini relativement au dossier courant, hors du jeu.
    if not local or not Path(local).is_absolute():
        return None
    return Path(local) / CONFIG_SUBPATH


def _ini_path(root: Path | None) -> Path | None:
    base = root if root is not None else config_dir()
    return base / ENGINE_INI if base is not None else None


def _is_ours(ledger: Ledger, path: Path) -> bool:
    """Le fichier présent a-t-il été déposé par nous et jamais annulé depuis ?

    On s'appuie sur le journal plutôt que sur le contenu du fichier : un utilisateur peut
    avoir édité notre fichier, il reste le nôtre et on doit savoir le retirer.
    """
    target = str(path)
    return any(
        e.target == target and e.action is Action.CREATE_FILE and not e.undone
        for e in ledger.entries
    )


def status(ledger: Ledger, *, root: Path | None = None) -> BoxesStatus:
    """État courant, sans rien modifier."""
    path = _ini_path(root)
    if path is None:
        return BoxesStatus(
            supported=False, config_dir=None, ini_path=None,
            present=False, ours=False,
            message="Le mode « boîtes » n'est disponible que sous Windows : "
                    "le dossier de configuration du jeu n'existe pas ici.")

    present = path.is_file()
    ours = present and _is_ours(ledger, path)
    if not present:
        msg = "Aucun Engine.ini : le mode peut être activé."
    elif ours:
        msg = "Mode « boîtes » actif — Engine.ini déposé par le launcher."
    else:
        msg = ("Un Engine.ini que le launcher n'a pas créé est déjà présent. "
               "Il n'y sera pas touché : déplacez-le ou supprimez-le vous-même "
               "si vous voulez activer le mode « boîtes ».")

    return BoxesStatus(supported=True, config_dir=path.parent, ini_path=path,
                       present=present, ours=ours, message=msg)


@dataclass
class BoxesResult:
    ok: bool
    message: str
    path: Path | None = None


def enable(ledger: Ledger, *, root: Path | None = None) -> BoxesResult:
    """Dépose l'Engine.ini de débogage. Refuse si un fichier étranger est présent.

    Le refus est délibéré : un `Engine.ini` déjà là contient peut-être des réglages
    auxquels l'utilisateur tient, et on ne peut pas distinguer « fichier de test jetable »
    de « configuration soignée ». Écraser serait rapide et destructeur ; on préfère
    expliquer et laisser décider.
    """
    st = status(ledger, root=root)
    if not st.supported or st.ini_path is None:
        return BoxesResult(False, st.message)
    if st.active:
        return BoxesResult(True, "Le mode « boîtes » est déjà actif.", st.ini_path)
    if st.blocked_by_foreign_file:
        return BoxesResult(False, st.message, st.ini_path)

    try:
        st.ini_path.parent.mkdir(parents=True, exist_ok=True)
        # Création exclusive : si le jeu a écrit son propre Engine.ini depuis le
        # contrôle `status()` ci-dessus, l'écriture échoue au lieu d'écraser son
        # fichier — le mode « boîtes » ne touche jamais à un Engine.ini étranger.
        ledger.create_file(st.ini_path, TEMPLATE.encode("utf-8"),
                           label="Engine.ini — mode « boîtes »", group=LEDGER_GROUP,
                           exclusive=True)
    except FileExistsError:
        return BoxesResult(False, status(ledger, root=root).message, st.ini_path)
    except OSError as exc:
        return BoxesResult(False, f"Écriture impossible : {exc}", st.ini_path)

    return BoxesResult(
        True,
        "Mode « boîtes » activé. Il prendra effet au prochain lancement du jeu — "
        "le fichier est lu au démarrage, pas en cours de partie.",
        st.ini_path)


def disable(ledger: Ledger, *, root: Path | None = None) -> BoxesResult:
    """Retire l'Engine.ini que nous avons déposé, en repassant par le journal."""
    st = status(ledger, root=root)
    if not st.supported or st.ini_path is None:
        return BoxesResult(False, st.message)
    if not st.present:
        return BoxesResult(True, "Le mode « boîtes » n'est pas actif.")
    if not st.ours:
        return BoxesResult(False, st.message, st.ini_path)

    results = ledger.undo_group(LEDGER_GROUP)
    failed = [r for r in results if not r.ok]
    if failed:
        return BoxesResult(
            False,
            "Le fichier n'a pas pu être retiré : " + " ; ".join(r.message for r in failed),
            st.ini_path)
    return BoxesResult(True, "Mode « boîtes » désactivé, Engine.ini retiré.", st.ini_path)


def ensure(ledger: Ledger, wanted: bool, *, root: Path | None = None) -> BoxesResult:
    """Aligne l'état sur `wanted`. Appelé juste avant chaque lancement du jeu.

    Le rappel avant CHAQUE lancement n'est pas une précaution inutile : le jeu réécrit
    son dossier de configuration, et une vérification de l'état à l'ouverture du launcher
    serait périmée dès la première partie.
    """
    return enable(ledger, root=root) if wanted else disable(ledger, root=root)
