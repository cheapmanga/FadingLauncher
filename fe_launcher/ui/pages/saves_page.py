"""Sauvegardes : instantanés et restauration de fichiers entiers, rien d'autre.

Pourquoi cette page existe
--------------------------
Fading Echo n'a qu'un seul emplacement de sauvegarde : `LastCheckpoint.sav` est écrasé
à chaque checkpoint, et le jeu n'offre aucun « slot 1 / slot 2 ». Quiconque veut garder
un état — avant un boss, avant un run, avant d'essayer un mod — doit copier des fichiers
à la main, au bon endroit, sans se faire écraser par Steam Cloud. C'est exactement ce
que `core.saves` fait correctement, et cette page en est la surface.

Les trois choses que la page doit absolument dire à l'utilisateur
-----------------------------------------------------------------
1. **Steam Cloud peut annuler une restauration sans le moindre message.** Le client
   recopie le dossier de sauvegardes au démarrage ET à la fermeture. On n'interdit
   rien — c'est la machine de l'utilisateur, et « Steam ouvert mais jeu jamais lancé »
   est parfaitement sûr en pratique — mais il doit l'avoir lu avant, pas découvrir la
   perte après. Le quota `ufs.maxnumfiles = 3` est déjà atteint par les trois `.sav` du
   jeu : `steam_cloud_notice()` détecte le `.sav` de trop posé à la main.
2. **Restaurer écrase la partie en cours**, et prend donc systématiquement un instantané
   automatique de l'état courant avant d'écrire. La page l'annonce AVANT de le faire :
   un filet dont on ignore l'existence ne rassure personne.
3. **Aucune édition de sauvegarde n'est proposée.** Le parseur GVAS est fiable en
   lecture, mais toute écriture qui change une longueur (chaîne, élément de tableau ou
   de map) décale un cadrage inter-objets qui n'est pas rétro-conçu : le fichier casse
   silencieusement, et le joueur ne s'en aperçoit qu'au chargement. La seule opération
   offerte est la copie de fichiers entiers. C'est délibéré, donc c'est écrit à l'écran.

Le cas du poste de dev
----------------------
Sous Linux, `save_dir()` renvoie `None` par construction — le jeu n'y existe pas, et
inventer un chemin plausible ferait échouer les appelants plus loin avec un message
moins clair. La page ne doit pas pour autant sembler cassée : elle affiche franchement
« dossier non détecté », explique pourquoi, et laisse en désigner un à la main. Toutes
les opérations de `core.saves` acceptent une racine explicite, précisément pour ça.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QToolButton, QVBoxLayout,
    QWidget,
)

from ...core import savelib as savelib_mod
from ...core import saves as saves_mod
from ..main_window import Page
from ..theme import METRICS, PALETTE
from ..widgets import Badge, Card, PageHeader, separator

#: Où l'on note le dossier désigné à la main. Il ne va PAS dans `Settings` : c'est un
#: chemin de travail propre à cette page, et l'ajouter aux préférences partagées
#: obligerait à toucher un module que d'autres écrans écrivent aussi.
ROOT_MEMO = "saves_root.txt"


def human_size(size: int) -> str:
    """Taille lisible. Les instantanés pèsent ~2 Mo : l'octet exact n'apprend rien."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} Mo"
    if size >= 1024:
        return f"{size / 1024:.0f} Ko"
    return f"{size} o"


#: Noms de champs « parlants », montrés en évidence dans l'éditeur simple avec un
#: libellé français. Tout le reste part dans la liste repliable « Autres champs » : une
#: sauvegarde expose ~30 noms distincts et 2500 champs, dont beaucoup de plomberie
#: interne (`bCanBeDamaged`, `bBaseLocked`…) qui n'apprend rien au joueur. On concentre
#: donc l'attention sur ce qui correspond à une notion de progression identifiable.
FEATURED_FIELDS: tuple[tuple[str, str], ...] = (
    ("Flying Water Unlocked", "Eau volante débloquée"),
    ("bUnlocked", "Éléments déverrouillés"),
    ("bLooted", "Coffres ramassés"),
    ("AlreadyDestroyed", "Objets destructibles détruits"),
    ("bCheckpointActivated", "Checkpoints activés"),
    ("bDialPlayed", "Dialogues joués"),
    ("HasActivatedAtLeastOnce", "Mécanismes activés"),
    ("bGlitchActivated", "Glitchs activés"),
    ("ConnectedSource", "Sources connectées"),
)

#: Libellés lisibles pour les noms non « featured », quand un existe. Sinon on retombe
#: sur le nom brut : inventer un libellé faux serait pire que montrer le nom technique.
FIELD_LABELS: dict[str, str] = {
    "bBaseActivated": "Socles activés",
    "bBaseLocked": "Socles verrouillés",
    "bPanelShown": "Panneaux révélés",
    "ElevatorActivated": "Ascenseurs activés",
    "bGridOpened": "Grilles ouvertes",
    "bLaserActivated": "Lasers activés",
    "bVinesBurned": "Lianes brûlées",
    "WaterTriggerActivated": "Déclencheurs d'eau",
    "isTutorialDone": "Tutoriels terminés",
    "bClosed": "Éléments fermés",
    "bConnectionRestaured": "Connexions rétablies",
    "bHasPortableItem": "Objets portables présents",
    "bAlreadyPlayed": "Séquences déjà jouées",
    "bEndSplineReached": "Fins de trajet atteintes",
    "bUseLightOnFirstFish": "Lumière du premier poisson",
    "bAutosaveUsed": "Sauvegardes auto utilisées",
    "bActivated": "Activés",
    "bCanBeDamaged": "Peuvent être endommagés",
    "AlphaTrain": "Position de train (alpha)",
    "Revision": "Révision du format",
    "BastionConnected": "Bastion connecté",
    "BastionDoubleConnected": "Bastion doublement connecté",
}


