"""Gestion des sauvegardes de Fading Echo : instantanés, restauration, lecture de progression.

Pourquoi ce module existe
-------------------------
Le jeu n'a qu'un seul emplacement de sauvegarde : `LastCheckpoint.sav` est écrasé à
chaque checkpoint. Il n'y a pas de « slot 1 / slot 2 » dans le jeu. Quiconque veut
garder un état (avant un boss, avant un run de speedrun, avant d'essayer un mod)
doit copier les fichiers à la main. Ce module fait ça correctement — c'est-à-dire
sans jamais mettre en danger la partie en cours, et sans se faire écraser par Steam.

Faits sourcés (manifeste Steam PICS de l'appid 2467880, pas des suppositions)
----------------------------------------------------------------------------
Emplacement des saves sous Windows :

    %LOCALAPPDATA%\\UE_YGRO\\Saved\\SaveGames\\<SteamID64>\\

Contenu observé : `LastCheckpoint.sav` (~1,9 Mo), `Achievements.sav` (5428 o),
`OptionsSlot.sav`, plus un `steam_autocloud.vdf` déposé par Steam.

Le manifeste déclare pour ce jeu :

    ufs.maxnumfiles = 3
    savefiles[0] = { path: "UE_YGRO/Saved/SaveGames/{64BitSteamID}",
                     pattern: "*.sav", root: "WinAppDataLocal" }

LE PIÈGE STEAM CLOUD — c'est la contrainte qui dicte toute la conception
-----------------------------------------------------------------------
1. `maxnumfiles = 3`, et il y a EXACTEMENT 3 `.sav`. Le quota est plein. Déposer un
   quatrième `.sav` dans ce dossier — par exemple `LastCheckpoint.avant-boss.sav` —
   met la synchronisation dans un état non spécifié : Steam n'a aucune obligation de
   choisir quel fichier sacrifier. Risque de perte réel, pas théorique.

2. Le pattern `*.sav` n'est PAS récursif. Un SOUS-DOSSIER échappe donc entièrement à
   la synchro. C'est la planque : les instantanés vont dans `FELauncher_Slots/`, et
   ils n'y portent PAS l'extension `.sav` (double ceinture : même si un jour le
   pattern devenait récursif, les fichiers stockés resteraient invisibles pour lui).

3. Steam Cloud écrase le dossier local au démarrage ET à la fermeture du client.
   Permuter une sauvegarde pendant que Steam tourne peut donc être annulé
   silencieusement quelques secondes plus tard, sans message, sans erreur.
   On ne l'interdit pas — l'utilisateur est chez lui — mais on AVERTIT, et on
   réutilise `doctor.steam_processes_running()` pour détecter le cas.

Ce que ce module ne fera JAMAIS : éditer le contenu d'une save
--------------------------------------------------------------
Le parseur `tools/gvas.py` fait un aller-retour octet pour octet sur les 45 fichiers
de test, ce qui le rend fiable en LECTURE. En écriture, les limites vérifiées sont :

    - permuter/copier des fichiers entiers ......... sans risque   (ce que fait ce module)
    - modifier un bool / un entier / un double ..... sûr (largeur fixe)
    - modifier une chaîne, ajouter ou retirer un
      élément de tableau ou de map ................ CASSE SILENCIEUSE

Le cadrage inter-objets entre blocs `SaveTreeEntry` n'est pas rétro-conçu (il est
conservé tel quel comme octets opaques). Toute écriture qui change une longueur
décale ce cadrage sans qu'on sache le recalculer. Ce module n'expose donc AUCUNE
API d'édition, même pour les cas « sûrs » : la seule opération offerte est la copie
de fichiers entiers, et c'est délibéré.

À ne pas confondre : `ConnectedSources`, `UnlockedSources` et `SkillPointBalance`
(les « points Ætherfact ») n'existent PAS dans les sauvegardes — ce sont des
statistiques runtime. La progression réellement stockée tient dans des booléens
agrégés : `bUnlocked`, `bLooted`, `AlreadyDestroyed`, `bCheckpointActivated`,
`bDialPlayed`, `Flying Water Unlocked`, `HasActivatedAtLeastOnce`. C'est ce que
`summarize()` compte, et rien d'autre.

Tout passe par le Ledger
------------------------
Une restauration écrase une partie en cours. Deux garde-fous, non négociables :
elle est journalisée (donc annulable), et elle prend systématiquement un instantané
de l'état courant avant d'écraser. Un utilisateur qui restaure le mauvais slot doit
pouvoir revenir en arrière en un clic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .doctor import steam_processes_running
from .ledger import Ledger

try:  # `tools/` vit à la racine du dépôt, pas dans le paquet.
    from tools import gvas
except ImportError:  # pragma: no cover - dépend de la façon dont on lance le code
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools import gvas


# --- Constantes issues du manifeste ---------------------------------------------

SAVE_SUBPATH = Path("UE_YGRO") / "Saved" / "SaveGames"

#: Les trois fichiers du jeu, dans l'ordre d'importance décroissante.
GAME_SAVE_FILES = ("LastCheckpoint.sav", "Achievements.sav", "OptionsSlot.sav")

#: `ufs.maxnumfiles` déclaré par le manifeste. Il est déjà atteint par les 3 fichiers
#: ci-dessus : il ne reste aucune place pour un `.sav` supplémentaire.
UFS_MAX_NUM_FILES = 3

#: Sous-dossier de rangement. Hors de portée du pattern `*.sav` non récursif.
SLOTS_DIRNAME = "FELauncher_Slots"

#: Extension des fichiers stockés dans un slot. SURTOUT PAS `.sav`.
SLOT_SUFFIX = ".savedata"

#: Métadonnées d'un slot, dans son propre dossier.
SLOT_META = "slot.json"

STEAM_CLOUD_WARNING = (
    "Steam semble en cours d'exécution. Steam Cloud recopie le dossier de "
    "sauvegardes au démarrage ET à la fermeture du client : la sauvegarde que vous "
    "venez de restaurer peut être remplacée par celle du cloud sans aucun message. "
    "Pour être sûr : quittez complètement Steam (icône de la zone de notification → "
    "Quitter), restaurez, puis relancez le jeu."
)

STEAM_CLOUD_UNKNOWN = (
    "Impossible de vérifier si Steam tourne (contrôle disponible sous Windows "
    "uniquement). Si le client Steam est ouvert, Steam Cloud peut écraser la "
    "restauration à la fermeture du client. Dans le doute, quittez Steam avant."
)

# Les porteurs de progression, avec un libellé lisible. L'ordre est celui du résumé.
# Ces noms sont ceux réellement observés dans les 15 sauvegardes de référence ; ce
# sont des booléens agrégés, seuls survivants exploitables de la progression.
PROGRESS_MARKERS: tuple[tuple[str, str], ...] = (
    ("bUnlocked", "déverrouillés"),
    ("bLooted", "coffres"),
    ("AlreadyDestroyed", "destructibles"),
    ("bCheckpointActivated", "checkpoints"),
    ("bDialPlayed", "dialogues"),
    ("Flying Water Unlocked", "eau volante"),
    ("HasActivatedAtLeastOnce", "mécanismes"),
)

# FDateTime UE : nombre de tranches de 100 ns depuis le 01/01/0001.
_TICKS_PER_MICROSECOND = 10
_UE_EPOCH = datetime(1, 1, 1)


# --- Structures -----------------------------------------------------------------

@dataclass
class SaveSummary:
    """Ce qu'on sait lire d'un fichier `.sav`, sans jamais l'écrire.

    En cas d'échec de lecture, l'objet est renvoyé quand même avec `error` rempli :
    une sauvegarde illisible doit s'afficher comme « illisible » dans l'interface,
    pas faire remonter une exception jusqu'à l'utilisateur.
    """

    path: Path
    ok: bool = False
    error: str = ""
    class_name: str = ""
    revision: int | None = None
    saved_at: str = ""                       # ISO 8601, depuis SaveDateTime
    blocks: int = 0
    props: int = 0
    bool_true: int = 0
    bool_total: int = 0
    #: {nom du marqueur: (vrais, total présents dans le fichier)}
    counters: dict[str, tuple[int, int]] = field(default_factory=dict)

    def counter(self, name: str) -> tuple[int, int]:
        return self.counters.get(name, (0, 0))

    @property
    def headline(self) -> str:
        """Résumé d'une ligne, en français, pour l'interface et pour `SaveSlot.progress`."""
        if not self.ok:
            return f"illisible ({self.error})" if self.error else "illisible"
        parts = []
        for name, label in PROGRESS_MARKERS:
            done, total = self.counters.get(name, (0, 0))
            if total:
                parts.append(f"{label} {done}/{total}")
        if not parts:
            # Cas réel : Achievements.sav range tout dans un tableau opaque, aucun
            # booléen n'y est exposé. On ne fabrique pas un faux résumé.
            return f"{self.props} propriétés, aucun marqueur de progression"
        return " · ".join(parts)


@dataclass
class SaveSlot:
    """Un instantané rangé par le launcher, hors de portée de Steam Cloud."""

    name: str                                # nom lisible choisi par l'utilisateur
    path: Path                               # dossier du slot
    created: str = ""                        # ISO 8601 UTC
    size: int = 0                            # octets, tous fichiers confondus
    note: str = ""
    progress: str = ""                       # `SaveSummary.headline` au moment de la copie
    source: str = "manuel"                   # 'manuel' | 'auto-restauration' | 'import'

    @property
    def files(self) -> list[Path]:
        if not self.path.is_dir():
            return []
        return sorted(p for p in self.path.iterdir() if p.suffix == SLOT_SUFFIX)

    @property
    def complete(self) -> bool:
        """Le slot contient-il les trois fichiers du jeu ?

        Un slot incomplet reste restaurable — on ne remet que ce qu'il contient — mais
        l'interface doit pouvoir le signaler.
        """
        have = {p.name for p in self.files}
        return all(_stored_name(n) in have for n in GAME_SAVE_FILES)

    @property
    def created_local(self) -> str:
        """Horodatage lisible, en heure locale."""
        try:
            dt = datetime.fromisoformat(self.created)
        except ValueError:
            return self.created
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")


@dataclass
class RestoreReport:
    """Compte rendu d'une restauration : ce qui a été fait, et ce dont il faut se méfier."""

    ok: bool
    slot: SaveSlot
    group: str = ""                          # groupe Ledger — passer à `undo_group()`
    backup: SaveSlot | None = None           # instantané automatique de l'état écrasé
    restored: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""


