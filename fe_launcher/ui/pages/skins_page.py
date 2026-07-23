"""Page Skins : galerie de personnages, options d'apparence, avertissement de lag.

Deux colonnes, comme la page Mods : la galerie de portraits à gauche, le détail et les
options du personnage sélectionné à droite. Le skin n'est pas appliqué en direct — le mod
FESkins ne se pilote qu'en jeu — mais écrit dans ses constantes de démarrage (via le
journal, donc annulable) et pris en compte au prochain lancement. C'est dit à l'écran
plutôt que laissé deviner.

L'avertissement de lag est en tête, permanent : changer de skin fait ramer, c'est
structurel (le mod réapplique en boucle), et mieux vaut le savoir avant que le découvrir.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...core import skins
from ...core.mods import ModState
from ..main_window import Page
from ..theme import METRICS, PALETTE
from ..widgets import Badge, Card, ComboBox, PageHeader, separator

_TILE = QSize(96, 104)


class PortraitTile(QPushButton):
    """Une vignette cliquable de la galerie : portrait si dispo, sinon initiale."""

    picked = Signal(str)

    def __init__(self, entry: skins.SkinEntry, parent: QWidget | None = None):
        super().__init__(parent)
        self.entry = entry
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(_TILE.width() + 12, _TILE.height() + 26)
        self.setToolTip(entry.label)
        self.clicked.connect(lambda: self.picked.emit(entry.alias))

        col = QVBoxLayout(self)
        col.setContentsMargins(4, 6, 4, 4)
        col.setSpacing(3)

        img = QLabel()
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setFixedSize(_TILE)
        portrait = entry.portrait
        if portrait is not None:
            pix = QPixmap(str(portrait))
            if not pix.isNull():
                img.setPixmap(pix.scaled(_TILE, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
            else:
                self._placeholder(img)
        else:
            self._placeholder(img)
        col.addWidget(img, 0, Qt.AlignmentFlag.AlignCenter)

        name = QLabel(entry.label)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet("font-size:11px;")
        col.addWidget(name)

    def _placeholder(self, img: QLabel) -> None:
        # Pas de portrait : on montre l'initiale sur une pastille, plutôt qu'un vide.
        img.setText(self.entry.label[:1].upper())
        img.setStyleSheet(
            f"background:{PALETTE.surface_alt}; color:{PALETTE.text_dim};"
            f"border-radius:6px; font-size:34px; font-weight:600;")

    def _refresh_style(self) -> None:
        border = PALETTE.accent if self.isChecked() else PALETTE.border
        self.setStyleSheet(
            f"PortraitTile {{ background:{PALETTE.surface}; border:1px solid {border};"
            f" border-radius:{METRICS.radius_sm}px; }}"
            f"PortraitTile:hover {{ border-color:{PALETTE.accent}; }}")

    def setChecked(self, checked: bool) -> None:  # noqa: N802 — API Qt
        super().setChecked(checked)
        self._refresh_style()

    def showEvent(self, event) -> None:  # noqa: N802
        self._refresh_style()
        super().showEvent(event)


class SkinsPage(Page):
    title = "Skins"
    icon = "◐"

    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(ctx, parent)
        self.selected: str = "one"
        self._tiles: dict[str, PortraitTile] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        root.addWidget(PageHeader(
            "Skins", "Changer l'apparence de One, cacher le bâton ou les cheveux."))

        # Avertissement de lag, permanent et en évidence.
        warn = QLabel("⚠  " + skins.LAG_WARNING)
        warn.setWordWrap(True)
        warn.setStyleSheet(
            f"background:{PALETTE.warn_bg}; color:{PALETTE.warn};"
            f"border:1px solid {PALETTE.warn}44; border-radius:{METRICS.radius_sm}px;"
            f"padding:{METRICS.pad_sm}px {METRICS.pad}px;")
        root.addWidget(warn)

        self.status_card = Card()
        root.addWidget(self.status_card)

        columns = QHBoxLayout()
        columns.setSpacing(METRICS.pad)

        self.gallery_card = Card()
        columns.addWidget(self.gallery_card, 3)

        self.detail_card = Card()
        columns.addWidget(self.detail_card, 2)
        root.addLayout(columns, 1)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._build_gallery()
        self.refresh()

    # --- construction ---

    def _mod(self):
        return next((m for m in self.ctx.mods if m.name == "ue4ss-FESkins"), None)

    def _build_gallery(self) -> None:
        title = QLabel("Personnages")
        title.setObjectName("SectionTitle")
        self.gallery_card.body.addWidget(title)

        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(METRICS.pad_sm)
        cols = 5
        for i, entry in enumerate(skins.CHARACTERS):
            tile = PortraitTile(entry)
            tile.picked.connect(self._on_pick)
            self._group.addButton(tile)
            self._tiles[entry.alias] = tile
            grid.addWidget(tile, i // cols, i % cols)
        self.gallery_card.body.addWidget(grid_holder)

    # --- rendu ---

    @staticmethod
    def _clear(card: Card) -> None:
        while card.body.count():
            item = card.body.takeAt(0)
            if (w := item.widget()) is not None:
                w.setParent(None)

    def refresh(self) -> None:
        self._render_status()
        self._render_detail()

    def _render_status(self) -> None:
        self._clear(self.status_card)
        mod = self._mod()

        if mod is None or mod.state is ModState.DISABLED:
            msg = QLabel("Le mod FESkins n'est pas activé. Activez-le dans la page Mods "
                         "pour pouvoir changer de skin — la sélection ci-dessous restera "
                         "mémorisée en attendant.")
            msg.setObjectName("Dim")
            msg.setWordWrap(True)
            self.status_card.body.addWidget(msg)
            return

        state = skins.read_state(mod)
        row = QHBoxLayout()
        label = QLabel("Skin au prochain lancement :")
        row.addWidget(label)
        if state is None:
            row.addWidget(Badge("VERSION TROP ANCIENNE", "warn"))
        elif state.mesh != "none":
            ch = skins.character(state.mesh)
            row.addWidget(Badge((ch.label if ch else state.mesh).upper(), "accent"))
        elif state.one_skin >= 0:
            row.addWidget(Badge(f"ONE — {skins.ONE_SKINS.get(state.one_skin, '?')}".upper(),
                                "accent"))
        else:
            row.addWidget(Badge("APPARENCE D'ORIGINE", "muted"))
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.status_card.body.addWidget(holder)

    def _render_detail(self) -> None:
        self._clear(self.detail_card)
        entry = skins.character(self.selected)
        if entry is None:
            return

        title = QLabel(entry.label)
        title.setObjectName("SectionTitle")
        self.detail_card.body.addWidget(title)

        if not entry.has_portrait:
            no_img = QLabel("Pas d'aperçu disponible pour ce personnage.")
            no_img.setObjectName("Dim")
            self.detail_card.body.addWidget(no_img)

        for text in (entry.note, skins.deform_note(entry.alias)):
            if text:
                lbl = QLabel(text)
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f"color:{PALETTE.text_dim};")
                self.detail_card.body.addWidget(lbl)

        self.detail_card.body.addWidget(separator())

        # Options d'apparence.
        self.outline_box = ComboBox()
        self.outline_box.addItems(["Ne pas toucher", "Masquer la silhouette",
                                   "Forcer la silhouette"])
        self._add_option("Contour (outline)", self.outline_box)

        self.hide_stick = QCheckBox("Cacher le bâton")
        self.hide_hair = QCheckBox("Cacher les cheveux / le bigoudi")
        self.detail_card.body.addWidget(self.hide_stick)
        self.detail_card.body.addWidget(self.hide_hair)

        # Pré-remplir depuis l'état courant du mod.
        mod = self._mod()
        state = skins.read_state(mod) if mod else None
        if state is not None:
            self.outline_box.setCurrentIndex(
                {"keep": 0, "off": 1, "on": 2}.get(state.outline, 0))
            self.hide_stick.setChecked(state.hide_stick)
            self.hide_hair.setChecked(state.hide_hair)

        self.detail_card.body.addStretch(1)

        apply_row = QHBoxLayout()
        reset_btn = QPushButton("Rétablir One")
        reset_btn.clicked.connect(self._on_reset)
        apply_row.addWidget(reset_btn)
        apply_row.addStretch(1)
        apply_btn = QPushButton(f"Appliquer {entry.label}")
        apply_btn.setObjectName("Primary")
        apply_btn.clicked.connect(self._on_apply)
        apply_row.addWidget(apply_btn)
        holder = QWidget()
        holder.setLayout(apply_row)
        self.detail_card.body.addWidget(holder)

    def _add_option(self, label: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(120)
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        holder = QWidget()
        holder.setLayout(row)
        self.detail_card.body.addWidget(holder)

    # --- actions ---

    def _on_pick(self, alias: str) -> None:
        self.selected = alias
        self._render_detail()

    def _current_state(self) -> skins.SkinState:
        outline = {0: "keep", 1: "off", 2: "on"}[self.outline_box.currentIndex()]
        return skins.SkinState(
            mesh=self.selected if self.selected != "one" else "none",
            outline=outline,
            hide_stick=self.hide_stick.isChecked(),
            hide_hair=self.hide_hair.isChecked(),
        )

    def _require_mod(self):
        mod = self._mod()
        if mod is None:
            QMessageBox.warning(self, "Mod absent",
                                "Le mod FESkins n'est pas installé dans cette version "
                                "du jeu.")
            return None
        return mod

    def _on_apply(self) -> None:
        mod = self._require_mod()
        if mod is None:
            return
        report = skins.apply(mod, self._current_state(), self.ctx.ledger)
        if report.ok:
            QMessageBox.information(self, "Skin enregistré", report.message)
        else:
            QMessageBox.warning(self, "Impossible", report.message)
        self.ctx.refresh()

    def _on_reset(self) -> None:
        mod = self._require_mod()
        if mod is None:
            return
        skins.reset(mod, self.ctx.ledger)
        self.selected = "one"
        self.ctx.refresh()
