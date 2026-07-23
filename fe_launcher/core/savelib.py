"""Bibliothèque de sauvegardes prêtes à l'emploi, et édition sûre d'une sauvegarde.

Deux fonctions, toutes deux réversibles.

1. Bibliothèque (`bundled_saves`, `apply_bundled`)
   Le launcher embarque une collection de sauvegardes à différents points de
   progression. L'utilisateur en choisit une, elle remplace la sauvegarde courante.

   Le filet de sécurité, tel que demandé : au moment de charger une sauvegarde de la
   bibliothèque, la sauvegarde ACTUELLE est mise de côté dans UN emplacement unique.
   Si on charge une autre sauvegarde ensuite, cette mise de côté est ÉCRASÉE — on ne
   garde donc qu'un seul retour en arrière, le plus récent, pas un historique. C'est un
   « annuler la dernière fois que j'ai chargé », rien de plus.

2. Édition (`editable_fields`, `write_fields`)
   On n'expose QUE ce que le format GVAS permet de modifier sans se casser : les
   booléens et les nombres à largeur fixe (cf. `tools/gvas.py`). Modifier une chaîne ou
   un tableau décalerait le cadrage interne et corromprait le fichier silencieusement —
   ces champs sont donc lus mais jamais proposés à l'écriture. L'aller-retour d'une
   édition sûre est exact à l'octet près, vérifié sur les sauvegardes réelles.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import saves
from .ledger import Ledger
from .saves import GAME_SAVE_FILES

# Emplacement UNIQUE du filet « annuler le dernier chargement ». Un seul, écrasé à
# chaque chargement — c'est le comportement demandé.
ROLLBACK_DIRNAME = "FELauncher_LastState"
LEDGER_GROUP = "savelib"


def _gvas():
    """Import tardif de tools/gvas.py (hors paquet, comme dans saves.py)."""
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tools import gvas  # noqa: PLC0415
    return gvas


def _bundled_dir() -> Path:
    """Dossier des sauvegardes embarquées, compatible mode compilé (.exe)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "fe_launcher" / "resources" / "saves"
    return Path(__file__).resolve().parent.parent / "resources" / "saves"


@dataclass
class BundledSave:
    """Une sauvegarde livrée avec le launcher."""

    name: str
    path: Path
    files: list[str] = field(default_factory=list)
    progress: str = ""

    @property
    def complete(self) -> bool:
        have = {p.name for p in self.path.glob("*.sav")}
        return "LastCheckpoint.sav" in have


def bundled_saves() -> list[BundledSave]:
    """Toutes les sauvegardes embarquées, triées par nom."""
    base = _bundled_dir()
    if not base.is_dir():
        return []
    out: list[BundledSave] = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        files = sorted(p.name for p in d.glob("*.sav"))
        if not files:
            continue
        out.append(BundledSave(name=d.name, path=d, files=files,
                               progress=_progress_of(d)))
    return out


def _progress_of(save_dir: Path) -> str:
    """Résumé court de progression, lu via gvas. Vide si illisible."""
    last = save_dir / "LastCheckpoint.sav"
    if not last.is_file():
        return ""
    summary = saves.summarize(last)
    return summary.headline if summary.ok else ""


@dataclass
class ApplyReport:
    ok: bool
    message: str
    group: str = LEDGER_GROUP
    warnings: list[str] = field(default_factory=list)


def _rollback_dir(save_root: Path | None, steam_id: str | None) -> Path | None:
    root = save_root or saves.save_dir(steam_id)
    return None if root is None else root / ROLLBACK_DIRNAME


