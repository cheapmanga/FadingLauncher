"""Lecture et réécriture des constantes de configuration en tête des mods Lua.

Fait vérifié : AUCUN mod de Fading Echo ne lit de fichier de configuration externe.
Tous leurs réglages sont des `local NOM = valeur` déclarés en tête de `Scripts/main.lua`.
Changer un réglage = réécrire la ligne dans le .lua. C'est la seule voie possible.

Contrainte forte : ces fichiers sont écrits à la main par l'utilisateur et contiennent
des commentaires qui documentent le domaine des valeurs (`-- water|waste|fire|glitch`).
La réécriture doit donc être chirurgicale : on ne touche QUE le littéral de valeur,
en préservant l'indentation, l'alignement du `=` et le commentaire de fin de ligne.
Un reformatage du fichier serait une régression, pas un détail cosmétique.

On ne parse pas le Lua : on cible des lignes de la forme
    local NOM<espaces>=<espaces><littéral><reste de ligne>
avec un littéral scalaire (nombre, chaîne, booléen, nil). Les tables sont détectées
mais exposées en lecture seule — les réécrire demanderait un vrai parseur, et aucun
besoin du launcher ne le justifie aujourd'hui.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class LuaType(Enum):
    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"
    NIL = "nil"
    TABLE = "table"       # lecture seule
    UNKNOWN = "unknown"   # expression : lecture seule


@dataclass
class LuaSetting:
    """Une constante `local NOM = valeur` repérée dans un fichier Lua."""

    name: str
    raw_value: str            # littéral tel qu'écrit dans le fichier
    value: object             # valeur Python décodée (None si non décodable)
    type: LuaType
    line_no: int              # 1-indexé
    comment: str              # commentaire de fin de ligne, '' si absent
    editable: bool

    #: Vrai si ce réglage a sa place dans l'interface simple (voir `_mark_user_facing`).
    user_facing: bool = False

    @property
    def choices(self) -> list[str]:
        """Valeurs possibles devinées depuis le commentaire, ex. `-- water|waste|fire`.

        Purement indicatif : sert à proposer une liste déroulante plutôt qu'un champ
        libre dans l'UI. On ne s'en sert jamais pour valider une écriture.
        """
        if not self.comment or self.type is not LuaType.STRING:
            return []
        m = re.search(r"([\w-]+(?:\|[\w-]+)+)", self.comment)
        return m.group(1).split("|") if m else []


# `local NOM = <valeur>` — on capture les 4 morceaux pour pouvoir recomposer à l'identique.
_DECL_RE = re.compile(
    r"^(?P<head>\s*local\s+(?P<name>[A-Za-z_]\w*)\s*=\s*)"
    r"(?P<value>.+?)"
    r"(?P<tail>\s*(?:--.*)?)$"
)
_COMMENT_RE = re.compile(r"--.*$")


def _read(path: Path) -> str:
    """Lit un fichier Lua sans en altérer la forme.

    Deux précautions, chacune tirée d'un vrai dysfonctionnement :

    * **`utf-8-sig`** — le Bloc-notes de Windows enregistre par défaut avec une marque
      d'ordre d'octets. Ce caractère invisible en tête de fichier n'est pas un espace :
      il faisait échouer la reconnaissance de la première constante, et l'interface
      affichait « ce mod n'a aucun réglage modifiable » sur un fichier parfaitement sain.
      La plateforme cible étant Windows, le cas est la règle plutôt que l'exception.

    * **`newline=""`** — sans lui, Python convertit toutes les fins de ligne en `\\n` à
      la lecture puis les retraduit à l'écriture. Un fichier en CRLF était donc
      intégralement réécrit pour un seul réglage modifié, et un fichier en LF pur devenait
      CRLF sous Windows. Chaque ligne apparaissait alors dans un diff.
    """
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return fh.read()


def _decode(raw: str) -> tuple[object, LuaType]:
    raw = raw.strip()
    if raw in ("true", "false"):
        return raw == "true", LuaType.BOOLEAN
    if raw == "nil":
        return None, LuaType.NIL
    if raw.startswith("{"):
        return None, LuaType.TABLE
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        # On DÉCODE les échappements, symétriquement à `_encode`. Sans ça, lire puis
        # réécrire une valeur inchangée doublait les antislashes à chaque passage
        # (`C:\Users` -> `C:\\Users` -> `C:\\\\Users`…) et l'annulation d'un réglage
        # corrompait la chaîne au lieu de la restaurer. La valeur exposée est donc la
        # chaîne RÉELLE, telle que Lua la verrait — c'est elle qui doit apparaître dans
        # l'interface, et elle qui sera ré-échappée à l'écriture.
        return _unescape_lua(raw[1:-1]), LuaType.STRING
    try:
        return (float(raw) if any(c in raw for c in ".eE") else int(raw)), LuaType.NUMBER
    except ValueError:
        return None, LuaType.UNKNOWN


# Échappements Lua. L'ordre compte à l'ENCODAGE : l'antislash d'abord, sinon on
# ré-échapperait ceux qu'on vient d'introduire.
_LUA_ESCAPES = (
    ("\\", "\\\\"),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
)

# `\X` -> caractère réel. Table dérivée de _LUA_ESCAPES pour rester cohérente ; on gère
# aussi `\"` et `\'` (échappement du guillemet), et un `\` suivi de tout autre caractère
# est laissé tel quel — les mods n'utilisent pas d'échappements exotiques.
_LUA_UNESCAPE = {"\\": "\\", "n": "\n", "r": "\r", "t": "\t", '"': '"', "'": "'"}


def _unescape_lua(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append(_LUA_UNESCAPE.get(nxt, "\\" + nxt))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _encode(value: object, previous: LuaType, raw_previous: str) -> str:
    """Réencode une valeur Python en littéral Lua, en respectant le style existant."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    if isinstance(value, str):
        # Toute valeur doit être échappée, PAS seulement entourée de guillemets.
        # Sans ça, trois saisies banales dans un champ texte cassent le mod :
        #   il a dit "non" et c'est fini   -> les deux guillemets, plus aucun ne convient
        #   ligne1\nligne2  (copier-coller) -> le littéral est coupé en deux lignes
        #   C:\Users\test                   -> \U et \t deviennent des échappements Lua
        # Le mod ne se charge alors plus du tout, et l'erreur n'apparaît qu'en jeu.
        text = value
        for char, replacement in _LUA_ESCAPES:
            text = text.replace(char, replacement)

        quote = raw_previous.strip()[0] if previous is LuaType.STRING else '"'
        if quote not in "\"'":
            quote = '"'
        text = text.replace(quote, "\\" + quote)
        return f"{quote}{text}{quote}"
    if isinstance(value, float):
        # Préserve la forme flottante si l'original en était une (700.0 ne doit pas
        # devenir 700 : certains champs Lua sont sensibles au type).
        text = repr(value)
        if text.endswith(".0") and "." not in raw_previous:
            return text[:-2]
        return text
    return str(value)