def _field_label(name: str) -> str:
    """Libellé lisible d'un nom de champ, avec repli sur le nom brut."""
    for key, label in FEATURED_FIELDS:
        if key == name:
            return label
    return FIELD_LABELS.get(name, name)


class Collapsible(QWidget):
    """Section repliable : un bouton-titre qui déplie/replie un corps.

    Le corps peut être construit paresseusement (`on_first_expand`) — indispensable pour
    la vue brute de l'éditeur, qui aligne ~2500 champs : les fabriquer d'emblée
    ralentirait l'ouverture de la page pour un écran que la plupart n'ouvriront jamais.
    """

    def __init__(self, title: str, *, on_first_expand=None, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_first_expand = on_first_expand
        self._expanded_once = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(METRICS.pad_sm)

        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        # QToolButton n'hérite pas du style des QPushButton : on lui donne l'allure d'un
        # titre de section cliquable, sans couleur en dur hors PALETTE.
        self.button.setStyleSheet(
            f"QToolButton {{ border:none; background:transparent; color:{PALETTE.text};"
            f" font-size:14px; font-weight:600; padding:{METRICS.pad_sm}px 0; }}"
            f"QToolButton:hover {{ color:{PALETTE.accent}; }}")
        col.addWidget(self.button)

        self.container = QWidget()
        self.body = QVBoxLayout(self.container)
        self.body.setContentsMargins(METRICS.pad, 0, 0, 0)
        self.body.setSpacing(METRICS.pad_sm)
        self.container.setVisible(False)
        col.addWidget(self.container)

        self.button.toggled.connect(self._toggle)

    def _toggle(self, on: bool) -> None:
        self.button.setArrowType(
            Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        if on and not self._expanded_once:
            self._expanded_once = True
            if self._on_first_expand is not None:
                self._on_first_expand(self.body)
        self.container.setVisible(on)

    def set_expanded(self, on: bool) -> None:
        self.button.setChecked(on)


class BoolGroupRow(QWidget):
    """Un nom de champ booléen partagé par plusieurs objets, présenté en agrégat.

    Beaucoup de noms (`bUnlocked`, `AlreadyDestroyed`…) reviennent des dizaines à
    centaines de fois : les afficher un par un serait illisible et sans signification —
    « le coffre n°87 est-il ramassé ? » n'intéresse personne. On montre donc « X/Y
    activés » et une case maîtresse qui bascule tout le groupe d'un coup. Les diffs sont
    calculés par rapport aux valeurs d'origine, jamais accumulés.
    """

    def __init__(self, name: str, fields: list, parent: QWidget | None = None):
        super().__init__(parent)
        self.name = name
        self.fields = fields
        self._original = {f.index: bool(f.value) for f in fields}
        self._state = dict(self._original)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(METRICS.pad)

        self.box = QCheckBox(_field_label(name))
        self.box.setTristate(True)
        row.addWidget(self.box, 1)

        self.count = QLabel()
        self.count.setObjectName("Dim")
        row.addWidget(self.count, 0)

        self._sync()
        self.box.clicked.connect(self._on_click)

    def _on_click(self, _checked: bool = False) -> None:
        # Un clic force une valeur définie pour tout le groupe : si tout n'est pas déjà
        # activé, on active tout ; sinon on désactive tout. On ne laisse jamais l'état
        # se figer sur « partiel », qui n'a pas de sens comme intention utilisateur.
        target = not all(self._state.values())
        for idx in self._state:
            self._state[idx] = target
        self._sync()

    def _sync(self) -> None:
        done = sum(self._state.values())
        total = len(self._state)
        state = (Qt.CheckState.Checked if done == total
                 else Qt.CheckState.Unchecked if done == 0
                 else Qt.CheckState.PartiallyChecked)
        self.box.blockSignals(True)
        self.box.setCheckState(state)
        self.box.blockSignals(False)
        self.count.setText(f"{done}/{total} activés")

    def changes(self) -> dict[int, bool]:
        """Modifications par rapport à l'état d'origine (index → nouvelle valeur)."""
        return {idx: val for idx, val in self._state.items()
                if val != self._original[idx]}


class ScalarFieldRow(QWidget):
    """Un champ numérique unique (entier ou décimal), éditable individuellement.

    Contrairement aux booléens, un scalaire porte une valeur qui a un sens propre
    (`ConnectedSource`, position d'un train…). Le drapeau `_dirty` évite de reporter une
    fausse modification : un décimal réaffiché avec moins de décimales que l'original
    diffère numériquement sans que l'utilisateur y ait touché.
    """

    def __init__(self, field, *, label: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.field = field
        self._dirty = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(METRICS.pad)

        text = label if label is not None else _field_label(field.name)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)

        if field.type == "DoubleProperty" or field.type == "FloatProperty":
            self.spin = QDoubleSpinBox()
            self.spin.setDecimals(6)
            self.spin.setRange(-1e12, 1e12)
            self.spin.setValue(float(field.value or 0))
        else:
            self.spin = QSpinBox()
            self.spin.setRange(-(2 ** 31), 2 ** 31 - 1)
            self.spin.setValue(int(field.value or 0))
        self.spin.setMinimumWidth(140)
        # La valeur initiale est posée AVANT le branchement : `valueChanged` se déclenche
        # aussi sur `setValue`, et on ne veut marquer « modifié » que sur action humaine.
        self.spin.valueChanged.connect(self._mark_dirty)
        row.addWidget(self.spin, 0)

    def _mark_dirty(self, _value=None) -> None:
        self._dirty = True

    def changes(self) -> dict[int, object]:
        if not self._dirty:
            return {}
        return {self.field.index: self.spin.value()}


class RawFieldRow(QWidget):
    """Une ligne de la vue brute « avancée » : nom + type + index + contrôle.

    C'est le « code » que l'on cache derrière le bandeau avancé : chaque champ est
    montré tel quel, éditable un par un, sans regroupement ni libellé traduit. Réservé à
    qui sait ce qu'il fait.
    """

    def __init__(self, field, parent: QWidget | None = None):
        super().__init__(parent)
        self.field = field
        self._original = bool(field.value) if field.is_bool else None
        self._dirty = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(METRICS.pad_sm)

        idx = QLabel(f"#{field.index}")
        idx.setObjectName("Dim")
        idx.setMinimumWidth(56)
        row.addWidget(idx, 0)

        name = QLabel(field.name)
        name.setObjectName("Mono")
        name.setMinimumWidth(220)
        row.addWidget(name, 1)

        row.addWidget(Badge(field.type.replace("Property", ""), "muted"), 0)

        if field.is_bool:
            self.box = QCheckBox()
            self.box.setChecked(bool(field.value))
            row.addWidget(self.box, 0)
            self.spin = None
        else:
            self.box = None
            if field.type in ("DoubleProperty", "FloatProperty"):
                self.spin = QDoubleSpinBox()
                self.spin.setDecimals(6)
                self.spin.setRange(-1e12, 1e12)
                self.spin.setValue(float(field.value or 0))
            else:
                self.spin = QSpinBox()
                self.spin.setRange(-(2 ** 31), 2 ** 31 - 1)
                self.spin.setValue(int(field.value or 0))
            self.spin.setMinimumWidth(130)
            self.spin.valueChanged.connect(self._mark_dirty)
            row.addWidget(self.spin, 0)

    def _mark_dirty(self, _value=None) -> None:
        self._dirty = True

    def changes(self) -> dict[int, object]:
        if self.box is not None:
            if self.box.isChecked() != self._original:
                return {self.field.index: self.box.isChecked()}
            return {}
        if self._dirty:
            return {self.field.index: self.spin.value()}
        return {}


class SaveEditor(QWidget):
    """Éditeur graphique d'un `.sav` : cases et champs numériques, code caché.

    Trois strates de lisibilité décroissante :

    1. les champs « parlants » (progression identifiable), montrés d'emblée ;
    2. « Autres champs », repliable, avec le reste des agrégats ;
    3. « Avancé », repliable et construit à la demande, la vue brute champ par champ.

    L'éditeur ne persiste rien tout seul : `save()` rassemble les diffs et les confie à
    `savelib.write_fields`, qui journalise (donc annulable) et garantit l'aller-retour
    exact du format. Une valeur incohérente ne casse pas le fichier mais peut rendre une
    partie bizarre — l'avertissement à l'écran le dit, et recommande une sauvegarde de
    secours.
    """

    saved = Signal()

    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._path: Path | None = None
        self.default_dir: Path | None = None
        self._group_rows: list = []       # BoolGroupRow | ScalarFieldRow (simple + autres)
        self._raw_rows: list = []         # RawFieldRow (vue brute avancée)

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(METRICS.pad_sm)
        self._rebuild()

    # --- fichier ------------------------------------------------------------------

    def set_path(self, path: Path | None) -> None:
        self._path = Path(path) if path is not None else None
        self._rebuild()

    @property
    def path(self) -> Path | None:
        return self._path

    def _browse(self) -> None:
        start = str(self.default_dir or (self._path.parent if self._path else Path.home()))
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Choisir une sauvegarde à modifier", start,
            "Sauvegardes Fading Echo (*.sav)")
        if chosen:
            self.set_path(Path(chosen))

    # --- rendu --------------------------------------------------------------------

    def _clear(self) -> None:
        self._group_rows = []
        self._raw_rows = []
        while self.root.count():
            item = self.root.takeAt(0)
            if (w := item.widget()) is not None:
                w.setParent(None)
                w.deleteLater()

    def _rebuild(self) -> None:
        self._clear()

        self.root.addWidget(self._file_row())
        self.root.addWidget(self._safety_box())

        if self._path is None:
            hint = QLabel(
                "Aucun fichier sélectionné. Par défaut, l'éditeur ouvre le "
                "« LastCheckpoint.sav » du dossier de sauvegardes courant ; sinon, "
                "choisissez un fichier à modifier.")
            hint.setObjectName("Dim")
            hint.setWordWrap(True)
            self.root.addWidget(hint)
            return

        fields = savelib_mod.editable_fields(self._path)
        if not fields:
            bad = QLabel(
                f"« {self._path.name} » est illisible ou ne contient aucun champ "
                "modifiable sans risque. Vérifiez que c'est bien une sauvegarde du jeu.")
            bad.setStyleSheet(f"color:{PALETTE.error};")
            bad.setWordWrap(True)
            self.root.addWidget(bad)
            return

        # Regroupement par nom, dans l'ordre de première apparition — stable et
        # reproductible entre deux ouvertures du même fichier.
        groups: dict[str, list] = {}
        for f in fields:
            groups.setdefault(f.name, []).append(f)

        featured = [name for name, _ in FEATURED_FIELDS if name in groups]
        others = [name for name in groups if name not in set(featured)]

        self.root.addWidget(self._group_section("Progression", featured, groups))

        rest = Collapsible(f"Autres champs ({len(others)})")
        for name in others:
            self._add_group(rest.body, name, groups[name])
        self.root.addWidget(rest)

        self.root.addWidget(separator())
        advanced = Collapsible(
            f"Avancé — vue brute ({len(fields)} champs)",
            on_first_expand=lambda body, fs=fields: self._fill_raw(body, fs))
        self.advanced = advanced
        self.root.addWidget(advanced)

        save_btn = QPushButton("Enregistrer les modifications")
        save_btn.setObjectName("Primary")
        save_btn.clicked.connect(self.save)
        self.root.addWidget(save_btn)

    def _file_row(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(METRICS.pad_sm)
        label = QLabel(str(self._path) if self._path else "Aucun fichier sélectionné")
        label.setObjectName("Mono")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(label, 1)
        browse = QPushButton("Choisir un fichier…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse, 0)
        return holder

    def _safety_box(self) -> QWidget:
        box = QLabel(
            "Seules les modifications SÛRES sont proposées : cases à cocher et nombres à "
            "largeur fixe. L'édition ne casse jamais le fichier — l'aller-retour du "
            "format est exact à l'octet près — MAIS une valeur incohérente peut rendre "
            "une partie bizarre (zone à moitié débloquée, compteur impossible). "
            "Chargez d'abord une sauvegarde de secours depuis la bibliothèque ci-dessus, "
            "ou prenez un instantané, avant de modifier une vraie partie.")
        box.setWordWrap(True)
        box.setStyleSheet(
            f"color:{PALETTE.warn}; background:{PALETTE.warn_bg};"
            f"border:1px solid {PALETTE.warn}44; border-radius:{METRICS.radius_sm}px;"
            f"padding:{METRICS.pad_sm}px;")
        return box

    def _group_section(self, title: str, names: list[str], groups: dict) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(METRICS.pad_sm)
        head = QLabel(title)
        head.setObjectName("SectionTitle")
        col.addWidget(head)
        if not names:
            empty = QLabel("Aucun champ de progression identifiable dans ce fichier.")
            empty.setObjectName("Dim")
            empty.setWordWrap(True)
            col.addWidget(empty)
        for name in names:
            self._add_group(col, name, groups[name])
        return holder

    def _add_group(self, layout, name: str, fields: list) -> None:
        """Ajoute un agrégat booléen OU une série de scalaires pour un nom donné."""
        if all(f.is_bool for f in fields):
            row = BoolGroupRow(name, fields)
            self._group_rows.append(row)
            layout.addWidget(row)
            return
        # Scalaires : chaque valeur a un sens propre, on les liste individuellement,
        # numérotées quand le même nom en porte plusieurs.
        scalars = [f for f in fields if not f.is_bool]
        multiple = len(scalars) > 1
        for i, f in enumerate(scalars, 1):
            label = f"{_field_label(name)} #{i}" if multiple else _field_label(name)
            row = ScalarFieldRow(f, label=label)
            self._group_rows.append(row)
            layout.addWidget(row)

    def _fill_raw(self, layout, fields: list) -> None:
        """Construit la vue brute à la demande (première ouverture du bandeau)."""
        for f in fields:
            row = RawFieldRow(f)
            self._raw_rows.append(row)
            layout.addWidget(row)

    # --- écriture -----------------------------------------------------------------

    def collect_changes(self) -> dict[int, object]:
        """Rassemble les diffs de toutes les vues. La vue brute a le dernier mot : si un
        même champ a été touché des deux côtés, la valeur brute (explicite) l'emporte."""
        changes: dict[int, object] = {}
        for row in self._group_rows:
            changes.update(row.changes())
        for row in self._raw_rows:
            changes.update(row.changes())
        return changes

    def save(self) -> None:
        if self._path is None:
            return
        changes = self.collect_changes()
        if not changes:
            QMessageBox.information(
                self, "Aucune modification",
                "Rien n'a été modifié : aucune sauvegarde à écrire.")
            return
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Enregistrer les modifications")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Écrire {len(changes)} modification(s) dans "
                        f"« {self._path.name} » ?")
        confirm.setInformativeText(
            "Une vraie sauvegarde va être modifiée. L'opération est annulable depuis le "
            "journal des modifications, mais mieux vaut avoir une sauvegarde de secours "
            "en cas de valeur incohérente. Le jeu doit être fermé.")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes
                                   | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        ok = savelib_mod.write_fields(self._path, changes, ledger=self.ctx.ledger)
        if ok:
            QMessageBox.information(
                self, "Modifications enregistrées",
                f"{len(changes)} champ(s) écrit(s) dans « {self._path.name} ». "
                "L'opération reste annulable depuis le journal.")
            self.saved.emit()
            self.set_path(self._path)   # recharge la nouvelle valeur de référence
        else:
            QMessageBox.warning(
                self, "Échec de l'écriture",
                "Le fichier n'a pas pu être modifié (illisible, ou champ refusé). "
                "La sauvegarde n'a pas été touchée.")


class SavesPage(Page):
    """Liste des instantanés, prise d'instantané, restauration avertie."""

    title = "Sauvegardes"
    icon = "▣"

    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(ctx, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        self.header = PageHeader(
            "Sauvegardes",
            "Le jeu n'a qu'un seul emplacement de sauvegarde. Cette page en garde "
            "des copies, hors de portée de Steam Cloud.")
        root.addWidget(self.header)

        self.snapshot_btn = QPushButton("Sauvegarder l'état actuel")
        self.snapshot_btn.setObjectName("Primary")
        self.snapshot_btn.clicked.connect(self._snapshot)
        self.header.add_action(self.snapshot_btn)

        self.location_card = Card()
        root.addWidget(self.location_card)

        self.cloud_card = Card()
        root.addWidget(self.cloud_card)

        self.library_card = Card()
        root.addWidget(self.library_card)

        # L'éditeur est construit UNE fois et jamais détruit par un rafraîchissement :
        # il garde son fichier ouvert et l'état de ses cases pendant que d'autres cartes
        # se reconstruisent autour de lui.
        self.editor_card = Card()
        editor_title = QLabel("Modifier une sauvegarde")
        editor_title.setObjectName("SectionTitle")
        self.editor_card.body.addWidget(editor_title)
        self.editor = SaveEditor(self.ctx)
        self.editor_card.body.addWidget(self.editor)
        root.addWidget(self.editor_card)

        self.slots_card = Card()
        root.addWidget(self.slots_card)

        root.addWidget(self._build_policy_card())
        root.addStretch(1)

        self.refresh()

    # --- dossier de sauvegardes ---------------------------------------------------

    @property
    def _memo_path(self) -> Path:
        return Path(self.ctx.data_dir) / ROOT_MEMO

    @property
    def save_root(self) -> Path | None:
        """Dossier de sauvegardes : celui du jeu, ou celui désigné à la main.

        La détection automatique passe en premier : sur la machine de jeu, l'utilisateur
        n'a rien à désigner. Le chemin mémorisé ne sert qu'en repli, et il est revérifié
        à chaque lecture — un dossier sur un disque externe débranché doit se signaler
        comme absent, pas faire planter la page.
        """
        detected = saves_mod.save_dir()
        if detected is not None and detected.is_dir():
            return detected
        try:
            memo = self._memo_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return Path(memo) if memo else None

    def set_save_root(self, path: Path | None) -> None:
        self._memo_path.parent.mkdir(parents=True, exist_ok=True)
        self._memo_path.write_text(str(path or ""), encoding="utf-8")
        self.refresh()

    def _browse_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Dossier de sauvegardes de Fading Echo",
            str(self.save_root or Path.home()))
        if chosen:
            self.set_save_root(Path(chosen))

    # --- rendu --------------------------------------------------------------------

    @staticmethod
    def _clear(card: Card) -> None:
        """Vide une carte de son contenu.

        `setParent(None)` avant `deleteLater()` n'est pas redondant : `deleteLater()`
        seul ne détruit le widget qu'au retour dans la boucle d'événements, et
        l'ancien contenu reste affiché par-dessus le nouveau si la carte est
        reconstruite plusieurs fois d'affilée — ce qui arrive dès qu'on enchaîne deux
        instantanés. Le détacher tout de suite le fait disparaître immédiatement.
        """
        while card.body.count():
            item = card.body.takeAt(0)
            if (w := item.widget()) is not None:
                w.setParent(None)
                w.deleteLater()

    def refresh(self) -> None:
        self._render_location()
        self._render_cloud()
        self._render_library()
        self._render_editor()
        self._render_slots()
        root = self.save_root
        self.snapshot_btn.setEnabled(root is not None and root.is_dir())

    def _render_location(self) -> None:
        self._clear(self.location_card)
        root = self.save_root

        row = QHBoxLayout()
        title = QLabel("Dossier de sauvegardes")
        title.setObjectName("SectionTitle")
        row.addWidget(title)
        row.addStretch(1)
        if root is None:
            row.addWidget(Badge("NON DÉTECTÉ", "warn"))
        elif not root.is_dir():
            row.addWidget(Badge("INTROUVABLE", "error"))
        else:
            detected = saves_mod.save_dir()
            row.addWidget(Badge("DÉTECTÉ" if detected is not None else "DÉSIGNÉ À LA MAIN",
                                "ok" if detected is not None else "accent"))
        browse = QPushButton("Choisir un dossier…")
        browse.clicked.connect(self._browse_root)
        row.addWidget(browse)
        holder = QWidget()
        holder.setLayout(row)
        self.location_card.body.addWidget(holder)

        if root is None:
            explain = QLabel(
                "Le dossier de sauvegardes n'a pas été détecté. C'est normal hors "
                "Windows — le jeu range ses sauvegardes dans "
                "%LOCALAPPDATA%\\UE_YGRO\\Saved\\SaveGames\\<SteamID>, qui n'existe "
                "pas ici. Ce peut aussi être le cas si plusieurs comptes Steam "
                "cohabitent : on ne devine pas lequel, car restaurer dans le mauvais "
                "compte serait une perte de données. Désignez le dossier à la main "
                "pour utiliser la page.")
            explain.setObjectName("Dim")
            explain.setWordWrap(True)
            self.location_card.body.addWidget(explain)
            return

        path_label = QLabel(str(root))
        path_label.setObjectName("Mono")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.location_card.body.addWidget(path_label)

        if not root.is_dir():
            gone = QLabel("Ce dossier n'existe plus (disque débranché, chemin renommé ?). "
                          "Choisissez-en un autre.")
            gone.setStyleSheet(f"color:{PALETTE.error};")
            gone.setWordWrap(True)
            self.location_card.body.addWidget(gone)
            return

        present = [n for n in saves_mod.GAME_SAVE_FILES if (root / n).is_file()]
        detail = QLabel(
            f"Fichiers du jeu présents : {', '.join(present) if present else 'aucun'} · "
            f"instantanés rangés dans « {saves_mod.SLOTS_DIRNAME}/ »")
        detail.setObjectName("Dim")
        detail.setWordWrap(True)
        self.location_card.body.addWidget(detail)

    def _render_cloud(self) -> None:
        self._clear(self.cloud_card)
        title = QLabel("Steam Cloud")
        title.setObjectName("SectionTitle")
        self.cloud_card.body.addWidget(title)

        # Cet avertissement est permanent, pas conditionnel : le piège n'est pas un
        # incident rare qu'on signalerait quand il se produit, c'est le fonctionnement
        # normal de Steam pour ce jeu.
        base = QLabel(
            f"Ce jeu ne synchronise que {saves_mod.UFS_MAX_NUM_FILES} fichiers .sav, "
            "et il en a exactement trois : le quota est plein. Un .sav supplémentaire "
            "posé à la main dans ce dossier met la synchro dans un état non spécifié — "
            "Steam ne garantit pas lequel il conservera. Par ailleurs, le client "
            "recopie ce dossier à son démarrage ET à sa fermeture : une sauvegarde "
            "restaurée pendant que Steam tourne peut être remplacée quelques secondes "
            "plus tard, sans message et sans erreur. Dans le doute, quittez "
            "complètement Steam avant de restaurer.")
        base.setWordWrap(True)
        base.setStyleSheet(
            f"color:{PALETTE.warn}; background:{PALETTE.warn_bg};"
            f"border:1px solid {PALETTE.warn}44; border-radius:{METRICS.radius_sm}px;"
            f"padding:{METRICS.pad_sm}px;")
        self.cloud_card.body.addWidget(base)

        root = self.save_root
        if root is None or not root.is_dir():
            return
        for notice in saves_mod.steam_cloud_notice(root):
            lbl = QLabel("!  " + notice)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{PALETTE.error};")
            self.cloud_card.body.addWidget(lbl)

    # --- bibliothèque de sauvegardes prêtes ---------------------------------------

    def _render_library(self) -> None:
        """Liste les sauvegardes embarquées (`savelib.bundled_saves`) avec un bouton
        « Charger » par ligne, et un bouton d'annulation du dernier chargement.

        La bibliothèque est indépendante du dossier de saves : on peut la CONSULTER même
        sans dossier détecté. Seul le chargement a besoin d'une destination — d'où
        l'avertissement affiché quand aucun dossier n'est désigné.
        """
        self._clear(self.library_card)
        title = QLabel("Sauvegardes prêtes à charger")
        title.setObjectName("SectionTitle")
        self.library_card.body.addWidget(title)

        intro = QLabel(
            "Des parties à différents points de progression, livrées avec le launcher. "
            "En charger une remplace votre sauvegarde actuelle — l'état d'avant est mis "
            "de côté et récupérable UNE seule fois (le chargement suivant l'écrase).")
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        self.library_card.body.addWidget(intro)

        root = self.save_root
        if root is None or not root.is_dir():
            warn = QLabel(
                "!  Aucun dossier de sauvegardes désigné : vous pouvez consulter la "
                "liste, mais pas encore charger. Choisissez d'abord un dossier ci-dessus.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color:{PALETTE.warn};")
            self.library_card.body.addWidget(warn)

        if savelib_mod.has_rollback(save_root=root):
            undo = QPushButton("Annuler le dernier chargement")
            undo.clicked.connect(self._rollback_bundled)
            undo_row = QHBoxLayout()
            undo_row.addStretch(1)
            undo_row.addWidget(undo)
            holder = QWidget()
            holder.setLayout(undo_row)
            self.library_card.body.addWidget(holder)

        saves = savelib_mod.bundled_saves()
        if not saves:
            empty = QLabel("Aucune sauvegarde embarquée n'a été trouvée.")
            empty.setObjectName("Dim")
            self.library_card.body.addWidget(empty)
            return

        for i, save in enumerate(saves):
            if i:
                self.library_card.body.addWidget(separator())
            self.library_card.body.addWidget(self._bundled_row(save, enabled=root is not None and root.is_dir()))

    def _bundled_row(self, save, *, enabled: bool) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, METRICS.pad_sm, 0, METRICS.pad_sm)
        col.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(METRICS.pad_sm)
        name = QLabel(save.name)
        name.setObjectName("SectionTitle")
        top.addWidget(name)
        if not save.complete:
            top.addWidget(Badge("INCOMPLÈTE", "warn"))
        top.addStretch(1)
        load = QPushButton("Charger")
        load.setEnabled(enabled and save.complete)
        load.clicked.connect(lambda _=False, s=save: self._load_bundled(s))
        top.addWidget(load)
        top_holder = QWidget()
        top_holder.setLayout(top)
        col.addWidget(top_holder)

        if save.progress:
            progress = QLabel(save.progress)
            progress.setObjectName("Dim")
            progress.setWordWrap(True)
            col.addWidget(progress)
        return holder

    def _load_bundled(self, save) -> None:
        root = self.save_root
        if root is None or not root.is_dir():
            return
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Charger une sauvegarde")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Charger « {save.name} » ?")
        confirm.setInformativeText(
            "Votre sauvegarde ACTUELLE va être mise de côté (récupérable UNE seule fois "
            "via « Annuler le dernier chargement »), puis remplacée par cette "
            "sauvegarde.\n\n"
            "Si vous rechargez une autre sauvegarde ensuite, cette mise de côté sera "
            "perdue — on ne garde qu'un seul retour en arrière.\n\n"
            "Le jeu doit être fermé.")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes
                                   | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        report = self.apply_bundled(save)
        self._show_apply_report(report)

    def apply_bundled(self, save) -> savelib_mod.ApplyReport:
        """Charge une sauvegarde de la bibliothèque et rend le compte rendu, sans rien
        afficher. Séparé de la boîte de dialogue pour rester testable."""
        root = self.save_root
        report = savelib_mod.apply_bundled(
            save, save_root=root, steam_id=None, ledger=self.ctx.ledger)
        self.refresh()
        return report

    def _rollback_bundled(self) -> None:
        report = savelib_mod.restore_rollback(
            save_root=self.save_root, ledger=self.ctx.ledger)
        self.refresh()
        self._show_apply_report(report)

    def _show_apply_report(self, report: savelib_mod.ApplyReport) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Chargement" if report.ok else "Chargement impossible")
        box.setIcon(QMessageBox.Icon.Information if report.ok else QMessageBox.Icon.Warning)
        box.setText(report.message)
        if report.warnings:
            box.setInformativeText("\n\n".join("!  " + w for w in report.warnings))
        box.exec()

    # --- éditeur de sauvegarde ----------------------------------------------------

    def _render_editor(self) -> None:
        """Donne à l'éditeur un fichier par défaut, sans le reconstruire.

        L'éditeur garde SON fichier une fois qu'il en a un (choisi à la main ou ouvert
        par défaut) : un rafraîchissement ne doit pas le renvoyer sans prévenir sur le
        LastCheckpoint.sav pendant que l'utilisateur édite une autre sauvegarde. On ne
        touche donc qu'au dossier par défaut et, si aucun fichier n'est encore ouvert, au
        fichier de départ.
        """
        root = self.save_root
        self.editor.default_dir = root if (root is not None and root.is_dir()) else None
        if self.editor.path is None and root is not None and root.is_dir():
            default = root / "LastCheckpoint.sav"
            if default.is_file():
                self.editor.set_path(default)

    def _render_slots(self) -> None:
        self._clear(self.slots_card)
        row = QHBoxLayout()
        title = QLabel("Instantanés")
        title.setObjectName("SectionTitle")
        row.addWidget(title)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.slots_card.body.addWidget(holder)

        root = self.save_root
        slots = saves_mod.list_slots(root) if root is not None and root.is_dir() else []
        count = QLabel(f"{len(slots)} instantané(s)")
        count.setObjectName("Dim")
        row.addWidget(count)

        if not slots:
            empty = QLabel(
                "Aucun instantané pour l'instant. « Sauvegarder l'état actuel » copie "
                "les trois fichiers du jeu dans un sous-dossier que Steam Cloud ne "
                "voit pas — l'opération ne touche pas à la partie en cours."
                if root is not None and root.is_dir() else
                "Désignez d'abord un dossier de sauvegardes.")
            empty.setObjectName("Dim")
            empty.setWordWrap(True)
            self.slots_card.body.addWidget(empty)
            return

        for i, slot in enumerate(slots):
            if i:
                self.slots_card.body.addWidget(separator())
            self.slots_card.body.addWidget(self._slot_row(slot))

    def _slot_row(self, slot: saves_mod.SaveSlot) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, METRICS.pad_sm, 0, METRICS.pad_sm)
        col.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(METRICS.pad_sm)
        name = QLabel(slot.name)
        name.setObjectName("SectionTitle")
        top.addWidget(name)
        if not slot.complete:
            # Un slot partiel reste restaurable — on ne remet que ce qu'il contient —
            # mais l'utilisateur doit savoir que le reste ne bougera pas.
            top.addWidget(Badge("PARTIEL", "warn"))
        if slot.source == "auto-restauration":
            top.addWidget(Badge("FILET AUTOMATIQUE", "accent"))
        top.addStretch(1)

        restore = QPushButton("Restaurer")
        restore.clicked.connect(lambda _=False, s=slot: self._restore(s))
        top.addWidget(restore)
        delete = QPushButton("Supprimer")
        delete.setObjectName("Danger")
        delete.clicked.connect(lambda _=False, s=slot: self._delete(s))
        top.addWidget(delete)
        top_holder = QWidget()
        top_holder.setLayout(top)
        col.addWidget(top_holder)

        meta = QLabel(f"{slot.created_local} · {human_size(slot.size)} · "
                      f"{len(slot.files)} fichier(s) · {slot.source}")
        meta.setObjectName("Dim")
        col.addWidget(meta)

        if slot.progress:
            progress = QLabel(slot.progress)
            progress.setWordWrap(True)
            progress.setStyleSheet(f"color:{PALETTE.text};")
            col.addWidget(progress)

        if slot.note:
            note = QLabel("« " + slot.note + " »")
            note.setObjectName("Dim")
            note.setWordWrap(True)
            col.addWidget(note)
        return holder

    def _build_policy_card(self) -> Card:
        card = Card()
        title = QLabel("Ce que cette page ne fait pas")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)
        text = QLabel(
            "L'éditeur ci-dessus ne propose QUE les modifications sûres : cases à cocher "
            "et nombres à largeur fixe, dont l'aller-retour est exact à l'octet près. "
            "Il ne touche jamais aux chaînes, tableaux ou maps : le format de ces "
            "sauvegardes contient un cadrage entre objets qui n'est pas rétro-conçu, et "
            "toute écriture qui change une longueur le décale — le fichier reste "
            "chargeable en apparence et casse plus tard, sans message. Ces champs sont "
            "donc lus mais jamais proposés à l'écriture. La copie de fichiers entiers "
            "(instantanés, bibliothèque) reste, elle, sans le moindre risque.")
        text.setObjectName("Dim")
        text.setWordWrap(True)
        card.body.addWidget(text)
        return card

    # --- actions ------------------------------------------------------------------

    def _snapshot(self) -> None:
        root = self.save_root
        if root is None or not root.is_dir():
            return
        name, ok = QInputDialog.getText(
            self, "Sauvegarder l'état actuel",
            "Nom de l'instantané :", QLineEdit.EchoMode.Normal,
            "avant-boss")
        if not ok or not name.strip():
            return
        note, ok = QInputDialog.getText(
            self, "Sauvegarder l'état actuel",
            "Note (facultative) — à quoi correspond cet état ?")
        if not ok:
            return
        self.take_snapshot(name.strip(), note.strip())

    def take_snapshot(self, name: str, note: str = "") -> saves_mod.SaveSlot | None:
        """Prend un instantané et rend compte. Séparé de la boîte de dialogue pour être
        appelable par un test comme par un autre écran."""
        root = self.save_root
        if root is None:
            return None
        try:
            slot = saves_mod.snapshot(name, root, note=note, ledger=self.ctx.ledger)
        except FileExistsError:
            QMessageBox.warning(
                self, "Nom déjà pris",
                f"Un instantané nommé « {name} » existe déjà.\n\nIl n'est pas écrasé : "
                "ce serait perdre exactement ce que vous cherchiez à protéger. "
                "Choisissez un autre nom.")
            return None
        except (FileNotFoundError, OSError) as exc:
            QMessageBox.warning(self, "Instantané impossible", str(exc))
            return None
        self.refresh()
        return slot

    def _restore(self, slot: saves_mod.SaveSlot) -> None:
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Restaurer un instantané")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Restaurer « {slot.name} » ?")
        confirm.setInformativeText(
            "Les fichiers de sauvegarde du jeu vont être remplacés par ceux de cet "
            "instantané : la progression faite depuis sera écrasée.\n\n"
            "Un instantané automatique de l'état actuel est pris AVANT toute écriture, "
            "sous le nom « avant-restauration-<date> ». Vous pourrez donc revenir en "
            "arrière depuis cette page, ou annuler l'opération entière depuis le "
            "journal des modifications.\n\n"
            "Le jeu doit être fermé.")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes
                                   | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return
        report = self.restore_slot(slot)
        if report is not None:
            self.show_report(report)

    def restore_slot(self, slot: saves_mod.SaveSlot) -> saves_mod.RestoreReport | None:
        """Restaure et rend le compte rendu, sans rien afficher.

        La restauration et son compte rendu sont séparés à dessein : l'opération est
        ainsi appelable par un test (ou un jour par un autre écran) sans qu'une boîte
        de dialogue modale n'attende un clic qui ne viendra pas.
        """
        root = self.save_root
        if root is None:
            return None
        report = saves_mod.restore(slot, root, ledger=self.ctx.ledger)
        self.refresh()
        return report

    def show_report(self, report: saves_mod.RestoreReport) -> None:
        """Affiche le compte rendu d'une restauration, avertissements compris."""
        box = QMessageBox(self)
        box.setWindowTitle("Restauration" if report.ok else "Restauration annulée")
        box.setIcon(QMessageBox.Icon.Information if report.ok else QMessageBox.Icon.Warning)
        box.setText(report.message)
        if report.warnings:
            # Les avertissements ne sont pas repliés dans un « détails » : celui sur
            # Steam Cloud décrit une perte de données possible dans la minute qui suit.
            box.setInformativeText("\n\n".join("!  " + w for w in report.warnings))
        box.exec()

    def _delete(self, slot: saves_mod.SaveSlot) -> None:
        confirm = QMessageBox.question(
            self, "Supprimer un instantané",
            f"Supprimer définitivement « {slot.name} » ?\n\n"
            "Les fichiers de cet instantané seront effacés du disque. La partie en "
            "cours n'est pas touchée.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm is not QMessageBox.StandardButton.Yes:
            return
        saves_mod.delete_slot(slot, ledger=self.ctx.ledger)
        self.refresh()