# --- Emplacements ---------------------------------------------------------------

def _stored_name(sav_name: str) -> str:
    """`LastCheckpoint.sav` → `LastCheckpoint.savedata`.

    Le renommage n'est pas cosmétique : c'est ce qui garantit qu'aucun fichier de slot
    ne peut être ramassé par le pattern `*.sav` de Steam Cloud, quoi qu'il arrive.
    """
    return Path(sav_name).stem + SLOT_SUFFIX


def _sav_name(stored_name: str) -> str:
    """Inverse de `_stored_name`."""
    return Path(stored_name).stem + ".sav"


def _steam_id_dirs(base: Path) -> list[Path]:
    """Sous-dossiers de `SaveGames/` qui ressemblent à un SteamID64 (17 chiffres)."""
    if not base.is_dir():
        return []
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    return [p for p in entries if p.is_dir() and p.name.isdigit() and len(p.name) >= 15]


def save_dir(steam_id: str | None = None) -> Path | None:
    """Dossier de sauvegardes du jeu, ou `None` hors Windows.

    Le `None` est volontaire et significatif : sur le poste de dev (Linux) le jeu
    n'existe pas, et inventer un chemin plausible ferait échouer les appelants plus
    loin, avec un message moins clair. Tout le reste du module accepte une racine
    explicite pour rester utilisable et testable là où `save_dir()` vaut `None`.

    Hypothèse assumée : quand `steam_id` n'est pas fourni et qu'un seul sous-dossier
    de compte existe, on le prend. S'il y en a plusieurs, on ne devine pas — on
    renvoie `None`, car restaurer dans le mauvais compte serait une perte de données.
    """
    if sys.platform != "win32":
        return None
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    base = Path(local) / SAVE_SUBPATH
    if steam_id:
        return base / steam_id
    candidates = _steam_id_dirs(base)
    if len(candidates) == 1:
        return candidates[0]
    return None