# Un `local` n'est pas forcément un réglage : les mods déclarent aussi leur état interne
# (`running = false`) et des variables de travail (`jm = "?"` ligne 167). Les exposer dans
# l'interface simple serait pire que du bruit — l'utilisateur pourrait casser un mod en
# modifiant son état interne en croyant régler une option.
_CONST_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Une déclaration de fonction marque la fin de l'en-tête de configuration.
_FUNC_RE = re.compile(r"^\s*(?:local\s+)?function\b")


def _mark_user_facing(settings: list[LuaSetting], header_end: int) -> None:
    """Décide quels réglages méritent d'apparaître dans l'interface simple.

    Trois critères cumulatifs, tirés de l'observation des 17 mods du projet :

    * **Nom en MAJUSCULES** — la convention est constante d'un mod à l'autre pour les
      réglages (`VOID_DELAY_MS`, `RISE_SPEED`), tandis que l'état interne est en
      minuscules (`running`, `jm`).
    * **Déclaré avant la première fonction** — les réglages sont groupés en tête ; un
      `local` apparaissant ligne 167 est une variable de travail, pas une option.
    * **Pas un identifiant technique** — `BASE = "/Game/Game/Placeable/..."`,
      `ENEMY_CLASS = "BP_EnemyBase_C"` ou `MOD = "[FEPerf] "` désignent des objets du
      jeu ou un préfixe de log. Les modifier ne règle rien : ça casse le mod.

    Ce qui est écarté ici reste accessible dans les options avancées : on masque, on
    ne supprime pas. Se tromper coûte donc peu — un réglage manquant reste atteignable,
    et un réglage en trop n'est qu'une ligne inutile.
    """
    for s in settings:
        technical = isinstance(s.value, str) and (
            s.value.startswith(("/", "["))     # chemin d'asset, préfixe de log
            or s.value.endswith("_C")          # nom de classe Blueprint
        )
        s.user_facing = (
            s.editable
            and bool(_CONST_NAME_RE.match(s.name))
            and s.line_no <= header_end
            and not technical
        )


