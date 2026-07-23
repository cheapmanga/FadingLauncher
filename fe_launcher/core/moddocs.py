"""Notice d'utilisation de chaque mod, et mods à accès restreint.

Deux problèmes distincts sont traités ici.

**1. Personne ne sait ce que fait un mod à son nom.** « FEChestHopper » ou « FormForcer »
ne disent rien à quelqu'un qui découvre l'outil, et 4 des mods du projet n'ont aucun
README. La notice est donc construite en trois couches, de la plus fiable à la moins
précise :

    notice rédigée à la main (ci-dessous)  >  README.md du mod  >  en-tête du main.lua

Les touches et commandes affichées, elles, ne sont jamais recopiées d'une notice : elles
sont lues dans le code du mod (`Mod.keybinds`, `Mod.commands`). Une notice peut mentir ou
vieillir, le code non — c'est d'ailleurs déjà arrivé dans ce projet, où le README de
FEInfiniteCore annonce un défaut de 500 ms alors que le code embarque 1200.

**2. Tous les mods n'ont pas vocation à être exposés de la même façon.** `ue4ss-FEDevMenu`
n'est pas un mod de confort : il débloque le menu de développement du jeu et appelle les
23 fonctions du `YgroCheatManager`, c'est-à-dire l'outillage interne du studio (vie
infinie, tuer tous les ennemis, téléportation, déblocage de toutes les capacités, maps de
debug). Le rendre disponible d'un clic dans un outil grand public, c'est diffuser une
surface que le studio n'a pas choisi de publier.

Il est donc marqué RESTREINT : masqué tant que le mode développeur n'est pas activé dans
les paramètres, et volontairement peu documenté. Ce n'est pas un verrou de sécurité — le
dossier du mod reste sur le disque et quiconque sait ce qu'il fait peut l'activer à la
main. C'est un choix de présentation : ne pas mettre en avant ce qui n'a pas à l'être.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Mods dont l'accès passe par le mode développeur.
RESTRICTED: set[str] = {"ue4ss-FEDevMenu"}


@dataclass
class ModDoc:
    """Notice affichable d'un mod."""

    summary: str = ""                              # une phrase : ce que ça fait
    usage: list[str] = field(default_factory=list) # étapes concrètes
    warnings: list[str] = field(default_factory=list)
    source: str = "aucune"                         # 'notice' | 'readme' | 'en-tête' | 'aucune'
    restricted: bool = False

    @property
    def documented(self) -> bool:
        return bool(self.summary)


# --- Notices rédigées à la main --------------------------------------------------
# Priorité sur les README : plus courtes, orientées « à quoi ça sert pour moi ».
# Les 4 mods sans README (FESkins, FEKillAll, FEPerkExplorer, FESpeedons) en dépendent
# entièrement.