def apply_bundled(save: BundledSave, *, save_root: Path | None = None,
                  steam_id: str | None = None, ledger: Ledger,
                  probe=None) -> ApplyReport:
    """Remplace la sauvegarde courante par une sauvegarde de la bibliothèque.

    Filet unique : l'état courant est copié dans le dossier de rollback (ÉCRASÉ s'il en
    existait déjà un — un seul retour arrière conservé). Puis les fichiers de la
    sauvegarde choisie sont écrits, via le journal (donc annulables à la désinstallation).
    """
    root = save_root or saves.save_dir(steam_id)
    if root is None:
        return ApplyReport(False,
                           "Dossier de sauvegardes introuvable. Indiquez-le à la main "
                           "dans la page Sauvegardes.")
    if not save.complete:
        return ApplyReport(False, f"La sauvegarde « {save.name} » est incomplète.")

    warnings = list(saves.steam_cloud_notice(root))
    if probe is None:
        from .doctor import steam_processes_running
        probe = steam_processes_running
    running = probe()
    if running or running is None:
        warnings.append(saves.STEAM_CLOUD_WARNING if running else saves.STEAM_CLOUD_UNKNOWN)

    # 1. Filet unique : on écrase le rollback précédent (comportement voulu).
    rb = _rollback_dir(root, steam_id)
    if rb is not None:
        if rb.exists():
            import shutil
            shutil.rmtree(rb, ignore_errors=True)   # détruit le filet précédent
        rb.mkdir(parents=True, exist_ok=True)
        for name in GAME_SAVE_FILES:
            cur = root / name
            if cur.is_file():
                import shutil
                shutil.copy2(cur, rb / name)

    # 2. Écrit les fichiers de la sauvegarde choisie, via le journal.
    for name in save.files:
        src = save.path / name
        if src.is_file():
            ledger.create_file(root / name, src.read_bytes(),
                               label=f"charger la sauvegarde « {save.name} » : {name}",
                               group=LEDGER_GROUP)

    return ApplyReport(True,
                       f"Sauvegarde « {save.name} » chargée. L'état précédent a été mis "
                       f"de côté (récupérable une seule fois, jusqu'au prochain "
                       f"chargement).",
                       warnings=warnings)


def has_rollback(save_root: Path | None = None, steam_id: str | None = None) -> bool:
    rb = _rollback_dir(save_root, steam_id)
    return rb is not None and rb.is_dir() and any(rb.glob("*.sav"))


def restore_rollback(*, save_root: Path | None = None, steam_id: str | None = None,
                     ledger: Ledger) -> ApplyReport:
    """Restaure l'état mis de côté lors du dernier chargement."""
    root = save_root or saves.save_dir(steam_id)
    rb = _rollback_dir(root, steam_id)
    if root is None or rb is None or not rb.is_dir():
        return ApplyReport(False, "Aucun état précédent à restaurer.")
    files = list(rb.glob("*.sav"))
    if not files:
        return ApplyReport(False, "Aucun état précédent à restaurer.")
    for src in files:
        ledger.create_file(root / src.name, src.read_bytes(),
                           label=f"restaurer l'état précédent : {src.name}",
                           group=LEDGER_GROUP)
    return ApplyReport(True, "État précédent restauré.")


# --- Édition sûre d'une sauvegarde ----------------------------------------------

@dataclass
class SaveField:
    """Une propriété modifiable d'une sauvegarde."""

    name: str
    type: str                 # BoolProperty, IntProperty, ...
    value: object
    index: int                # position dans la liste à plat, pour cibler l'écriture

    @property
    def is_bool(self) -> bool:
        return self.type == "BoolProperty"


def editable_fields(sav_path: Path) -> list[SaveField]:
    """Toutes les propriétés modifiables SANS RISQUE d'un fichier .sav.

    Ne renvoie que des booléens et des nombres à largeur fixe — jamais de chaîne ni de
    tableau, dont l'édition casserait le fichier. Liste vide si illisible.
    """
    gvas = _gvas()
    try:
        sv = gvas.load(sav_path)
    except (OSError, ValueError, Exception):  # noqa: BLE001 — un save corrompu ne doit pas planter
        return []
    out: list[SaveField] = []
    idx = 0
    for block in sv.blocks:
        for p in block.props:
            if p.editable():
                out.append(SaveField(name=p.name, type=p.type.name,
                                     value=p.value(), index=idx))
            idx += 1
    return out


def write_fields(sav_path: Path, changes: dict[int, object], *,
                 ledger: Ledger | None = None) -> bool:
    """Applique des modifications (index → nouvelle valeur) à un .sav, en sécurité.

    Round-trip exact garanti pour les types autorisés. Si un `ledger` est fourni,
    l'ancien contenu du fichier est sauvegardé avant écriture (donc annulable).
    Retourne False si le fichier est illisible ou une modification refusée.
    """
    gvas = _gvas()
    try:
        sv = gvas.load(sav_path)
    except (OSError, ValueError):
        return False

    flat = [p for block in sv.blocks for p in block.props]
    for idx, value in changes.items():
        if not (0 <= idx < len(flat)):
            return False
        prop = flat[idx]
        if not prop.editable():
            return False
        prop.set_value(value)

    data = sv.pack()
    if ledger is not None:
        ledger.modify_file(Path(sav_path), data,
                           label=f"édition de {Path(sav_path).name}", group=LEDGER_GROUP)
    else:
        Path(sav_path).write_bytes(data)
    return True