def parse(path: Path | str) -> list[LuaSetting]:
    """Toutes les constantes `local` scalaires d'un fichier Lua, dans l'ordre du fichier.

    Seule la PREMIÈRE déclaration de chaque nom est retenue : les mods redéclarent
    parfois un `local` du même nom dans une fonction, et seule celle de tête est un
    réglage. Retourne une liste vide si le fichier est illisible.
    """
    path = Path(path)
    try:
        lines = _read(path).split("\n")
    except OSError:
        return []

    # Fin de l'en-tête de configuration : la première déclaration de fonction.
    header_end = len(lines)
    for i, line in enumerate(lines, start=1):
        if _FUNC_RE.match(line):
            header_end = i
            break

    out: list[LuaSetting] = []
    seen: set[str] = set()
    for i, line in enumerate(lines, start=1):
        m = _DECL_RE.match(line)
        if not m:
            continue
        name = m.group("name")
        if name in seen:
            continue
        raw = m.group("value").strip()
        # Une valeur qui ouvre une table multi-lignes : on la marque table, sans la lire.
        value, ltype = _decode(raw)
        seen.add(name)
        cm = _COMMENT_RE.search(m.group("tail") or "")
        out.append(LuaSetting(
            name=name,
            raw_value=raw,
            value=value,
            type=ltype,
            line_no=i,
            comment=(cm.group(0) if cm else "").lstrip("- ").strip(),
            editable=ltype in (LuaType.NUMBER, LuaType.STRING, LuaType.BOOLEAN),
        ))
    _mark_user_facing(out, header_end)
    return out


def read(path: Path | str, name: str) -> LuaSetting | None:
    for s in parse(path):
        if s.name == name:
            return s
    return None


class NotEditable(ValueError):
    """La constante existe mais n'est pas réécrivable (table ou expression)."""


def write(path: Path | str, name: str, value: object) -> LuaSetting:
    """Réécrit une constante en place et retourne son nouvel état.

    Ne modifie que le littéral : indentation, alignement et commentaire sont préservés
    à l'octet près. Lève KeyError si la constante n'existe pas, NotEditable si elle
    n'est pas un scalaire.
    """
    path = Path(path)
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    # Le Bloc-notes de Windows enregistre avec une marque d'ordre d'octets. On la
    # RETIRE pour travailler, puis on la REMET à l'écriture : sans ça, le premier
    # réglage modifié retirait 3 octets en tête du fichier — exactement le bruit de
    # diff qu'on cherche à éviter.
    had_bom = raw_text.startswith("﻿")
    text = _read(path)
    lines = text.split("\n")

    current = read(path, name)
    if current is None:
        raise KeyError(f"constante introuvable dans {path.name} : {name}")
    if not current.editable:
        raise NotEditable(
            f"{name} est de type {current.type.value} — réécriture non supportée"
        )

    idx = current.line_no - 1
    m = _DECL_RE.match(lines[idx])
    if m is None:  # pragma: no cover — incohérent avec parse()
        raise KeyError(f"ligne {current.line_no} ne correspond plus à {name}")

    literal = _encode(value, current.type, current.raw_value)
    tail = m.group("tail") or ""
    # Le launcher réécrit ces lignes des dizaines de fois pendant une campagne de
    # mesure. Si on se contente de recoller le tail, chaque changement de longueur de
    # valeur décale le commentaire, et le fichier se désaligne progressivement.
    # On repositionne donc le commentaire sur sa colonne d'origine.
    if tail.lstrip().startswith("--"):
        column = len(m.group("head")) + len(current.raw_value) + (len(tail) - len(tail.lstrip()))
        pad = max(1, column - len(m.group("head")) - len(literal))
        tail = " " * pad + tail.lstrip()
    lines[idx] = f"{m.group('head')}{literal}{tail}"

    # `newline=""` des deux cotes : sans lui, Python retraduit les fins de
    # ligne et un fichier en CRLF (ou en LF sous Windows) est integralement
    # reecrit alors qu'une seule valeur a change.
    with path.open("w", encoding="utf-8-sig" if had_bom else "utf-8",
                   newline="") as fh:
        fh.write("\n".join(lines))

    updated = read(path, name)
    assert updated is not None
    return updated
