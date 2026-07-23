"""Diagnostic d'une installation de Fading Echo, avant de lancer quoi que ce soit.

Pourquoi ce module existe
-------------------------
Les pannes de ce projet ne se manifestent presque jamais par un message d'erreur
lisible. UE4SS meurt dans un log que personne n'ouvre, un mod « désactivé » tourne
quand même, trois mods se partagent F7 et déclenchent leurs trois actions d'un seul
appui. Le symptôme observé est toujours le même — « ça marche pas », ou pire, « ça
marche mais les mesures sont bizarres ». Le Doctor transforme ces silences en
diagnostics nommés, chacun avec sa cause.

Chaque contrôle encodé ici vient d'un fait vérifié sur le PC de jeu (logs UE4SS v3.0.1,
dump PICS Steam), pas d'une supposition. Les commentaires disent lequel. Ne pas durcir
un contrôle qui n'a pas été observé.

Ce que le Doctor ne fait PAS
----------------------------
Il ne répare rien tout seul. Un `Diagnosis` peut porter un correctif, mais c'est
l'appelant qui décide de l'exécuter. Et tout correctif touchant au disque commence par
vérifier que son opération est sûre : quand la vérification est impossible (on n'est
pas sous Windows, `tasklist` ne répond pas), le correctif ÉCHOUE explicitement au lieu
de tenter sa chance. Un renommage de dossier de jeu raté pendant que Steam tourne coûte
une réinstallation complète.

Ne jamais mettre le résultat en cache
-------------------------------------
Une grosse mise à jour Steam peut recréer le dossier d'origine (nom grec compris) et
réécrire `appmanifest_2467880.acf`. Un diagnostic « chemin ASCII, tout va bien » calculé
au démarrage du launcher peut donc être faux dix minutes plus tard. `run()` est conçue
pour être rappelée avant chaque lancement du jeu, pas une fois par session.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # évite un import circulaire à l'exécution
    from .ledger import Ledger
from pathlib import Path

from .procutil import run_hidden
from .mods import Conflict, Mod, ModKind, ModState, conflicts, load, set_enabled
from .paths import APPID, Edition, GameInstall

# Les process qui, s'ils tournent, réécrivent le manifeste Steam en se fermant. C'est
# le piège du renommage : on renomme le dossier, Steam se ferme, remet `installdir` à
# `Project Ygrό`, et au prochain lancement le jeu est « introuvable » — ou pire, Steam
# le retélécharge sous son ancien nom.
STEAM_PROCESSES = ("steam.exe", "steamwebhelper.exe", "steamservice.exe")

# Translittération minimale, limitée à ce dont on a besoin. On ne cherche pas à écrire
# un translittérateur général : le seul cas réel est l'omicron tonos de `Project Ygrό`.
_TRANSLIT = {
    "ό": "o", "ο": "o", "Ό": "O", "Ο": "O",
    "ά": "a", "α": "a", "Ά": "A", "Α": "A",
    "έ": "e", "ε": "e", "ή": "i", "η": "i",
    "ί": "i", "ι": "i", "ύ": "y", "υ": "y",
    "ώ": "o", "ω": "o", "ρ": "r", "Ρ": "R",
    "γ": "g", "Γ": "G", "π": "p", "τ": "t",
    "σ": "s", "ς": "s", "κ": "k", "λ": "l",
    "μ": "m", "ν": "n", "δ": "d", "β": "b",
}


class Level(Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


# Ordre d'affichage : ce qui empêche de jouer d'abord, les confirmations en dernier.
_SEVERITY = {Level.ERROR: 0, Level.WARN: 1, Level.OK: 2}


@dataclass(frozen=True)
class FixResult:
    """Issue d'un correctif. Un correctif ne lève pas : il rend compte."""

    ok: bool
    message: str

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class FixOption:
    """Un correctif parmi plusieurs, quand la bonne action dépend d'un choix humain.

    Cas type : trois mods se disputent F7. Le launcher ne peut pas deviner lequel
    l'utilisateur veut garder — il propose les trois branches et laisse choisir.
    """

    label: str
    run: Callable[[], FixResult]


