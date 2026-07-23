"""Inventaire, activation et analyse des mods UE4SS.

Les règles encodées ici viennent toutes de logs UE4SS réels (v3.0.1, PC de jeu),
pas de la documentation d'UE4SS. Les trois faits qui gouvernent ce module :

1. UE4SS démarre les mods en DEUX PASSES SÉQUENTIELLES, pas une :
       Starting mods (from mods.txt ... load order)...
       Starting mods (from enabled.txt ..., no defined load order)...
   La première lit `mods.txt` (`Nom : 1` / `Nom : 0`) et définit l'ordre de chargement.
   La seconde démarre TOUT dossier de `Mods/` contenant un fichier `enabled.txt`.

2. C'est la PRÉSENCE du fichier `enabled.txt` qui active, pas son contenu — tous les
   `enabled.txt` du projet font 0 octet. Écrire `0` dedans ne désactive rien.

3. Conséquence contre-intuitive, et c'est le piège principal : mettre `Nom : 0` dans
   `mods.txt` NE DÉSACTIVE PAS un mod qui possède aussi un `enabled.txt`, puisque la
   seconde passe le rattrape. La seule désactivation fiable est de retirer `enabled.txt`.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import luaconf
from .luaconf import LuaSetting, LuaType
from .paths import Ue4ssLayout

# On renomme plutôt que supprimer : un enabled.txt est vide, mais le renommage rend
# la désactivation triviale à annuler et laisse une trace visible dans le dossier.
DISABLED_SUFFIX = ".disabled"

_KEYBIND_RE = re.compile(r"RegisterKeyBind\s*\(\s*(?:Key\.)?([A-Za-z_]\w*)")
_CONSOLE_RE = re.compile(r'RegisterConsoleCommand(?:Global)?Handler\s*\(\s*["\']([^"\']+)["\']')
_HOOK_RE = re.compile(r'RegisterHook\s*\(\s*["\']([^"\']+)["\']')
_REQUIRE_RE = re.compile(r'require\s*\(\s*["\']([^"\']+)["\']')


class ModKind(Enum):
    LUA = "lua"
    CPP = "cpp"
    UNKNOWN = "unknown"


class ModState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    #  Activé mais inopérant : mod C++ dont la DLL n'a jamais été compilée.
    BROKEN = "broken"


@dataclass
class Mod:
    """Un dossier de mod dans `Mods/`."""

    name: str
    path: Path
    kind: ModKind
    state: ModState
    script: Path | None = None          # Scripts/main.lua
    dll: Path | None = None             # dlls/main.dll
    readme: Path | None = None
    keybinds: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    settings: list[LuaSetting] = field(default_factory=list)
    description: str = ""
    in_mods_txt: bool | None = None     # None = absent du fichier

    @property
    def enabled_marker(self) -> Path:
        return self.path / "enabled.txt"

    @property
    def editable_settings(self) -> list[LuaSetting]:
        return [s for s in self.settings if s.editable]

    def setting(self, name: str) -> LuaSetting | None:
        for s in self.settings:
            if s.name == name:
                return s
        return None


def _first_doc_line(script: Path) -> str:
    """Première ligne de commentaire utile en tête de fichier, comme description."""
    try:
        for line in script.read_text(encoding="utf-8", errors="replace").splitlines()[:15]:
            stripped = line.strip()
            if stripped.startswith("--"):
                text = stripped.lstrip("-").strip()
                # On saute les lignes de décoration (----, ====) et les titres vides.
                if len(text) > 12 and not set(text) <= set("=-_ #*"):
                    return text
    except OSError:
        pass
    return ""


_KEY_LITERAL_RE = re.compile(r"\bKey\.([A-Z][A-Z0-9_]*)\b")

# Jetons qui ne sont manifestement pas des touches : paramètres de fonction, variables
# de boucle. Leur présence signale qu'il faut se rabattre sur les littéraux du fichier.
_NOT_A_KEY = re.compile(r"^[a-z]")


def _resolve_keys(tokens: list[str], settings: list[LuaSetting],
                  text: str = "") -> list[str]:
    """Traduit les jetons de `RegisterKeyBind` en noms de touches exploitables.

    Tous les mods n'écrivent pas `RegisterKeyBind(Key.F7, ...)`. Certains passent une
    constante — `RegisterKeyBind(ACTIVATE_KEY, ...)` dans VoidCancel, `K_UP` dans FEPerf —
    et la regex ne récupère alors que le nom de la variable. Sans résolution, la détection
    de conflits est aveugle sur ces mods : deux mods pourraient revendiquer F7 sans qu'on
    le voie, et c'est précisément le genre de collision qui pollue une campagne de mesure.

    On résout donc chaque jeton contre les constantes du fichier. Une constante qui vaut
    elle-même une expression (`Key.ADD or Key.NUM_NINE`) est décodée en prenant la
    première touche nommée.

    Reste un cas indécidable statiquement : `FadingEchoTrainer` enveloppe l'appel dans
    `registerKey(nom, key, callback)`, où la touche est un PARAMÈTRE. Suivre ça
    demanderait d'interpréter le Lua. On se rabat alors sur tous les littéraux `Key.X`
    du fichier — ici `Key.F6` et `Key.F7`, effectivement les touches du mod.

    Ce repli peut sur-signaler (un `Key.X` cité sans être lié). C'est délibéré : rater
    un conflit corrompt silencieusement une campagne de mesure, alors qu'un conflit
    signalé à tort coûte une vérification à l'utilisateur.
    """
    by_name = {s.name: s for s in settings}
    out: list[str] = []
    unresolved = False

    for token in tokens:
        resolved = token
        setting = by_name.get(token)
        if setting is not None and isinstance(setting.value, str) and setting.value:
            resolved = setting.value
        elif setting is not None and setting.type is LuaType.UNKNOWN:
            m = _KEY_LITERAL_RE.search(setting.raw_value)
            if m:
                resolved = m.group(1)
        resolved = resolved.removeprefix("Key.")
        if _NOT_A_KEY.match(resolved):
            unresolved = True
            continue
        out.append(resolved)

    if unresolved and text:
        out.extend(_KEY_LITERAL_RE.findall(text))

    return list(dict.fromkeys(out))


def _scan_script(mod: Mod) -> None:
    if mod.script is None or not mod.script.is_file():
        return
    try:
        text = mod.script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    mod.settings = luaconf.parse(mod.script)
    # dict.fromkeys : dédoublonne en gardant l'ordre d'apparition dans le fichier.
    mod.keybinds = _resolve_keys(_KEYBIND_RE.findall(text), mod.settings, text)
    mod.commands = list(dict.fromkeys(_CONSOLE_RE.findall(text)))
    mod.hooks = list(dict.fromkeys(_HOOK_RE.findall(text)))
    mod.requires = list(dict.fromkeys(_REQUIRE_RE.findall(text)))
    mod.description = _first_doc_line(mod.script)


def parse_mods_txt(path: Path) -> dict[str, bool]:
    """`mods.txt` -> {nom: activé}. Les lignes vides et commentaires sont ignorés."""
    out: dict[str, bool] = {}
    if not path.is_file():
        return out
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.split(";", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, _, flag = line.partition(":")
        out[name.strip()] = flag.strip() == "1"
    return out


def load(layout: Ue4ssLayout) -> list[Mod]:
    """Inventorie tous les mods présents, triés par nom."""
    if not layout.mods_dir.is_dir():
        return []

    declared = parse_mods_txt(layout.mods_txt)
    mods: list[Mod] = []

    for entry in sorted(layout.mods_dir.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or entry.name == "shared":
            continue

        script = entry / "Scripts" / "main.lua"
        dll = entry / "dlls" / "main.dll"
        has_script, has_dll = script.is_file(), dll.is_file()

        if has_script:
            kind = ModKind.LUA
        elif has_dll or (entry / "dlls").is_dir() or (entry / "dllmain.cpp").is_file():
            kind = ModKind.CPP
        else:
            kind = ModKind.UNKNOWN

        # Un mod est chargé s'il passe par L'UNE des deux voies : une entrée à 1 dans
        # mods.txt (première passe) OU un enabled.txt (seconde passe). Ne regarder que
        # le marqueur ferait passer tous les mods intégrés d'UE4SS — BPModLoaderMod,
        # ConsoleEnablerMod… — pour désactivés alors qu'ils sont bel et bien chargés.
        marker_present = (entry / "enabled.txt").is_file()
        declared_on = declared.get(entry.name) is True
        if not (marker_present or declared_on):
            state = ModState.DISABLED
        elif kind is ModKind.UNKNOWN or (kind is ModKind.CPP and not has_dll):
            # Le dossier est activé mais n'a rien à exécuter : ni script, ni DLL. Cas
            # réel rencontré en jeu — une réinstallation d'UE4SS par-dessus avait vidé
            # `ue4ss-FECoreGiver/` en laissant son `enabled.txt`, et UE4SS répondait
            # « Main script 'main.lua' not found ». Sans ce cas, le launcher affichait
            # le mod comme ACTIF pendant qu'il échouait au chargement : le pire des
            # états, puisqu'il donne confiance dans quelque chose qui ne marche pas.
            state = ModState.BROKEN
        else:
            state = ModState.ENABLED

        readme = entry / "README.md"
        mod = Mod(
            name=entry.name,
            path=entry,
            kind=kind,
            state=state,
            script=script if has_script else None,
            dll=dll if has_dll else None,
            readme=readme if readme.is_file() else None,
            in_mods_txt=declared.get(entry.name),
        )
        _scan_script(mod)
        mods.append(mod)

    return mods


# --- Activation -----------------------------------------------------------------

def set_enabled(mod: Mod, enabled: bool) -> ModState:
    """Active ou désactive un mod, et retourne son nouvel état.

    Activer  = créer `enabled.txt` vide.
    Désactiver = renommer `enabled.txt` en `enabled.txt.disabled`.

    On NE touche PAS à `mods.txt` : pour les mods maison, il ne sert à rien, et y
    écrire `Nom : 0` donnerait la fausse impression d'avoir désactivé le mod alors
    que la seconde passe le redémarrerait.
    """
    marker = mod.enabled_marker
    off = marker.with_name(marker.name + DISABLED_SUFFIX)

    if enabled:
        if off.is_file() and not marker.is_file():
            off.replace(marker)
        elif not marker.is_file():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_bytes(b"")
        mod.state = (
            ModState.BROKEN
            if mod.kind is ModKind.CPP and mod.dll is None
            else ModState.ENABLED
        )
    else:
        if marker.is_file():
            if off.is_file():
                off.unlink()
            marker.replace(off)
        mod.state = ModState.DISABLED

    return mod.state


def install_from_dir(source: Path, layout: Ue4ssLayout, *, overwrite: bool = False) -> Mod:
    """Copie un dossier de mod dans `Mods/` et retourne le mod installé."""
    source = Path(source)
    if not source.is_dir():
        raise NotADirectoryError(source)
    dest = layout.mods_dir / source.name
    if dest.exists():
        if not overwrite:
            raise FileExistsError(f"{source.name} est déjà installé")
        shutil.rmtree(dest)
    shutil.copytree(source, dest)

    for mod in load(layout):
        if mod.name == source.name:
            return mod
    raise RuntimeError(f"{source.name} copié mais introuvable après relecture")


# --- Analyse des conflits -------------------------------------------------------

# Touches déjà prises par le jeu ou par UE4SS. Un mod qui se lie dessus n'entre en
# conflit avec AUCUN autre mod — la comparaison mod-à-mod ne peut donc pas le voir — et
# pourtant il casse quelque chose.
#
# N'inscrire ici QUE des touches dont la réservation est vérifiée dans les fichiers du
# projet. Une entrée inventée produit un avertissement sur un mod parfaitement sain, ce
# qui apprend à l'utilisateur à ignorer les avertissements — le pire résultat possible.
#
# Cas d'école : `INS` a d'abord été inscrite ici comme « console GUI d'UE4SS ». C'est
# faux — c'est la touche de rechargement de BPModLoaderMod, un mod livré d'origine.
# L'entrée signalait donc un conflit inexistant sur une installation standard.
#
# F10 est vérifiée : les README de FECoreGiver et FESourceGiver disent « console in-game,
# ouverte avec F10 ». C'est par elle que passent TOUTES les commandes des mods (`core`,
# `source`, `xp`, `skin`…) — un mod lié sur F10 prive l'utilisateur de tous les autres.
RESERVED_KEYS: dict[str, str] = {
    "F10": "console in-game — c'est par elle que passent les commandes des autres mods "
           "(core, source, xp, skin…)",
}


@dataclass(frozen=True)
class Conflict:
    """Une ressource disputée : entre mods, ou avec une touche réservée."""

    kind: str            # 'keybind' | 'command' | 'reserved'
    resource: str        # 'F7' | 'core' | 'F10'
    mods: tuple[str, ...]
    reason: str = ""     # pour 'reserved' : à quoi sert la touche

    @property
    def message(self) -> str:
        who = ", ".join(self.mods)
        if self.kind == "reserved":
            return (f"La touche {self.resource} est réservée ({self.reason}) "
                    f"et pourtant utilisée par : {who}")
        if self.kind == "keybind":
            return f"La touche {self.resource} est utilisée par {len(self.mods)} mods : {who}"
        return f"La commande console `{self.resource}` est enregistrée par : {who}"


def conflicts(mods: list[Mod], *, enabled_only: bool = True) -> list[Conflict]:
    """Collisions de touches et de commandes console entre mods.

    Réel dans ce projet : F7 est revendiquée par trois mods (FEMoonJump,
    FEInfiniteCore, FEPerkExplorer) et F8 par trois autres. Un appui déclenche alors
    toutes les actions à la fois — ce qui, pendant une campagne de mesure, invalide
    silencieusement les essais.
    """
    pool = [m for m in mods if not enabled_only or m.state is ModState.ENABLED]

    def collect(attr: str, kind: str) -> list[Conflict]:
        owners: dict[str, list[str]] = {}
        for mod in pool:
            for res in getattr(mod, attr):
                owners.setdefault(res, []).append(mod.name)
        return [
            Conflict(kind=kind, resource=res, mods=tuple(names))
            for res, names in sorted(owners.items())
            if len(names) > 1
        ]

    # Un mod SEUL sur une touche réservée est quand même un conflit : la comparaison
    # mod-à-mod ne le verrait jamais, alors qu'il prive l'utilisateur de la console.
    reserved = [
        Conflict(kind="reserved", resource=key, mods=(mod.name,), reason=why)
        for mod in pool
        for key, why in RESERVED_KEYS.items()
        if key in mod.keybinds
    ]

    return collect("keybinds", "keybind") + reserved + collect("commands", "command")