def slots_dir(save_root: Path | None = None, steam_id: str | None = None) -> Path | None:
    """Dossier de rangement des instantanés — le seul endroit où le launcher écrit.

    Il est DANS le dossier de saves mais en sous-dossier, donc invisible pour le
    pattern `*.sav` non récursif de Steam Cloud : les instantanés ne comptent pas
    dans le quota de 3 fichiers et ne peuvent pas être écrasés par le cloud.
    """
    root = Path(save_root) if save_root is not None else save_dir(steam_id)
    return None if root is None else root / SLOTS_DIRNAME


def steam_cloud_notice(save_root: Path) -> list[str]:
    """Avertissements sur l'état du dossier de saves vis-à-vis du quota Steam Cloud.

    Le cas dangereux qu'on cherche : un `.sav` de plus que les trois attendus, posé à
    la main par l'utilisateur (« je fais une copie avant le boss »). C'est exactement
    ce qui met la synchro dans un état non spécifié.
    """
    notices: list[str] = []
    root = Path(save_root)
    if not root.is_dir():
        return notices
    try:
        savs = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix == ".sav")
    except OSError:
        return notices
    if len(savs) > UFS_MAX_NUM_FILES:
        extra = [n for n in savs if n not in GAME_SAVE_FILES]
        notices.append(
            f"{len(savs)} fichiers .sav dans le dossier de sauvegardes alors que Steam "
            f"Cloud n'en synchronise que {UFS_MAX_NUM_FILES}. Fichiers en trop : "
            f"{', '.join(extra) or '—'}. Steam ne garantit pas lequel sera conservé : "
            "déplacez-les hors de ce dossier (le launcher les range dans "
            f"« {SLOTS_DIRNAME} », qui échappe à la synchro)."
        )
    return notices


