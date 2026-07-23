"""Journal des modifications : tout ce que le launcher touche est tracé et réversible.

Pourquoi ce module est le plus important du projet
--------------------------------------------------
Le launcher écrit dans le dossier d'un jeu que l'utilisateur n'a pas fabriqué : il crée
des `enabled.txt`, réécrit des constantes dans des `.lua` écrits à la main, copie des
paks, et peut renommer le dossier d'installation Steam lui-même. Sans trace, deux
promesses seraient du bluff :

  « remettre d'origine »  — on ne peut pas défaire ce qu'on n'a pas noté ;
  « désinstaller proprement » — on ne peut pas distinguer ce que le launcher a créé
                                de ce que l'utilisateur avait déjà.

La seconde est une question de sécurité, pas de confort. Une désinstallation qui
supprimerait un mod installé à la main, ou un pak que l'utilisateur a fabriqué, serait
une perte de données irréversible. Le journal est ce qui permet de n'effacer QUE ce que
le launcher a effectivement créé, et de laisser tout le reste intact.

Principe
--------
Chaque mutation est enregistrée AVANT d'être appliquée, avec de quoi la défaire :
l'ancienne valeur pour une constante, le chemin d'origine pour un renommage, le contenu
d'origine pour un fichier écrasé. Les entrées sont horodatées et rejouées en ordre
inverse pour annuler.

Les fichiers écrasés ou supprimés sont sauvegardés dans un magasin de sauvegardes
(`backups/`) plutôt que gardés en mémoire : une annulation doit survivre à la fermeture
de l'application, à un crash, et à un redémarrage de la machine.

Ce qui n'est délibérément PAS journalisé
-----------------------------------------
Les lectures, et les actions du jeu lui-même. Le journal décrit les effets du launcher
sur le disque, pas l'historique d'utilisation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class Action(Enum):
    """Nature d'une mutation. Chaque valeur a une règle d'annulation propre."""

    CREATE_FILE = "create_file"     # annuler = supprimer (si inchangé depuis)
    DELETE_FILE = "delete_file"     # annuler = restaurer depuis la sauvegarde
    MODIFY_FILE = "modify_file"     # annuler = restaurer depuis la sauvegarde
    RENAME = "rename"               # annuler = renommer en sens inverse
    CREATE_DIR = "create_dir"       # annuler = supprimer si vide
    COPY_TREE = "copy_tree"         # annuler = supprimer l'arbre copié
    LUA_SET = "lua_set"             # annuler = réécrire l'ancienne valeur


@dataclass
class Entry:
    """Une mutation journalisée."""

    id: str
    action: Action
    at: str                                 # ISO 8601 UTC
    target: str                             # chemin principal concerné
    label: str = ""                         # description lisible en français
    origin: str = ""                        # chemin d'origine (RENAME)
    backup: str = ""                        # nom du fichier dans backups/
    payload: dict = field(default_factory=dict)   # ex. {"name": "...", "old": 1200}
    group: str = ""                         # regroupe des mutations liées
    undone: bool = False

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["action"] = self.action.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "Entry":
        d = dict(d)
        d["action"] = Action(d["action"])
        return Entry(**d)


@dataclass
class UndoResult:
    entry: Entry
    ok: bool
    message: str


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class Ledger:
    """Journal persistant des mutations, avec magasin de sauvegardes."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.path = self.root / "ledger.json"
        self.backups = self.root / "backups"
        self.entries: list[Entry] = []
        self._load()

    # --- persistance ---

    def _load(self) -> None:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries = [Entry.from_dict(e) for e in data.get("entries", [])]
            except (OSError, ValueError, TypeError, KeyError):
                # Un journal corrompu ne doit jamais empêcher l'application de démarrer,
                # mais on ne l'écrase pas silencieusement : on le met de côté.
                if self.path.is_file():
                    # `os.replace` et non `rename` : sous Windows, `Path.rename` lève si
                    # la cible existe. Une SECONDE corruption tuait donc le démarrage de
                    # l'application, dans le constructeur, sans rattrapage possible.
                    #
                    # Nom unique par corruption : sans suffixe distinct, chaque nouvelle
                    # corruption écraserait la précédente et on ne conserverait qu'un
                    # seul `.corrupt`. On cherche le premier nom libre plutôt que
                    # d'horodater (Date.now indisponible ici, et il faut rester
                    # déterministe pour les tests).
                    dest = self.path.with_suffix(".json.corrupt")
                    n = 1
                    while dest.exists():
                        dest = self.path.with_suffix(f".json.corrupt.{n}")
                        n += 1
                    try:
                        os.replace(self.path, dest)
                    except OSError:
                        pass
                self.entries = []

    def _flush(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": [e.to_dict() for e in self.entries]}
        # Écriture atomique : une coupure pendant l'écriture du journal ne doit pas
        # laisser un fichier tronqué, sinon on perdrait la capacité d'annuler.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    # --- enregistrement ---

    def _stash(self, path: Path) -> str:
        """Copie un fichier dans le magasin de sauvegardes, retourne son nom de stockage."""
        self.backups.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}-{path.name}"
        shutil.copy2(path, self.backups / name)
        return name

    def _add(self, action: Action, target: Path, **kw) -> Entry:
        entry = Entry(
            id=uuid.uuid4().hex[:12],
            action=action,
            at=datetime.now(timezone.utc).isoformat(),
            target=str(target),
            **kw,
        )
        self.entries.append(entry)
        self._flush()
        return entry

    # --- opérations tracées ---
    # Chacune journalise AVANT d'agir : si l'action échoue, on a une entrée en trop,
    # ce qui est sans danger ; l'inverse ferait perdre la capacité d'annuler.

    def create_file(self, path: Path, content: bytes = b"", *, label: str = "",
                    group: str = "", exclusive: bool = False) -> Entry:
        path = Path(path)
        if exclusive:
            # Création atomique : échoue si le fichier apparaît, au lieu de l'écraser.
            # Indispensable pour le mode « boîtes », qui promet de ne jamais toucher un
            # Engine.ini étranger : sans ça, un fichier écrit par le jeu entre la
            # vérification et l'écriture serait silencieusement remplacé (la délégation
            # à modify_file plus bas l'écraserait). O_EXCL ferme cette fenêtre de course.
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, content)
            finally:
                os.close(fd)
            entry = self._add(Action.CREATE_FILE, path, label=label, group=group)
            entry.payload["sha256"] = _sha256(path)
            self._flush()
            return entry
        existed = path.is_file()
        if existed:
            # Le fichier existait : c'est une modification, pas une création.
            return self.modify_file(path, content, label=label, group=group)
        # Écrire D'ABORD, journaliser APRÈS succès. Si l'écriture échoue (la cible est
        # un dossier, disque plein, dossier non inscriptible), aucune entrée n'est
        # créée. Journaliser avant laisserait une entrée `CREATE_FILE` fantôme dont
        # l'annulation — un `unlink` sur un fichier qui n'existe pas, ou sur un dossier —
        # échouerait à jamais et bloquerait la désinstallation. La règle « journaliser
        # avant » protège les écritures DESTRUCTIVES ; une création ne détruit rien.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entry = self._add(Action.CREATE_FILE, path, label=label, group=group)
        entry.payload["sha256"] = _sha256(path)
        self._flush()
        return entry

    def modify_file(self, path: Path, content: bytes, *, label: str = "",
                    group: str = "") -> Entry:
        path = Path(path)
        if not path.is_file():
            # Sans fichier préexistant il n'y a rien à sauvegarder, et une entrée
            # MODIFY_FILE sans sauvegarde est inannulable pour toujours — le fichier
            # serait créé et ne pourrait plus jamais être retiré, ce qui bloque la
            # désinstallation. C'est une création : on la journalise comme telle.
            return self.create_file(path, content, label=label, group=group)
        backup = self._stash(path)
        entry = self._add(Action.MODIFY_FILE, path, backup=backup,
                          label=label, group=group)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return entry

    def delete_file(self, path: Path, *, label: str = "", group: str = "") -> Entry | None:
        path = Path(path)
        if not path.is_file():
            # Rien à supprimer : ne pas journaliser une entrée `DELETE_FILE` sans
            # sauvegarde, dont l'annulation échouerait pour toujours faute de fichier
            # à restaurer — et bloquerait la désinstallation.
            return None
        backup = self._stash(path)
        entry = self._add(Action.DELETE_FILE, path, backup=backup,
                          label=label, group=group)
        if path.is_file():
            path.unlink()
        return entry

    def rename(self, src: Path, dst: Path, *, label: str = "", group: str = "") -> Entry:
        """Renomme, et journalise SEULEMENT si le renommage a réussi.

        Exception délibérée à la règle « journaliser avant d'agir ». Cette règle protège
        les écritures destructives, où l'ancien contenu disparaît au moment de l'action.
        Un renommage ne détruit rien tant qu'il n'a pas abouti : journaliser d'abord n'y
        apporte aucune sécurité, et coûte cher en cas d'échec.

        Vérifié : quand `rename()` levait (dossier ouvert dans l'Explorateur, antivirus,
        `Directory not empty`), l'entrée restait au journal en décrivant un déplacement
        qui n'avait jamais eu lieu. Son annulation échouait alors pour toujours — et comme
        la désinstallation refuse de purger tant qu'une annulation échoue, l'utilisateur
        se retrouvait dans une impasse : plus aucun moyen de désinstaller proprement.
        """
        src, dst = Path(src), Path(dst)
        src.rename(dst)
        return self._add(Action.RENAME, dst, origin=str(src), label=label, group=group)

    def copy_tree(self, src: Path, dst: Path, *, label: str = "", group: str = "") -> Entry:
        src, dst = Path(src), Path(dst)
        # On refuse d'écraser : l'annulation supprimerait alors du contenu préexistant
        # que le launcher n'a pas créé.
        if dst.exists():
            raise FileExistsError(f"{dst} existe déjà — copie refusée pour rester annulable")
        entry = self._add(Action.COPY_TREE, dst, origin=str(src), label=label, group=group)
        shutil.copytree(src, dst)
        return entry

    def lua_set(self, script: Path, name: str, old: object, new: object, *,
                label: str = "", group: str = "") -> Entry:
        return self._add(Action.LUA_SET, Path(script), label=label, group=group,
                         payload={"name": name, "old": old, "new": new})

    # --- lecture ---

    @property
    def pending(self) -> list[Entry]:
        """Mutations encore en vigueur, de la plus ancienne à la plus récente."""
        return [e for e in self.entries if not e.undone]

    def groups(self) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = {}
        for e in self.pending:
            out.setdefault(e.group or e.id, []).append(e)
        return out

    def touched_paths(self) -> list[Path]:
        return [Path(e.target) for e in self.pending]

    # --- annulation ---

    def _undo_one(self, e: Entry) -> UndoResult:
        target = Path(e.target)
        try:
            if e.action is Action.CREATE_FILE:
                if not target.exists():
                    return UndoResult(e, True, f"déjà absent : {target.name}")
                # On ne supprime QUE si on peut prouver que le fichier est resté le
                # nôtre — c'est-à-dire si son empreinte correspond à celle qu'on a
                # écrite. Deux cas de refus, tous deux traités comme « succès » pour ne
                # pas bloquer la désinstallation sur un fichier qu'on renonce à toucher :
                #   - empreinte différente : l'utilisateur ou le jeu l'a modifié depuis ;
                #   - empreinte absente : entrée héritée d'une version antérieure, ou
                #     cible qui n'est pas un fichier simple. Dans le doute, on ne
                #     supprime pas — perdre le travail de l'utilisateur est pire qu'un
                #     fichier orphelin.
                expected = e.payload.get("sha256")
                if not expected:
                    return UndoResult(e, True,
                                      f"{target.name} : origine non prouvée, laissé en place")
                if not target.is_file() or _sha256(target) != expected:
                    return UndoResult(e, True,
                                      f"{target.name} a changé depuis — laissé en place")
                target.unlink()
                return UndoResult(e, True, f"supprimé : {target.name}")

            if e.action in (Action.MODIFY_FILE, Action.DELETE_FILE):
                if not e.backup:
                    return UndoResult(e, False, f"pas de sauvegarde pour {target.name}")
                src = self.backups / e.backup
                if not src.is_file():
                    return UndoResult(e, False, f"sauvegarde introuvable pour {target.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                return UndoResult(e, True, f"restauré : {target.name}")

            if e.action is Action.RENAME:
                origin = Path(e.origin)
                if origin.exists():
                    return UndoResult(e, False, f"{origin.name} existe déjà")
                if not target.exists():
                    return UndoResult(e, False, f"{target.name} introuvable")
                target.rename(origin)
                return UndoResult(e, True, f"renommé : {target.name} → {origin.name}")

            if e.action is Action.CREATE_DIR:
                if target.is_dir() and not any(target.iterdir()):
                    target.rmdir()
                    return UndoResult(e, True, f"dossier supprimé : {target.name}")
                return UndoResult(e, True, f"dossier non vide, conservé : {target.name}")

            if e.action is Action.COPY_TREE:
                if target.is_dir():
                    shutil.rmtree(target)
                    return UndoResult(e, True, f"arbre supprimé : {target.name}")
                return UndoResult(e, True, f"déjà absent : {target.name}")

            if e.action is Action.LUA_SET:
                from . import luaconf  # import tardif : évite un cycle d'import
                name = e.payload["name"]
                old = e.payload["old"]
                if not target.is_file():
                    return UndoResult(e, False, f"{target.name} introuvable")
                luaconf.write(target, name, old)
                return UndoResult(e, True, f"{name} remis à {old!r}")

        except (OSError, KeyError, ValueError) as exc:
            return UndoResult(e, False, f"échec : {exc}")

        return UndoResult(e, False, f"action inconnue : {e.action}")

    def undo(self, entries: list[Entry] | None = None) -> list[UndoResult]:
        """Annule les mutations données (par défaut : toutes), en ordre inverse.

        L'ordre inverse n'est pas un détail : un renommage de dossier suivi d'écritures
        à l'intérieur ne peut être défait que dans l'autre sens.
        """
        todo = list(entries if entries is not None else self.pending)
        results = []
        for e in reversed(todo):
            if e.undone:
                continue
            r = self._undo_one(e)
            if r.ok:
                e.undone = True
            results.append(r)
        self._flush()
        return results

    def undo_group(self, group: str) -> list[UndoResult]:
        return self.undo([e for e in self.pending if e.group == group])

    # --- désinstallation ---

    def uninstall_plan(self) -> list[tuple[Entry, str]]:
        """Ce que ferait une désinstallation, sans rien exécuter.

        Toujours proposé à l'utilisateur avant l'action : une désinstallation touche
        des fichiers dans son dossier de jeu, il doit pouvoir lire la liste d'abord.
        """
        plan = []
        for e in reversed(self.pending):
            verb = {
                Action.CREATE_FILE: "supprimer",
                Action.MODIFY_FILE: "restaurer la version d'origine de",
                Action.DELETE_FILE: "restaurer",
                Action.RENAME: "renommer à l'identique de départ",
                Action.CREATE_DIR: "supprimer si vide",
                Action.COPY_TREE: "supprimer le dossier copié",
                Action.LUA_SET: "remettre la valeur d'origine dans",
            }[e.action]
            plan.append((e, f"{verb} {Path(e.target).name}"))
        return plan

    def purge_self(self) -> list[str]:
        """Efface les données propres du launcher (journal + sauvegardes).

        À n'appeler QU'APRÈS un undo réussi : une fois les sauvegardes supprimées,
        plus aucune annulation n'est possible.
        """
        removed = []
        if self.backups.is_dir():
            shutil.rmtree(self.backups, ignore_errors=True)
            removed.append(str(self.backups))
        for p in (self.path, self.path.with_suffix(".json.tmp")):
            if p.is_file():
                p.unlink()
                removed.append(str(p))
        self.entries = []
        return removed