_CURATED: dict[str, ModDoc] = {
    "ue4ss-FEInfiniteCore": ModDoc(
        summary="Reproduit le glitch du Core infini : donne un Core, puis provoque une "
                "mort dans le vide après un délai réglable, ce qui conserve la charge "
                "élémentaire au respawn.",
        usage=[
            "Réglez « Void delay ms » : c'est le délai entre la prise du Core et la chute.",
            "En jeu, F7 lance la séquence complète (Core + chute), F8 déclenche la chute seule.",
            "Observez l'interface au respawn : la charge est-elle conservée ?",
        ],
        warnings=[
            "Le glitch est une course entre deux traitements séparés d'une seule frame : "
            "il ne réussit qu'une fois sur 10 à 30. Un échec ne veut pas dire que le "
            "réglage est mauvais — c'est précisément pour ça que le Banc d'essai existe.",
            "Le mod est livré avec un délai de 1200 ms alors que sa propre notice annonce "
            "500 ms. Le launcher pilote cette valeur lui-même pendant une campagne.",
        ],
    ),
    "ue4ss-FEMoonJump": ModDoc(
        summary="Saut infini et vol libre : permet de monter indéfiniment et de "
                "sauter autant de fois qu'on veut.",
        usage=[
            "F7 active le vol : maintenez la touche de saut pour monter.",
            "F6 passe le nombre de sauts à 999, ce qui autorise le multi-saut au sol.",
            "« Rise speed » règle la vitesse de montée.",
        ],
        warnings=["F7 est aussi utilisée par d'autres mods — voyez les conflits signalés."],
    ),
    "ue4ss-FESkins": ModDoc(
        summary="Change l'apparence de One, y compris les skins présents dans le jeu mais "
                "absents du menu, et permet de remplacer son modèle par n'importe quel "
                "personnage.",
        usage=[
            "Cinq skins existent (0 à 4). Le menu du jeu n'en propose que deux : "
            "0 (défaut) et 1 (« Hellgur One »).",
            "Les skins 2, 3 et 4 sont complets mais n'ont jamais eu d'entrée de menu.",
            "Le sélecteur de modèle propose 21 personnages, dont Bob, Rahne et l'Agent.",
        ],
        warnings=[
            "Seul One partage son squelette : les autres modèles seront figés ou déformés. "
            "C'est attendu, ce n'est pas un bug.",
            "Le menu Customization du jeu ne peut pas être étendu — la liste est construite "
            "en dur au lancement de l'écran d'options.",
        ],
    ),
    "ue4ss-FormForcer": ModDoc(
        summary="Force la forme du personnage : eau, déchet, vapeur, nitro ou corruption.",
        usage=["Choisissez une forme ; le mode persistant la maintient en boucle."],
        warnings=[
            "La forme Corruption (« glitch ») fait planter le jeu de façon confirmée : "
            "sa jauge n'est pas initialisée sur le personnage. Elle reste bloquée derrière "
            "une confirmation explicite.",
        ],
    ),
    "ue4ss-FEChestHopper": ModDoc(
        summary="Téléporte de coffre en coffre dans la zone chargée.",
        usage=["Enchaînez les coffres un par un, ou sautez directement à un numéro."],
        warnings=["Seuls les coffres de la zone actuellement chargée sont atteignables."],
    ),
    "ue4ss-FESourceGiver": ModDoc(
        summary="Manipule le nombre de sources branchées au Bastion, ce qui commande "
                "l'accès au combat final.",
        usage=["Le combat final s'ouvre à 12 sources branchées (3 par zone, 4 zones)."],
        warnings=["Ces manipulations salissent la sauvegarde : ne les mélangez pas avec "
                  "une campagne de mesure sur la même partie."],
    ),
    "ue4ss-FEXpGiver": ModDoc(
        summary="Donne des points d'Ætherfact, la monnaie des améliorations.",
        usage=["Indiquez le nombre de points à ajouter."],
    ),
    "ue4ss-FECoreGiver": ModDoc(
        summary="Fait apparaître un Core de l'élément voulu : eau, déchet, feu, "
                "corruption ou énergie.",
        usage=["Choisissez l'élément ; l'option « nograb » le pose sans le ramasser."],
        warnings=["Fait double emploi avec FEUnlocker-Plus, qui fournit la même commande : "
                  "n'activez que l'un des deux."],
    ),
    "ue4ss-FEFreeRoam": ModDoc(
        summary="Lève les barrières invisibles, désactive le renvoi automatique au Bastion "
                "et neutralise les zones de mort.",
        usage=["Utile pour explorer hors des limites prévues."],
    ),
    "ue4ss-FEKillAll": ModDoc(
        summary="Tue tous les ennemis de la zone chargée.",
        usage=["Une seule commande, sans réglage."],
        warnings=["Existe parce que la fonction équivalente du jeu ne fonctionne pas."],
    ),
    "ue4ss-FEUnlocker-Plus": ModDoc(
        summary="Débloque les zones, les murs, les ascenseurs, les escaliers et les portes, "
                "et permet de se téléporter aux points de passage.",
        usage=["F1 lève les murs rouges, F2 les escaliers rotatifs, F3 appelle l'ascenseur "
               "le plus proche, F4 affiche l'aide."],
    ),
    "ue4ss-FEPerf": ModDoc(
        summary="Dix préréglages de performance, du plus beau au plus fluide, avec un "
                "affichage des temps d'image.",
        usage=[
            "Les touches du pavé numérique + et − passent d'un préréglage à l'autre.",
            "Verrouiller le framerate est indispensable avant une campagne de mesure : "
            "un délai en millisecondes ne veut rien dire sans lui.",
        ],
        warnings=["Certains réglages sont ignorés par le jeu en version commerciale, "
                  "sans message d'erreur."],
    ),
    "ue4ss-FEPerkExplorer": ModDoc(
        summary="Outil de diagnostic : liste les améliorations et étiquettes du personnage "
                "dans la console.",
        usage=["Conçu pour l'inspection, pas pour le jeu. N'affiche rien à l'écran."],
    ),
    "ue4ss-KeystrokesKBM-Lua": ModDoc(
        summary="Affiche à l'écran les touches clavier et souris pressées — pour le stream "
                "et la relecture d'un run.",
        usage=["F8 affiche ou masque l'incrustation, F9 lance un auto-diagnostic."],
        warnings=["Ne peut pas fonctionner en même temps que la version manette : "
                  "les deux utilisent F8 et F9."],
    ),
    "ue4ss-KeystrokesPad-Lua": ModDoc(
        summary="Affiche à l'écran les boutons de manette pressés, gâchettes et sticks "
                "compris.",
        usage=["F8 affiche ou masque l'incrustation, F9 lance un auto-diagnostic."],
        warnings=["Ne peut pas fonctionner en même temps que la version clavier."],
    ),
    "ue4ss-FEDevMenu": ModDoc(
        # Volontairement sommaire : voir la docstring du module.
        summary="Outillage de développement interne du jeu.",
        usage=[],
        warnings=["Réservé au mode développeur. Ces fonctions ne sont pas prévues pour "
                  "être utilisées en jeu normal et peuvent rendre une partie incohérente."],
        restricted=True,
    ),
}

