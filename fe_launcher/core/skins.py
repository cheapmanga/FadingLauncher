"""Sélection de skin : catalogue des personnages et pilotage du mod FESkins.

Comment un skin est réellement appliqué
---------------------------------------
Le mod `ue4ss-FESkins` ne s'active qu'à la console F10 en jeu, et le launcher est un
processus séparé qui ne peut pas parler à un jeu déjà lancé. On agit donc en amont : le
mod a reçu des constantes `BOOT_*` en tête de son `main.lua`, que le launcher réécrit
(via le journal, donc réversibles). Le skin choisi est appliqué au PROCHAIN démarrage
du jeu, pas immédiatement — c'est dit clairement dans l'interface.

Le catalogue
------------
Les 21 meshes viennent de la table `MESHES` du mod ; on les redéclare ici plutôt que de
parser le Lua, parce qu'on y ajoute ce que le mod ne porte pas : un libellé lisible, un
avertissement par cas, et le lien vers le portrait (`portraits.py`). Toute divergence
avec le mod se verrait au test — `test_skins` compare les alias.

L'avertissement de lag
----------------------
Changer de skin fait ramer, et ce n'est pas un défaut du launcher : le mod maintient des
boucles de réapplication toutes les 1,5 s, et un swap de mesh active un « entretien
permanent » qui refait le travail en continu pour que le jeu ne réécrase pas le mesh.
C'est structurel. On l'affiche une fois pour toutes plutôt que de le laisser découvrir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import luaconf, portraits
from .ledger import Ledger
from .mods import Mod

LEDGER_GROUP = "skins"

# Avertissement affiché en tête de la page. Vrai pour tout changement de skin.
LAG_WARNING = (
    "Changer de skin fait ramer le jeu. Ce n'est pas un bug du launcher : le mod "
    "réapplique le skin en boucle pour empêcher le jeu de le réécraser. Plus le "
    "personnage est éloigné de One, plus c'est coûteux."
)


@dataclass(frozen=True)
class SkinEntry:
    """Un personnage sélectionnable."""

    alias: str                # clé passée au mod (BOOT_MESH)
    label: str                # nom lisible
    note: str = ""            # avertissement spécifique, '' si aucun

    @property
    def portrait(self) -> Path | None:
        return portraits.resolve(self.alias).path

    @property
    def has_portrait(self) -> bool:
        return self.portrait is not None


# Redéclaration de la table MESHES du mod, enrichie. L'ordre est celui de la galerie :
# les personnages jouables « propres » d'abord, les curiosités ensuite.
CHARACTERS: list[SkinEntry] = [
    SkinEntry("one", "One (d'origine)"),
    SkinEntry("bob", "Bob"),
    SkinEntry("mime", "Marcel Bob",
              "Bob en tenue de mime (squelette SKEL_Bob_Mime)."),
    SkinEntry("rahne", "Rahne"),
    SkinEntry("kheleb", "Kheleb"),
    SkinEntry("agent", "Agent"),
    SkinEntry("critter", "Critter"),
    SkinEntry("ranged", "Ranged"),
    SkinEntry("rusher", "Rusher"),
    SkinEntry("builder", "Builder"),
    SkinEntry("bungee", "BungeeMan"),
    SkinEntry("disappear", "Disappear"),
    SkinEntry("wonder", "Last Wonder"),
    SkinEntry("wonder2", "Last Wonder (2)"),
    SkinEntry("wonder4", "Last Wonder (4)"),
    SkinEntry("wonder5", "Last Wonder (5)"),
    SkinEntry("mannequin", "Mannequin Unreal",
              "Mesh de test Unreal, sans rapport avec le jeu."),
    SkinEntry("cine", "Builder (cinématique)"),
    SkinEntry("hat", "Chapeau de Rahne (gag)"),
    SkinEntry("alien", "Alien Animal",
              "Nécessite le pak custom AA_Alien_P monté, sinon sans effet."),
]

# Squelettes compatibles avec celui de One : les autres seront figés ou déformés.
# C'est attendu et documenté dans le mod ; on le redit sur les entrées concernées.
_SHARES_ONE_SKELETON = {"one", "hero"}

_DEFORM_NOTE = ("Squelette différent de One : le modèle sera figé ou déformé. "
                "C'est normal, pas un bug.")

# Les 5 skins de matériaux de One, dont 3 jamais exposés dans le menu du jeu.
ONE_SKINS = {
    0: "Défaut",
    1: "Hellgur One",
    2: "Skin 2 (caché)",
    3: "Skin 3 (caché)",
    4: "Skin 4 (caché)",
}


def character(alias: str) -> SkinEntry | None:
    for c in CHARACTERS:
        if c.alias == alias:
            return c
    return None


def deform_note(alias: str) -> str:
    """Avertissement de déformation, si le mesh ne partage pas le squelette de One."""
    return "" if alias in _SHARES_ONE_SKELETON else _DEFORM_NOTE


@dataclass
class SkinState:
    """Ce que les constantes BOOT_* du mod disent de l'état au prochain démarrage."""

    mesh: str = "none"
    one_skin: int = -1
    outline: str = "keep"        # keep | off | on
    hide_stick: bool = False
    hide_hair: bool = False

    @property
    def active_character(self) -> SkinEntry | None:
        return character(self.mesh) if self.mesh != "none" else None