@dataclass
class Diagnosis:
    """Un constat sur l'install, formulé pour être lu par un humain non technicien."""

    code: str                                  # identifiant stable, pour les tests et l'UI
    level: Level
    title: str                                 # une ligne, ce qu'on a constaté
    detail: str = ""                           # les faits : quels fichiers, quels mods
    why: str = ""                              # POURQUOI ça compte / ce que ça casse
    fix_label: str = ""                        # libellé du bouton, si fix existe
    fix: Callable[[], FixResult] | None = None
    options: list[FixOption] = field(default_factory=list)
    doc: str = ""                              # d'où vient le fait, pour pouvoir recouper

    @property
    def actionable(self) -> bool:
        return self.fix is not None or bool(self.options)


# --- Vérifications d'environnement ----------------------------------------------

def steam_processes_running() -> bool | None:
    """Steam tourne-t-il ? `None` si on ne peut pas savoir.

    Le `None` est la valeur importante : sur le poste de dev (Linux) et si `tasklist`
    échoue, on ne sait PAS. Les correctifs traitent `None` comme un refus, jamais
    comme un « non ».
    """
    if sys.platform != "win32":
        return None
    try:
        out = run_hidden(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    listing = out.stdout.lower()
    return any(name in listing for name in STEAM_PROCESSES)


def ascii_name(name: str) -> str:
    """Version ASCII d'un nom de dossier, ou `''` si on ne sait pas la produire.

    NFKD seul ne suffit pas ici : `ό` (U+03CC) se décompose en omicron grec + accent,
    et l'omicron grec reste non-ASCII. D'où la table de translittération explicite.
    """
    folded = []
    for ch in unicodedata.normalize("NFKD", name):
        if unicodedata.combining(ch):
            continue
        if ord(ch) < 128:
            folded.append(ch)
        elif ch in _TRANSLIT:
            folded.append(_TRANSLIT[ch])
        else:
            return ""  # caractère qu'on ne sait pas rendre : on ne devine pas.
    return "".join(folded).strip()


# --- Correctifs -----------------------------------------------------------------

def manifest_for(install: GameInstall) -> Path | None:
    """`appmanifest_<appid>.acf` correspondant à l'install, s'il est là où on l'attend.

    Une install Steam vit dans `<steamapps>/common/<installdir>`, donc le manifeste est
    deux niveaux au-dessus. Si l'arborescence ne correspond pas (install copiée à la
    main), on retourne None plutôt que de fabriquer un chemin.
    """
    common = install.root.parent
    if common.name.lower() != "common":
        return None
    acf = common.parent / f"appmanifest_{APPID}.acf"
    return acf if acf.is_file() else None


def fix_non_ascii_path(
    install: GameInstall,
    *,
    probe: Callable[[], bool | None] = steam_processes_running,
    ledger: "Ledger | None" = None,
) -> FixResult:
    """Renomme le dossier du jeu en ASCII et met `installdir` à jour dans le manifeste.

    Refuse — sans rien toucher — dans tous les cas où l'opération n'est pas prouvée sûre :
    Steam en cours d'exécution, état de Steam inconnu, manifeste introuvable, nom cible
    déjà pris. `probe` est injectable pour les tests ; en production c'est `tasklist`.

    Si un `ledger` est fourni, les deux mutations (manifeste puis renommage) y sont
    consignées sous un même groupe, ce qui les rend annulables ensemble. C'est ce qui
    permet au launcher de proposer « remettre le nom d'origine » : sans journal, le
    correctif serait à sens unique, et on ne saurait plus si le dossier ASCII vient de
    nous ou de l'utilisateur.
    """
    running = probe()
    if running is None:
        return FixResult(False, "Impossible de vérifier que Steam est fermé — "
                                "renommage refusé. Fermez Steam et renommez à la main.")
    if running:
        return FixResult(False, "Steam est en cours d'exécution. Fermez-le complètement "
                                "(icône de la barre des tâches → Quitter), puis relancez "
                                "le diagnostic.")

    target_name = ascii_name(install.root.name)
    if not target_name:
        return FixResult(False, f"Impossible de proposer un nom ASCII sûr pour "
                                f"« {install.root.name} » — renommez-le vous-même.")

    target = install.root.with_name(target_name)
    if target.exists():
        return FixResult(False, f"« {target_name} » existe déjà à côté — renommage refusé "
                                f"pour ne rien écraser.")

    # On édite le manifeste AVANT de renommer : si l'écriture échoue, le dossier est
    # encore à sa place et Steam reste cohérent. L'inverse laisserait Steam pointer sur
    # un dossier disparu.
    acf = manifest_for(install)
    if acf is None:
        return FixResult(False, "Manifeste appmanifest_%d.acf introuvable : le renommage "
                                "rendrait le jeu invisible pour Steam. Refusé." % APPID)
    group = f"ascii-path-{install.root.name}"
    try:
        # En OCTETS, jamais en texte. Le manifeste était lu avec `errors="replace"` puis
        # réécrit depuis le texte remplacé : tout octet non décodable en UTF-8 — un nom
        # de compte accentué, un champ ajouté par un outil tiers — était définitivement
        # remplacé par U+FFFD. Steam ne reconnaissait alors plus l'installation, avec un
        # retéléchargement complet à la clé. Une substitution littérale n'a aucun besoin
        # de passer par du texte.
        text = acf.read_bytes()
        # Ancrée sur la clé et limitée à une occurrence : le nom du dossier peut
        # apparaître ailleurs dans le fichier, et tout remplacer réécrirait des champs
        # sans rapport.
        patched = re.sub(
            rb'("installdir"\s+")[^"]*(")',
            lambda m: m.group(1) + target_name.encode("utf-8") + m.group(2),
            text, count=1)
        if patched == text:
            return FixResult(False, "`installdir` ne correspond pas au nom du dossier dans "
                                    "le manifeste : situation inattendue, renommage refusé.")
        if ledger is not None:
            ledger.modify_file(acf, patched,
                               label=f"installdir → {target_name}", group=group)
        else:
            acf.write_bytes(patched)
    except OSError as exc:
        return FixResult(False, f"Écriture du manifeste impossible : {exc}")

    try:
        if ledger is not None:
            ledger.rename(install.root, target,
                          label=f"dossier du jeu → {target_name}", group=group)
        else:
            install.root.rename(target)
    except OSError as exc:
        # On remet le manifeste comme on l'a trouvé : mieux vaut le problème d'origine
        # qu'un manifeste qui pointe sur un dossier inexistant.
        if ledger is not None:
            # Passer par le journal plutôt que réécrire à la main : sinon l'entrée
            # resterait « en vigueur » alors que la modification a été défaite, et une
            # annulation ultérieure restaurerait un manifeste déjà correct.
            ledger.undo_group(group)
        else:
            try:
                acf.write_bytes(text)
            except OSError:
                pass
        return FixResult(False, f"Renommage impossible : {exc}")

    return FixResult(True, f"Dossier renommé en « {target_name} » et manifeste mis à jour. "
                           f"Relancez Steam, puis vérifiez le jeu si Steam propose un "
                           f"téléchargement.")


def _disable_all(targets: list[Mod]) -> FixResult:
    """Désactive une liste de mods en retirant leur `enabled.txt` (renommé, réversible)."""
    done, failed = [], []
    for mod in targets:
        try:
            set_enabled(mod, False)
            done.append(mod.name)
        except OSError as exc:
            failed.append(f"{mod.name} ({exc})")
    if failed:
        return FixResult(False, "Échec sur : " + ", ".join(failed)
                         + (" — désactivés : " + ", ".join(done) if done else ""))
    if not done:
        return FixResult(False, "Aucun mod à désactiver.")
    return FixResult(True, "Mods désactivés : " + ", ".join(done))


def _strip_from_mods_txt(path: Path, names: set[str]) -> FixResult:
    """Retire les lignes `Nom : x` trompeuses de `mods.txt`, en préservant le reste."""
    if not path.is_file():
        return FixResult(False, f"{path.name} introuvable.")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        newline = "\r\n" if "\r\n" in text else "\n"
        kept, removed = [], []
        for line in text.splitlines():
            name = line.split(";", 1)[0].partition(":")[0].strip()
            if name in names:
                removed.append(name)
            else:
                kept.append(line)
        if not removed:
            return FixResult(False, "Aucune ligne correspondante dans mods.txt.")
        path.write_text(newline.join(kept) + newline, encoding="utf-8")
    except OSError as exc:
        return FixResult(False, f"Écriture de mods.txt impossible : {exc}")
    return FixResult(True, "Lignes retirées de mods.txt : " + ", ".join(removed))


# --- Contrôles ------------------------------------------------------------------

def _check_path(install: GameInstall) -> Diagnosis:
    if not install.non_ascii_path:
        return Diagnosis(
            code="path.ascii",
            level=Level.OK,
            title="Le chemin d'installation est en ASCII pur",
            detail=str(install.root),
            why="UE4SS peut convertir son chemin en multi-byte sans erreur.",
            doc="Vérifié : la démo, en ASCII, charge la même install d'UE4SS sans planter.",
        )

    chars = ", ".join(f"« {ch} » {code} ({name})" for ch, code, name in install.offending_chars())
    target = ascii_name(install.root.name)
    proposal = f"« {target} »" if target else "un nom sans accent ni caractère grec"
    return Diagnosis(
        code="path.non_ascii",
        level=Level.ERROR,
        title="Le chemin du jeu contient un caractère non-ASCII : UE4SS ne démarrera pas",
        detail=(
            f"Dossier : {install.root}\n"
            f"Caractère(s) en cause : {chars}\n"
            "\n"
            "Procédure manuelle (Steam DOIT être complètement fermé) :\n"
            "  1. Quitter Steam pour de bon (clic droit sur l'icône de la barre des "
            "tâches → Quitter), pas seulement fermer la fenêtre.\n"
            f"  2. Renommer le dossier du jeu en {proposal}.\n"
            f"  3. Ouvrir steamapps\\appmanifest_{APPID}.acf dans un éditeur de texte et "
            "remplacer la valeur de \"installdir\" par le nouveau nom.\n"
            "  4. Relancer Steam et vérifier l'intégrité des fichiers si Steam propose "
            "un téléchargement.\n"
            "\n"
            "Si Steam tourne pendant l'opération, il réécrit le manifeste en se fermant "
            "et le nom d'origine revient."
        ),
        why=(
            "UE4SS convertit le chemin de son propre dossier en chaîne multi-byte pour "
            "initialiser Lua. En page de codes 850 ou 1252, ce caractère n'a aucune "
            "correspondance : UE4SS s'arrête sur « Fatal Error: No mapping for the Unicode "
            "character exists in the target multi-byte code page », juste après « Lua Scan "
            "attempt 1 ». Aucun mod ne se charge. Le jeu, lui, démarre normalement — c'est "
            "ce qui rend la panne difficile à identifier.\n"
            "À refaire après chaque grosse mise à jour Steam : une mise à jour peut "
            "recréer le dossier sous son nom d'origine."
        ),
        fix_label="Renommer le dossier et corriger le manifeste (Steam fermé)",
        fix=lambda: fix_non_ascii_path(install),
        doc="Log UE4SS du PC de jeu ; la même install sous « Fading Echo Demo » fonctionne.",
    )


def _check_ue4ss_present(install: GameInstall) -> Diagnosis:
    if install.has_ue4ss:
        return Diagnosis(
            code="ue4ss.present",
            level=Level.OK,
            title="UE4SS est installé",
            detail=str(install.ue4ss.settings_ini),  # type: ignore[union-attr]
            why="Les mods Lua et C++ peuvent être chargés.",
        )
    return Diagnosis(
        code="ue4ss.absent",
        level=Level.WARN,
        title="UE4SS n'est pas installé",
        detail=f"Aucun UE4SS-settings.ini trouvé dans {install.engine_dir} "
               f"ni dans son sous-dossier ue4ss\\.",
        why=(
            "Ce n'est pas une panne : le jeu se lance et se joue parfaitement sans UE4SS. "
            "Mais aucun mod ne fonctionnera, et les outils de mesure du launcher qui "
            "reposent sur des mods Lua seront inopérants."
        ),
        doc="Deux dispositions possibles : à plat (démo) ou dans ue4ss\\ (jeu complet).",
    )


def _check_layout(install: GameInstall) -> Diagnosis:
    layout = install.ue4ss
    assert layout is not None
    if layout.nested:
        title = "Disposition UE4SS imbriquée (ue4ss\\) — typique du jeu complet"
    else:
        title = "Disposition UE4SS à plat — typique de la démo"
    return Diagnosis(
        code="ue4ss.layout",
        level=Level.OK,
        title=title,
        detail=f"Racine UE4SS : {layout.root}\nMods : {layout.mods_dir}",
        why=(
            "La disposition détermine où vont les mods, mods.txt et UEHelpers. Un mod "
            "copié au mauvais endroit est simplement ignoré, sans message d'erreur."
        ),
        doc="Les deux dispositions ont été observées sur le PC de jeu, démo et jeu complet.",
    )


def _check_proxy_dll(install: GameInstall) -> Diagnosis:
    layout = install.ue4ss
    assert layout is not None
    if layout.proxy_dll.is_file():
        return Diagnosis(
            code="ue4ss.proxy_ok",
            level=Level.OK,
            title="La DLL proxy dwmapi.dll est en place",
            detail=str(layout.proxy_dll),
            why="C'est elle que le jeu charge au démarrage, et qui démarre UE4SS.",
        )
    return Diagnosis(
        code="ue4ss.proxy_missing",
        level=Level.WARN,
        title="dwmapi.dll est absent : UE4SS ne sera jamais chargé",
        detail=f"UE4SS-settings.ini est bien présent ({layout.settings_ini}), "
               f"mais {layout.proxy_dll} manque.",
        why=(
            "UE4SS ne s'injecte pas tout seul : il est chargé par une DLL proxy que le "
            "jeu prend pour une DLL système. Sans dwmapi.dll à côté de l'exe, les "
            "fichiers d'UE4SS sont là mais rien ne les lit — aucun log ne sera même créé, "
            "ce qui fait croire à un problème de mods alors que c'est un problème "
            "d'installation."
        ),
        doc="Réinstaller UE4SS en recopiant l'archive complète dans Binaries\\Win64.",
    )


def _check_uehelpers(install: GameInstall, mods: list[Mod]) -> Diagnosis:
    layout = install.ue4ss
    assert layout is not None
    dependents = [m.name for m in mods if "UEHelpers" in m.requires]

    if layout.uehelpers.is_file():
        return Diagnosis(
            code="ue4ss.uehelpers_ok",
            level=Level.OK,
            title="UEHelpers est présent",
            detail=f"{layout.uehelpers}\n{len(dependents)} mod(s) installé(s) le requièrent.",
            why="Les mods qui font require(\"UEHelpers\") peuvent se charger.",
        )

    if dependents:
        listing = ", ".join(sorted(dependents))
        detail = (f"Attendu : {layout.uehelpers}\n"
                  f"{len(dependents)} mod(s) installé(s) le requièrent : {listing}")
    else:
        detail = (f"Attendu : {layout.uehelpers}\n"
                  "Aucun mod actuellement installé ne le requiert, mais presque tous les "
                  "mods du projet en dépendent : le premier que vous ajouterez échouera.")

    return Diagnosis(
        code="ue4ss.uehelpers_missing",
        level=Level.ERROR,
        title="UEHelpers.lua est absent de Mods/shared",
        detail=detail,
        why=(
            "Tous les mods Lua du projet sauf ue4ss-FEKillAll commencent par "
            "require(\"UEHelpers\"). Ce require échoue si le fichier n'est pas dans "
            "Mods/shared/UEHelpers/ : le mod s'arrête à sa première ligne. Sur les 20 mods "
            "du projet, 19 sont dans ce cas. Le jeu se lance, les mods sont « activés », "
            "et pourtant aucun ne répond."
        ),
        doc="UEHelpers est livré avec UE4SS ; le recopier depuis l'archive UE4SS d'origine.",
    )


def _check_broken_cpp(mods: list[Mod]) -> Diagnosis:
    broken = [m for m in mods if m.state is ModState.BROKEN]
    if not broken:
        return Diagnosis(
            code="mods.cpp_ok",
            level=Level.OK,
            title="Aucun mod activé sans contenu",
            detail=f"{len(mods)} mod(s) détecté(s), tous exécutables.",
            why="Un mod activé dont le script ou la DLL manque échoue au chargement.",
        )

    listing = "\n".join(f"  • {m.name} — {m.path}" for m in broken)
    return Diagnosis(
        code="mods.cpp_not_compiled",
        level=Level.WARN,
        title=f"{len(broken)} mod(s) activé(s) mais sans contenu exécutable",
        detail=listing,
        why=(
            "Ces dossiers ont un enabled.txt, donc UE4SS les considère comme actifs et "
            "tente de les démarrer, mais il n'y a ni Scripts/main.lua ni dlls/main.dll à "
            "exécuter. UE4SS répond « Main script 'main.lua' not found » et passe au "
            "suivant. Ils occupent la liste, ne font rien, et polluent le log. Cela "
            "arrive quand un dossier de mod a été vidé — par une réinstallation d'UE4SS "
            "par-dessus, ou une suppression à la main. Reposer les mods fournis les "
            "réparera ; les désactiver nettoiera le log."
        ),
        fix_label="Désactiver ces mods (réversible)",
        fix=lambda: _disable_all(broken),
        doc="Pour les réparer plutôt que les désactiver : page Mods → « Installer les "
            "mods fournis ».",
    )


def _check_conflicts(mods: list[Mod]) -> list[Diagnosis]:
    found = conflicts(mods)
    if not found:
        return [Diagnosis(
            code="mods.no_conflict",
            level=Level.OK,
            title="Aucun conflit de touche ni de commande entre les mods actifs",
            detail=f"{sum(1 for m in mods if m.state is ModState.ENABLED)} mod(s) actif(s).",
            why="Chaque touche déclenche une seule action.",
        )]

    by_name = {m.name: m for m in mods}
    out = []
    for c in found:
        out.append(_conflict_diagnosis(c, by_name))
    return out


def _conflict_diagnosis(c: Conflict, by_name: dict[str, Mod]) -> Diagnosis:
    involved = [by_name[n] for n in c.mods if n in by_name]
    # Un correctif par « mod à garder » : le launcher ne peut pas choisir à la place de
    # l'utilisateur lequel des trois mods il voulait réellement déclencher.
    options = [
        FixOption(
            label=f"Ne garder que {keep.name} (désactiver les {len(involved) - 1} autres)",
            run=(lambda k=keep: _disable_all([m for m in involved if m.name != k.name])),
        )
        for keep in involved
    ]

    if c.kind == "keybind":
        why = (
            f"Un appui sur {c.resource} n'en déclenche pas un mais {len(c.mods)} : UE4SS "
            "appelle tous les callbacks enregistrés sur cette touche. Rien ne le signale, "
            "ni à l'écran ni dans le log. Pendant une campagne de mesure, c'est le pire "
            "cas possible : chaque essai exécute des actions non voulues, les HIT et les "
            "MISS deviennent ininterprétables, et le tableau de résultats a l'air normal. "
            "Réattribuer la touche ou désactiver les mods en trop avant toute mesure."
        )
        title = f"Touche {c.resource} partagée par {len(c.mods)} mods actifs"
    else:
        why = (
            f"La commande console `{c.resource}` est enregistrée par {len(c.mods)} mods. "
            "UE4SS ne garde qu'un seul gestionnaire par nom de commande ; lequel gagne "
            "dépend de l'ordre de chargement, qui n'est pas garanti d'un lancement à "
            "l'autre. La commande fait donc parfois autre chose que ce qu'on attend."
        )
        title = f"Commande console `{c.resource}` enregistrée par {len(c.mods)} mods actifs"

    return Diagnosis(
        code=f"mods.conflict.{c.kind}.{c.resource}",
        level=Level.WARN,
        title=title,
        detail=c.message,
        why=why,
        options=options,
        doc="Les touches sont déclarées en tête de Scripts/main.lua de chaque mod.",
    )


def _check_mods_txt(install: GameInstall, mods: list[Mod]) -> Diagnosis:
    layout = install.ue4ss
    assert layout is not None
    # Le piège : `Nom : 0` dans mods.txt + enabled.txt présent. La seconde passe de
    # chargement d'UE4SS démarre le mod quand même.
    misleading = [m for m in mods if m.in_mods_txt is False and m.enabled_marker.is_file()]

    if not misleading:
        return Diagnosis(
            code="mods.txt_coherent",
            level=Level.OK,
            title="mods.txt et les enabled.txt sont cohérents",
            detail=f"{layout.mods_txt}",
            why="Aucun mod marqué « 0 » ne tourne en réalité.",
        )

    listing = "\n".join(f"  • {m.name} — « {m.name} : 0 » dans mods.txt, "
                        f"mais {m.enabled_marker.name} est présent" for m in misleading)
    names = {m.name for m in misleading}
    return Diagnosis(
        code="mods.txt_misleading",
        level=Level.WARN,
        title=f"{len(misleading)} mod(s) semblent désactivés dans mods.txt mais tournent",
        detail=listing,
        why=(
            "UE4SS démarre les mods en deux passes. La première lit mods.txt et respecte "
            "les « 0 ». La seconde démarre TOUT dossier de Mods/ contenant un enabled.txt, "
            "sans consulter mods.txt. Un mod avec « Nom : 0 » et un enabled.txt est donc "
            "rattrapé par la seconde passe et tourne malgré tout. C'est le piège classique : "
            "on croit avoir isolé un mod pour un test, et il est toujours actif.\n"
            "La seule désactivation fiable est de retirer enabled.txt."
        ),
        options=[
            FixOption(
                label="Désactiver réellement ces mods (retirer enabled.txt)",
                run=lambda: _disable_all(misleading),
            ),
            FixOption(
                label="Au contraire, les assumer actifs (retirer les lignes de mods.txt)",
                run=lambda: _strip_from_mods_txt(layout.mods_txt, names),
            ),
        ],
        doc="Log UE4SS : « Starting mods (from mods.txt… ) » puis « … (from enabled.txt… ) ».",
    )


def _check_edition(install: GameInstall) -> Diagnosis:
    if install.edition is not Edition.UNKNOWN:
        label = "jeu complet" if install.edition is Edition.FULL else "démo"
        return Diagnosis(
            code="install.edition",
            level=Level.OK,
            title=f"Édition détectée : {label}",
            detail=f"Lanceur : {install.shim_exe.name if install.shim_exe else '—'}",
            why="L'édition détermine la disposition d'UE4SS et le contenu disponible.",
        )
    return Diagnosis(
        code="install.edition_unknown",
        level=Level.WARN,
        title="Édition indéterminée (ni démo ni jeu complet reconnus)",
        detail=f"Ni FadingEcho.exe ni FadingEchoDemo.exe trouvés dans {install.root}.",
        why=(
            "L'édition se déduit du shim lancé par Steam. Sans lui, l'install est soit "
            "incomplète, soit copiée à la main depuis un autre poste. Le launcher "
            "fonctionnera peut-être, mais les hypothèses sur la disposition d'UE4SS et "
            "sur le contenu disponible ne sont plus garanties."
        ),
        doc="Steam lance un shim (~180 Ko) qui démarre l'exe du moteur (~176 Mo).",
    )


# --- Point d'entrée -------------------------------------------------------------

def run(install: GameInstall, mods: list[Mod] | None = None) -> list[Diagnosis]:
    """Passe tous les contrôles sur une install et retourne les constats, pire d'abord.

    `mods` est optionnel : s'il n'est pas fourni et qu'UE4SS est présent, on inventorie
    les mods nous-mêmes. Le passer permet à l'UI de réutiliser un inventaire déjà chargé.

    Résultat à ne pas mettre en cache : une mise à jour Steam peut invalider le contrôle
    de chemin entre deux lancements du jeu (cf. docstring du module).
    """
    out: list[Diagnosis] = [_check_path(install), _check_edition(install)]

    ue4ss = _check_ue4ss_present(install)
    out.append(ue4ss)

    if install.has_ue4ss:
        layout = install.ue4ss
        assert layout is not None
        if mods is None:
            mods = load(layout)
        out.append(_check_layout(install))
        out.append(_check_proxy_dll(install))
        out.append(_check_uehelpers(install, mods))
        out.append(_check_broken_cpp(mods))
        out.extend(_check_conflicts(mods))
        out.append(_check_mods_txt(install, mods))

    # Tri stable : les erreurs remontent, l'ordre des contrôles est conservé à l'intérieur
    # de chaque niveau, ce qui garde un affichage prévisible d'un lancement à l'autre.
    out.sort(key=lambda d: _SEVERITY[d.level])
    return out


def worst(diagnoses: list[Diagnosis]) -> Level:
    """Niveau le plus grave de la liste — pour un voyant global dans l'UI."""
    for level in (Level.ERROR, Level.WARN):
        if any(d.level is level for d in diagnoses):
            return level
    return Level.OK


def summary(diagnoses: list[Diagnosis]) -> str:
    """Une ligne de résumé en français, pour la barre d'état."""
    errors = sum(1 for d in diagnoses if d.level is Level.ERROR)
    warns = sum(1 for d in diagnoses if d.level is Level.WARN)
    if errors:
        return f"{errors} erreur(s) et {warns} avertissement(s) — le jeu ne moddera pas."
    if warns:
        return f"{warns} avertissement(s) — jouable, mais à regarder."
    return "Installation saine : aucun problème détecté."