# Mods C++ non compilés : même notice, le détail n'apporte rien tant qu'il n'y a pas de DLL.
for _name in ("ue4ss-FECheatUtils", "ue4ss-KeystrokesKBM", "ue4ss-KeystrokesPad"):
    _CURATED.setdefault(_name, ModDoc(
        summary="Version C++ d'un mod, à compiler avant utilisation.",
        warnings=["Aucune bibliothèque compilée n'est présente : activer ce mod n'aura "
                  "aucun effet tant qu'il n'est pas construit."],
    ))


_HEADING_RE = re.compile(r"^#{1,6}\s")
_BADGE_RE = re.compile(r"^[\[!|`>-]")


def _from_readme(text: str) -> str:
    """Premier paragraphe utile d'un README, comme résumé de repli."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _HEADING_RE.match(line) or _BADGE_RE.match(line):
            continue
        if len(line) > 25:
            return line
    return ""


def doc_for(mod) -> ModDoc:
    """Notice d'un mod, en descendant les couches jusqu'à trouver quelque chose.

    `mod` est un `mods.Mod` ; on ne l'importe pas pour éviter un cycle, seuls
    `name`, `readme` et `description` sont utilisés.
    """
    curated = _CURATED.get(mod.name)
    if curated is not None:
        d = ModDoc(summary=curated.summary, usage=list(curated.usage),
                   warnings=list(curated.warnings), source="notice",
                   restricted=curated.restricted)
        return d

    if getattr(mod, "readme", None) is not None:
        try:
            summary = _from_readme(mod.readme.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            summary = ""
        if summary:
            return ModDoc(summary=summary, source="readme",
                          restricted=mod.name in RESTRICTED)

    if getattr(mod, "description", ""):
        return ModDoc(summary=mod.description, source="en-tête",
                      restricted=mod.name in RESTRICTED)

    return ModDoc(source="aucune", restricted=mod.name in RESTRICTED)


def is_restricted(name: str) -> bool:
    return name in RESTRICTED or _CURATED.get(name, ModDoc()).restricted


def visible_mods(all_mods: list, *, developer_mode: bool) -> list:
    """Filtre les mods à présenter. En mode normal, les mods restreints sont masqués."""
    if developer_mode:
        return list(all_mods)
    return [m for m in all_mods if not is_restricted(m.name)]
