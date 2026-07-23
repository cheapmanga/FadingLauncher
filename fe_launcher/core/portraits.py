"""Association portrait ↔ personnage, pour la prévisualisation des skins.

Les images viennent du jeu lui-même : l'utilisateur les exporte depuis FModel (dossiers
`UI_VS/Avatars/` et `DataCollections/Enemies/Thumbnail/`) vers `resources/portraits/`.
Le launcher ne les fabrique pas et ne les convertit pas — il se contente de retrouver la
bonne image pour un alias de mesh du mod FESkins.

Pourquoi une résolution par règles plutôt qu'une table figée
------------------------------------------------------------
Le jeu nomme ses portraits de façon inégale : `T_RadioPic_Kheleb` (portrait de menu, net,
cadré visage), `HUD_Avatar_Rahne` (bandeau de HUD, plus large), `T_TN_CritterWater_Shard`
(vignette d'ennemi, une par élément × distance). Un même personnage a donc 0, 1 ou 30
images selon les cas. On classe les candidats par QUALITÉ de cadrage plutôt que de coder
une table nom→fichier qui vieillirait au premier renommage d'export.

Ordre de préférence, du meilleur au moins bon :
    T_RadioPic_*   portrait de menu, le plus propre
    HUD_Avatar_*   bandeau, correct
    T_TN_*_Shard   vignette « shard » : personnage entier, cadrage stable
    T_TN_*         n'importe quelle vignette, en dernier recours

Un alias sans aucune image n'est pas un problème : la page Skins affiche alors une fiche
descriptive. Mieux vaut pas d'image qu'une image trompeuse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RESOURCES = Path(__file__).resolve().parent.parent / "resources" / "portraits"

# Nom du personnage tel qu'il apparaît DANS LES FICHIERS, par alias du mod FESkins.
# Le jeu écrit « Rhane » (sans le premier a) : on colle à ses fichiers, pas à
# l'orthographe du mod. Un alias absent d'ici est cherché sur l'alias lui-même.
_ALIAS_TO_ASSET: dict[str, str] = {
    "rahne": "Rhane",
    "hero": "One",
    "one": "One",
    "mime": "Bob",          # Marcel Bob partage le portrait de Bob
    "bob": "Bob",
    "kheleb": "Kheleb",
    "agent": "Agent",
    "critter": "Critter",
    "ranged": "Ranged",
    "rusher": "Rusher",
    "disappear": "Disappear",
    "vellum": "Vellum",
    "maddock": "Maddock",
}

# Rang de préférence d'un fichier selon son préfixe. Plus petit = meilleur.
_PREFIX_RANK = (
    (re.compile(r"^T_RadioPic_", re.I), 0),
    (re.compile(r"^HUD_Avatar_", re.I), 1),
    (re.compile(r"^T_TN_.*Shard", re.I), 2),
    (re.compile(r"^T_TN_", re.I), 3),
)


@dataclass(frozen=True)
class Portrait:
    alias: str
    path: Path | None
    asset_name: str = ""

    @property
    def found(self) -> bool:
        return self.path is not None


def _rank(filename: str) -> int:
    for pattern, rank in _PREFIX_RANK:
        if pattern.match(filename):
            return rank
    return 99


@lru_cache(maxsize=1)
def _index(resources: Path = RESOURCES) -> list[Path]:
    """Toutes les images disponibles, triées par qualité de cadrage croissante.

    Mise en cache : la page Skins interroge le résolveur une fois par personnage, et le
    dossier ne bouge pas en cours de session. `refresh()` vide le cache si l'utilisateur
    vient de déposer de nouveaux exports.
    """
    if not resources.is_dir():
        return []
    imgs = [p for p in resources.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    imgs.sort(key=lambda p: (_rank(p.name), p.name))
    return imgs


def refresh() -> None:
    """À appeler après un dépôt de nouveaux PNG."""
    _index.cache_clear()


def resolve(alias: str, *, resources: Path = RESOURCES) -> Portrait:
    """Meilleure image pour un alias de mesh, ou une fiche vide si rien ne correspond."""
    asset = _ALIAS_TO_ASSET.get(alias.lower(), alias)
    # Frontière de token, pas un simple `\b` : les vignettes d'ennemis collent le nom du
    # personnage à son élément — `T_TN_CritterLava_Mid`. Il faut donc autoriser une
    # MAJUSCULE juste après (frontière CamelCase : « Critter » puis « Lava »), tout en
    # rejetant une minuscule qui prolongerait le mot — sinon « Range » capterait
    # « Ranged ». Devant : pas de lettre (on ne veut pas d'un match en milieu de mot).
    # Pas de `re.I` : le lookahead `[a-z]` doit distinguer la casse (une majuscule
    # suivante est une frontière CamelCase valide), et les fichiers du jeu ont une casse
    # fixe qui correspond déjà à `_ALIAS_TO_ASSET`.
    needle = re.compile(rf"(?<![A-Za-z]){re.escape(asset)}(?![a-z])")

    imgs = _index(resources) if resources == RESOURCES else _rebuild(resources)
    for path in imgs:  # déjà triées par préférence
        if needle.search(path.stem):
            return Portrait(alias=alias, path=path, asset_name=asset)
    return Portrait(alias=alias, path=None, asset_name=asset)


def _rebuild(resources: Path) -> list[Path]:
    """Version non mise en cache, pour les tests qui pointent un autre dossier."""
    if not resources.is_dir():
        return []
    imgs = [p for p in resources.iterdir()
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    imgs.sort(key=lambda p: (_rank(p.name), p.name))
    return imgs


def coverage(aliases: list[str], *, resources: Path = RESOURCES) -> dict[str, Portrait]:
    """Portrait résolu pour chaque alias — pour peupler la galerie d'un coup."""
    return {a: resolve(a, resources=resources) for a in aliases}