# --- Lecture de progression -----------------------------------------------------

def _decode_save_datetime(data: bytes) -> str:
    """`SaveDateTime` (FDateTime, 8 octets de ticks) → ISO 8601, `''` si illisible."""
    if len(data) != 8:
        return ""
    try:
        ticks = struct.unpack("<q", data)[0]
        dt = _UE_EPOCH + timedelta(microseconds=ticks // _TICKS_PER_MICROSECOND)
    except (struct.error, OverflowError, ValueError):
        return ""
    return dt.isoformat(timespec="seconds")


def summarize(sav_path: Path) -> SaveSummary:
    """Lit la progression d'un `.sav` via `tools/gvas.py`. Ne lève jamais.

    Le fichier n'est ouvert qu'en lecture, et rien n'est réécrit : c'est la seule
    interaction avec le contenu d'une sauvegarde que ce module s'autorise.

    Dégradation propre : un fichier tronqué, un fichier qui n'est pas du GVAS, un
    fichier absent → `SaveSummary(ok=False, error=...)`. Une sauvegarde corrompue est
    un cas normal dans la vie d'un joueur (coupure de courant pendant l'écriture) ;
    faire planter le launcher dessus le rendrait inutilisable au pire moment.
    """
    path = Path(sav_path)
    summary = SaveSummary(path=path)
    try:
        save = gvas.load(path)
    except FileNotFoundError:
        summary.error = "fichier introuvable"
        return summary
    except OSError as exc:
        summary.error = f"lecture impossible : {exc.strerror or exc}"
        return summary
    except Exception as exc:  # noqa: BLE001 - gvas lève ValueError, struct.error, IndexError…
        # On ne filtre pas par type : un parseur binaire face à des octets arbitraires
        # peut lever à peu près n'importe quoi, et aucune de ces exceptions ne doit
        # traverser la couche interface.
        summary.error = f"format illisible : {type(exc).__name__}: {exc}"
        return summary

    summary.ok = True
    summary.class_name = save.header.class_name
    summary.blocks = len(save.blocks)

    wanted = {name for name, _ in PROGRESS_MARKERS}
    tally: dict[str, list[int]] = {name: [0, 0] for name in wanted}

    for prop in save.all_props():
        summary.props += 1
        try:
            if prop.type.name == "BoolProperty":
                value = bool(prop.value())
                summary.bool_total += 1
                summary.bool_true += value
                if prop.name in wanted:
                    tally[prop.name][0] += value
                    tally[prop.name][1] += 1
            elif prop.name == "Revision" and summary.revision is None:
                summary.revision = int(prop.value())
            elif prop.name == "SaveDateTime" and not summary.saved_at:
                summary.saved_at = _decode_save_datetime(prop.data)
        except Exception:  # noqa: BLE001, S112 - une propriété illisible n'invalide pas le reste
            # Le résumé est indicatif : mieux vaut un compteur légèrement incomplet
            # qu'un fichier déclaré illisible parce qu'une propriété sur 7000 a surpris.
            continue

    summary.counters = {name: (done, total) for name, (done, total) in tally.items() if total}
    return summary


# --- Slots ----------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^\w.-]+", re.UNICODE)


def _slugify(name: str) -> str:
    """Nom de dossier sûr dérivé du nom lisible.

    On translittère en ASCII : le dossier de saves peut vivre sous un chemin déjà
    problématique (`Project Ygrό`), inutile d'y ajouter des noms non-ASCII. On refuse
    aussi tout ce qui pourrait sortir du dossier de slots (`..`, séparateurs).
    """
    folded = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    slug = _SLUG_STRIP.sub("-", ascii_only.encode("ascii", "ignore").decode()).strip("-. ")
    slug = slug[:60]
    return slug or "slot"


def _read_meta(slot_path: Path) -> SaveSlot:
    """Reconstruit un `SaveSlot` depuis son dossier ; tolère des métadonnées absentes."""
    meta: dict = {}
    meta_file = slot_path / SLOT_META
    if meta_file.is_file():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    files = [p for p in slot_path.iterdir() if p.suffix == SLOT_SUFFIX] if slot_path.is_dir() else []
    size = sum(p.stat().st_size for p in files if p.is_file())
    created = meta.get("created", "")
    if not created:
        # Repli sur la date du dossier : un slot copié à la main reste listable.
        try:
            created = datetime.fromtimestamp(
                slot_path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            created = ""
    return SaveSlot(
        name=meta.get("name") or slot_path.name,
        path=slot_path,
        created=created,
        size=size,
        note=meta.get("note", ""),
        progress=meta.get("progress", ""),
        source=meta.get("source", "inconnu"),
    )


def _write_meta(slot: SaveSlot) -> None:
    payload = {
        "version": 1,
        "name": slot.name,
        "created": slot.created,
        "note": slot.note,
        "progress": slot.progress,
        "source": slot.source,
    }
    (slot.path / SLOT_META).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def list_slots(save_root: Path | None = None, *, steam_id: str | None = None) -> list[SaveSlot]:
    """Instantanés existants, du plus récent au plus ancien.

    On ne parse aucun `.sav` ici : le résumé de progression a été calculé une fois à
    la copie et stocké dans `slot.json`. Relire 1,9 Mo de GVAS par slot à chaque
    affichage de liste rendrait l'interface poussive pour rien.
    """
    directory = slots_dir(save_root, steam_id)
    if directory is None or not directory.is_dir():
        return []
    slots = [_read_meta(p) for p in directory.iterdir() if p.is_dir()]
    return sorted(slots, key=lambda s: s.created, reverse=True)


def find_slot(name: str, save_root: Path | None = None, *,
              steam_id: str | None = None) -> SaveSlot | None:
    """Retrouve un slot par son nom lisible ou par son nom de dossier."""
    slug = _slugify(name)
    for slot in list_slots(save_root, steam_id=steam_id):
        if slot.name == name or slot.path.name == slug:
            return slot
    return None


def snapshot(name: str, save_root: Path | None = None, *, steam_id: str | None = None,
             note: str = "", source: str = "manuel",
             ledger: Ledger | None = None) -> SaveSlot:
    """Copie l'état courant des sauvegardes dans un nouveau slot.

    L'opération est en lecture seule du côté du jeu : on ne fait que LIRE les trois
    `.sav` et écrire des copies dans le sous-dossier de slots. C'est pour ça qu'un
    instantané est sans risque, et que le `ledger` est optionnel ici — il n'y a rien
    à annuler dans le dossier du jeu. Quand il est fourni, les copies y sont tout de
    même consignées, pour qu'une désinstallation sache quoi nettoyer.

    Lève `FileNotFoundError` si le dossier de saves n'existe pas, et `FileExistsError`
    si un slot du même nom existe déjà : écraser silencieusement un instantané
    reviendrait à perdre exactement ce que l'utilisateur cherchait à protéger.
    """
    root = Path(save_root) if save_root is not None else save_dir(steam_id)
    if root is None:
        raise FileNotFoundError(
            "Dossier de sauvegardes introuvable (hors Windows, ou compte Steam ambigu) — "
            "indiquez-le explicitement via `save_root`."
        )
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"Dossier de sauvegardes introuvable : {root}")

    present = [n for n in GAME_SAVE_FILES if (root / n).is_file()]
    if not present:
        raise FileNotFoundError(f"Aucune sauvegarde à copier dans {root}")

    target = slots_dir(root) / _slugify(name)
    if target.exists():
        raise FileExistsError(f"Un instantané nommé « {name} » existe déjà")
    target.mkdir(parents=True)

    total = 0
    for sav_name in present:
        src = root / sav_name
        dst = target / _stored_name(sav_name)
        # Un instantané n'est JAMAIS journalisé, même si un journal est fourni.
        #
        # Le journal décrit ce que le launcher a fait AU JEU, pour pouvoir le défaire.
        # Un instantané est l'inverse : une donnée que l'utilisateur a délibérément
        # créée, rangée hors du dossier du jeu. Le journaliser en ferait une entrée
        # `CREATE_FILE`, dont l'annulation est une SUPPRESSION — et la désinstallation
        # effacerait donc les points de restauration du joueur, alors que son écran de
        # confirmation promet explicitement de ne pas toucher aux sauvegardes.
        # Vérifié : les trois `.savedata` d'un instantané disparaissaient à la
        # désinstallation. C'est le même raisonnement que `delete_slot()`.
        shutil.copy2(src, dst)
        total += len(data := src.read_bytes())

    # Le résumé est calculé une seule fois, ici, sur la copie : la liste des slots
    # devient une simple lecture de JSON.
    checkpoint = target / _stored_name(GAME_SAVE_FILES[0])
    progress = summarize(checkpoint).headline if checkpoint.is_file() else ""

    slot = SaveSlot(
        name=name,
        path=target,
        created=datetime.now(timezone.utc).isoformat(),
        size=total,
        note=note,
        progress=progress,
        source=source,
    )
    _write_meta(slot)
    return slot


def _free_backup_name(save_root: Path) -> str:
    """Nom d'instantané automatique libre, horodaté à la seconde.

    L'horodatage à la seconde ne suffit PAS : deux restaurations enchaînées (cas
    normal — « je me suis trompé de slot, je remets celui d'avant ») tombent dans la
    même seconde, et `snapshot()` refuse à juste titre d'écraser. Sans ce suffixe, la
    deuxième restauration échouerait, précisément au moment où l'utilisateur en a le
    plus besoin. On numérote plutôt que d'ajouter des millisecondes : le nom reste
    lisible dans la liste des instantanés.
    """
    base = f"avant-restauration-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    directory = slots_dir(save_root)
    if directory is None or not (directory / _slugify(base)).exists():
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if not (directory / _slugify(candidate)).exists():
            return candidate
    return f"{base}-{datetime.now().microsecond}"


def restore(slot: SaveSlot, save_root: Path | None = None, *, steam_id: str | None = None,
            ledger: Ledger, probe=steam_processes_running,
            auto_backup: bool = True) -> RestoreReport:
    """Remet un instantané en place, de façon annulable et avec filet de sécurité.

    Trois garanties, dans cet ordre :

    1. **Filet** — un instantané automatique de l'état courant est pris AVANT toute
       écriture, sous le nom `avant-restauration-<horodatage>`. Écraser une partie en
       cours sans copie de secours est inacceptable : le joueur peut avoir progressé
       depuis son dernier instantané manuel sans y penser.
    2. **Annulable** — chaque fichier est écrit via le Ledger, sous un même groupe.
       `ledger.undo_group(report.group)` rend l'état exact d'avant la restauration.
    3. **Averti** — si Steam tourne (ou si on ne peut pas le savoir), le rapport porte
       un avertissement explicite sur l'écrasement possible par Steam Cloud. On
       n'interdit rien : c'est la machine de l'utilisateur, et le cas « Steam ouvert
       mais jeu jamais lancé » est parfaitement sûr en pratique. Mais il doit lire.

    Les fichiers présents dans le dossier du jeu mais absents du slot ne sont PAS
    supprimés : un slot partiel doit remettre ce qu'il contient, pas amputer le reste.
    """
    root = Path(save_root) if save_root is not None else save_dir(steam_id)
    if root is None:
        return RestoreReport(False, slot,
                             message="Dossier de sauvegardes introuvable — restauration annulée.")
    root = Path(root)

    stored = slot.files
    if not stored:
        return RestoreReport(False, slot,
                             message=f"L'instantané « {slot.name} » ne contient aucun fichier.")

    warnings: list[str] = []
    running = probe()
    if running is True:
        warnings.append(STEAM_CLOUD_WARNING)
    elif running is None:
        warnings.append(STEAM_CLOUD_UNKNOWN)
    warnings.extend(steam_cloud_notice(root))
    if not slot.complete:
        have = ", ".join(_sav_name(p.name) for p in stored)
        warnings.append(
            f"Instantané partiel : il ne contient que {have}. Les autres fichiers de "
            "sauvegarde resteront tels qu'ils sont actuellement."
        )

    # 1. Le filet, avant tout le reste. S'il échoue, on ne restaure pas : mieux vaut
    #    ne rien faire que d'écraser une partie sans pouvoir la rendre.
    backup: SaveSlot | None = None
    if auto_backup and any((root / n).is_file() for n in GAME_SAVE_FILES):
        try:
            backup = snapshot(
                _free_backup_name(root),
                root,
                note=f"État automatique sauvegardé avant restauration de « {slot.name} »",
                source="auto-restauration",
            )
        except OSError as exc:
            return RestoreReport(
                False, slot, warnings=warnings,
                message=f"Impossible de sauvegarder l'état courant ({exc}) — "
                        "restauration annulée pour ne rien écraser sans filet.",
            )

    # 2. L'écriture, groupée pour être annulable d'un bloc.
    group = f"restore:{slot.path.name}:{datetime.now(timezone.utc).timestamp():.0f}"
    restored: list[str] = []
    for src in stored:
        sav_name = _sav_name(src.name)
        # create_file délègue à modify_file si la cible existe déjà : dans les deux
        # cas l'annulation sait quoi faire (supprimer, ou remettre l'ancien contenu).
        ledger.create_file(root / sav_name, src.read_bytes(),
                           label=f"restauration de « {slot.name} » : {sav_name}",
                           group=group)
        restored.append(sav_name)

    message = (f"{len(restored)} fichier(s) restauré(s) depuis « {slot.name} ».")
    if backup is not None:
        message += f" État précédent conservé dans « {backup.name} »."
    return RestoreReport(True, slot, group=group, backup=backup,
                         restored=restored, warnings=warnings, message=message)


def delete_slot(slot: SaveSlot, *, ledger: Ledger | None = None) -> bool:
    """Supprime un instantané. Retourne False s'il n'existait déjà plus.

    On ne passe pas par le Ledger pour le contenu : un slot est une donnée du
    launcher, dans son propre sous-dossier, jamais un fichier du jeu — le journal
    sert à protéger ce qui appartient à l'utilisateur, pas à archiver indéfiniment
    des copies de 1,9 Mo qu'il a explicitement demandé à supprimer. Le `ledger` est
    accepté pour marquer les entrées de création comme annulées, afin qu'une
    désinstallation ultérieure ne cherche pas à nettoyer un dossier disparu.
    """
    path = Path(slot.path)
    if not path.is_dir():
        return False
    shutil.rmtree(path)
    if ledger is not None:
        group = f"snapshot:{path.name}"
        for entry in ledger.pending:
            if entry.group == group:
                entry.undone = True
        ledger._flush()  # noqa: SLF001 - même paquet, marquage sans rejouer l'annulation
    return True