def read_state(mod: Mod) -> SkinState | None:
    """Lit l'état voulu depuis les constantes du mod. None si le mod n'est pas là."""
    if mod.script is None or not mod.script.is_file():
        return None
    settings = {s.name: s.value for s in luaconf.parse(mod.script)}
    if "BOOT_MESH" not in settings:
        return None  # mod présent mais sans le bloc BOOT : version trop ancienne.
    return SkinState(
        mesh=str(settings.get("BOOT_MESH", "none")),
        one_skin=int(settings.get("BOOT_SKIN", -1)),
        outline=str(settings.get("BOOT_OUTLINE", "keep")),
        hide_stick=bool(settings.get("BOOT_HIDE_STICK", False)),
        hide_hair=bool(settings.get("BOOT_HIDE_HAIR", False)),
    )


@dataclass
class ApplyReport:
    ok: bool
    changed: list[str] = field(default_factory=list)
    message: str = ""


def apply(mod: Mod, state: SkinState, ledger: Ledger) -> ApplyReport:
    """Écrit l'état voulu dans les constantes du mod, chaque changement journalisé.

    On ne réécrit QUE les constantes qui changent : inutile de journaliser une valeur
    identique, et ça garde le journal lisible. L'application est réversible d'un bloc
    (même groupe) depuis la page Désinstallation.
    """
    if mod.script is None or not mod.script.is_file():
        return ApplyReport(False, message="Le mod FESkins n'est pas installé.")

    current = read_state(mod)
    if current is None:
        return ApplyReport(
            False,
            message="Ce FESkins est une version sans le bloc de démarrage : "
                    "réinstallez le mod fourni avec le launcher.")

    wanted = {
        "BOOT_MESH": state.mesh,
        "BOOT_SKIN": state.one_skin,
        "BOOT_OUTLINE": state.outline,
        "BOOT_HIDE_STICK": state.hide_stick,
        "BOOT_HIDE_HAIR": state.hide_hair,
    }
    changed: list[str] = []
    for name, value in wanted.items():
        setting = next((s for s in luaconf.parse(mod.script) if s.name == name), None)
        if setting is None or setting.value == value:
            continue
        ledger.lua_set(mod.script, name, setting.value, value,
                       label=f"FESkins {name} → {value}", group=LEDGER_GROUP)
        luaconf.write(mod.script, name, value)
        changed.append(name)

    if not changed:
        return ApplyReport(True, message="Aucun changement : le skin voulu est déjà réglé.")
    return ApplyReport(
        True, changed=changed,
        message="Skin enregistré. Il sera appliqué au prochain lancement du jeu.")


def reset(mod: Mod, ledger: Ledger) -> ApplyReport:
    """Remet l'apparence d'origine (One, sans masquage, outline par défaut)."""
    return apply(mod, SkinState(), ledger)
