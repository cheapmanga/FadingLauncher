"""Composants d'interface réutilisables.

La pièce centrale est `build_editor()` : elle transforme un réglage de mod en contrôle
graphique adapté à son type. C'est ce qui permet de tenir la promesse « on ne touche
jamais à du code ».

Les mods de Fading Echo n'ont aucun fichier de configuration : leurs réglages sont des
`local NOM = valeur` en tête de `main.lua`, avec un commentaire qui documente souvent le
domaine (`-- water|waste|fire|glitch`). Le module `luaconf` en extrait le type et les
valeurs possibles ; ici on en déduit le bon widget :

    booléen                  -> case à cocher
    chaîne avec domaine      -> liste déroulante
    chaîne libre             -> champ texte
    nombre                   -> compteur, borné quand le nom du réglage le permet

L'utilisateur voit « Délai grab → void : [500] ms », jamais `local VOID_DELAY_MS = 500`.
Le Lua brut n'apparaît que dans les options avancées.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QMargins, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.luaconf import LuaSetting, LuaType
from .theme import METRICS, PALETTE, badge_style


class FlowLayout(QLayout):
    """Disposition qui fait passer ses widgets à la ligne selon la largeur disponible.

    Qt n'en fournit pas ; c'est l'implémentation de référence des exemples Qt, adaptée.
    Chaque enfant garde sa taille idéale et on remplit ligne par ligne, en repassant à la
    ligne dès qu'un élément déborde. C'est ce qui rend une galerie de cartes RESPONSIVE :
    une fenêtre large montre quatre cartes de front, une fenêtre étroite une seule, sans
    calcul de colonnes en dur. L'espacement horizontal ET vertical vaut `spacing`.
    """

    def __init__(self, parent: QWidget | None = None, *, spacing: int = METRICS.pad):
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    # --- API QLayout obligatoire ---
    def addItem(self, item) -> None:  # noqa: N802 — API Qt
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    # --- cœur : place les éléments, renvoie la hauteur totale ---
    def _layout(self, rect: QRect, *, apply: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > eff.right() and line_h > 0:
                # débordement : on passe à la ligne suivante.
                x = eff.x()
                y += line_h + self._spacing
                next_x = x + hint.width() + self._spacing
                line_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class ComboBox(QComboBox):
    """Liste déroulante dont le chevron est peint, faute de mieux en QSS.

    Qt ignore `transform` dans les feuilles de style — un chevron composé de bordures
    tournées s'affiche en « L ». Utiliser `image:` imposerait d'embarquer un fichier
    d'icône et de gérer son chemin après empaquetage. Deux traits peints coûtent moins
    cher que les deux, et suivent la couleur du thème au survol.
    """

    def paintEvent(self, event) -> None:  # noqa: N802 — API Qt
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(PALETTE.accent if self.underMouse() else PALETTE.text_dim)
        painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx = self.width() - 13
        cy = self.height() / 2
        w, h = 3.8, 2.2
        painter.drawPolyline([QPointF(cx - w, cy - h),
                              QPointF(cx, cy + h),
                              QPointF(cx + w, cy - h)])
        painter.end()


class Card(QFrame):
    """Panneau encadré, unité de base de la mise en page."""

    def __init__(self, parent: QWidget | None = None, *, padding: int | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        pad = METRICS.pad if padding is None else padding
        self.body.setContentsMargins(pad, pad, pad, pad)
        self.body.setSpacing(METRICS.pad_sm)


class Badge(QLabel):
    """Pastille d'état colorée. `kind` ∈ ok / warn / error / accent / muted."""

    def __init__(self, text: str, kind: str = "muted", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setStyleSheet(badge_style(kind))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_kind(self, text: str, kind: str) -> None:
        self.setText(text)
        self.setStyleSheet(badge_style(kind))


class PageHeader(QWidget):
    """Titre + sous-titre d'une page, avec une zone d'actions à droite."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, METRICS.pad_sm)

        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        col.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("PageSubtitle")
            s.setWordWrap(True)
            col.addWidget(s)
        row.addLayout(col, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(METRICS.pad_sm)
        row.addLayout(self.actions, 0)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


# --- Fabrique de contrôles à partir d'un réglage Lua -----------------------------

# Bornes raisonnables déduites du nom du réglage. Ce n'est PAS une validation du jeu —
# aucune borne n'est documentée côté moteur — mais un garde-fou d'interface : il évite
# de saisir un délai de 10 000 000 ms par une faute de frappe pendant une campagne.
_HINTS: dict[str, tuple[float, float, str]] = {
    "DELAY": (0, 10_000, "ms"),
    "MS": (0, 10_000, "ms"),
    "SPEED": (0, 10_000, "cm/s"),
    "TICK": (1, 1_000, "ms"),
    "COUNT": (0, 9_999, ""),
    "RADIUS": (0, 100_000, "cm"),
    "OFFSET": (-100_000, 100_000, "cm"),
    "PRESET": (0, 10, ""),
    "GOAL": (0, 999, ""),
}


def _hint_for(name: str) -> tuple[float, float, str]:
    upper = name.upper()
    for key, hint in _HINTS.items():
        if key in upper:
            return hint
    return (-1_000_000, 1_000_000, "")


def humanize(name: str) -> str:
    """`VOID_DELAY_MS` -> `Void delay ms`. Un libellé lisible à défaut de mieux.

    On ne traduit pas : inventer un libellé français pour chaque constante de chaque
    mod serait une table à maintenir qui divergerait des mods. Le commentaire du .lua,
    affiché en dessous, porte déjà l'explication en français quand l'auteur en a mis un.
    """
    return name.replace("_", " ").strip().capitalize()


class SettingEditor(QWidget):
    """Une ligne de réglage : libellé, contrôle adapté au type, aide.

    Émet `changed(nom, valeur)` quand l'utilisateur modifie la valeur. L'écriture dans
    le fichier n'est PAS faite ici — c'est la page qui décide quand persister, pour
    pouvoir grouper les modifications et les journaliser.
    """

    changed = Signal(str, object)

    def __init__(self, setting: LuaSetting, parent: QWidget | None = None):
        super().__init__(parent)
        self.setting = setting
        self._emitting = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(METRICS.pad)

        label = QLabel(humanize(setting.name))
        label.setMinimumWidth(190)
        label.setWordWrap(True)
        row.addWidget(label, 0)

        self.control = self._build_control()
        row.addWidget(self.control, 1)
        root.addLayout(row)

        # Le commentaire du .lua est la meilleure documentation disponible : il vient
        # de l'auteur du mod et il est déjà en français.
        if setting.comment:
            help_label = QLabel(setting.comment)
            help_label.setObjectName("Dim")
            help_label.setWordWrap(True)
            help_label.setContentsMargins(190 + METRICS.pad, 0, 0, 0)
            root.addWidget(help_label)

    def _build_control(self) -> QWidget:
        s = self.setting

        if not s.editable:
            # Tables et expressions : lecture seule, mais on montre quand même la
            # valeur — la masquer donnerait l'impression que le réglage n'existe pas.
            w = QLineEdit(s.raw_value)
            w.setReadOnly(True)
            w.setObjectName("Mono")
            w.setToolTip("Ce réglage est une structure : il se modifie dans le fichier "
                         "du mod, via les options avancées.")
            return w

        if s.type is LuaType.BOOLEAN:
            w = QCheckBox()
            w.setChecked(bool(s.value))
            w.toggled.connect(lambda v: self._emit(bool(v)))
            return w

        if s.type is LuaType.STRING:
            choices = s.choices
            if choices:
                w = ComboBox()
                w.addItems(choices)
                current = str(s.value)
                if current in choices:
                    w.setCurrentIndex(choices.index(current))
                else:
                    # Valeur hors domaine : on l'ajoute plutôt que de la perdre
                    # silencieusement en forçant le premier choix.
                    w.insertItem(0, current)
                    w.setCurrentIndex(0)
                w.currentTextChanged.connect(self._emit)
                return w
            w = QLineEdit(str(s.value))
            # Sans ça, un chemin d'asset long s'affiche cadré à droite (le curseur
            # part en fin de texte) et on ne voit que sa terminaison — or c'est le
            # début qui identifie la valeur.
            w.setCursorPosition(0)
            w.textEdited.connect(self._emit)
            return w

        # NUMBER
        low, high, unit = _hint_for(s.name)
        is_float = isinstance(s.value, float)
        w = QDoubleSpinBox() if is_float else QSpinBox()
        w.setRange(low, high) if is_float else w.setRange(int(low), int(high))
        if is_float:
            w.setDecimals(2)
            w.setValue(float(s.value or 0))
        else:
            w.setValue(int(s.value or 0))
        if unit:
            w.setSuffix(f" {unit}")
        w.setMinimumWidth(140)
        w.valueChanged.connect(self._emit)
        return w

    def _emit(self, value: object) -> None:
        if self._emitting:
            self.changed.emit(self.setting.name, value)

    def set_value(self, value: object) -> None:
        """Met à jour le contrôle sans réémettre `changed` (évite les boucles)."""
        self._emitting = False
        try:
            w = self.control
            if isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            elif isinstance(w, QComboBox):
                idx = w.findText(str(value))
                if idx >= 0:
                    w.setCurrentIndex(idx)
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(type(w.value())(value))
            elif isinstance(w, QLineEdit):
                w.setText(str(value))
        finally:
            self._emitting = True


def build_editors(settings: list[LuaSetting],
                  on_change: Callable[[str, object], None],
                  *, advanced: bool = False) -> tuple[QWidget, dict[str, SettingEditor]]:
    """Construit un panneau de réglages. Retourne (widget, éditeurs par nom).

    Par défaut, n'affiche que les réglages destinés à l'utilisateur (`user_facing`).
    `advanced=True` montre toutes les constantes éditables du fichier, y compris les
    identifiants techniques et les variables internes — c'est le mode « je sais ce que
    je fais », pas le mode par défaut.
    """
    if not advanced:
        settings = [s for s in settings if s.user_facing]
    holder = QWidget()
    # Sans fond transparent, ce conteneur peint le fond de la fenêtre par-dessus la
    # carte qui l'accueille et dessine une bande sombre sous les réglages.
    holder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(METRICS.pad)

    editors: dict[str, SettingEditor] = {}
    for s in settings:
        ed = SettingEditor(s)
        ed.changed.connect(on_change)
        editors[s.name] = ed
        layout.addWidget(ed)

    if not settings:
        empty = QLabel("Ce mod n'a aucun réglage modifiable.")
        empty.setObjectName("Dim")
        layout.addWidget(empty)

    layout.addStretch(1)
    return holder, editors


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background:{PALETTE.border}; max-height:1px; border:none;")
    return line


class ModDocPanel(QWidget):
    """Notice d'un mod : ce qu'il fait, comment s'en servir, ce qu'il faut savoir.

    Les touches et commandes ne viennent PAS de la notice mais du code du mod, relu à
    chaque affichage. Une notice peut vieillir ; le code, non. Ce projet en a un
    exemple : le README de FEInfiniteCore annonce un délai que le code contredit.
    """

    def __init__(self, mod, doc, parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(METRICS.pad)

        title = QLabel(mod.name.replace("ue4ss-", ""))
        title.setObjectName("PageTitle")
        root.addWidget(title)

        if doc.restricted:
            root.addWidget(Badge("MODE DÉVELOPPEUR", "warn"))

        if doc.documented:
            summary = QLabel(doc.summary)
            summary.setWordWrap(True)
            root.addWidget(summary)
        else:
            missing = QLabel("Aucune notice disponible pour ce mod.")
            missing.setObjectName("Dim")
            root.addWidget(missing)

        if doc.usage:
            root.addWidget(self._section("Comment s'en servir"))
            for step in doc.usage:
                root.addWidget(self._bullet(step, "•"))

        # Relu dans le code du mod, pas dans la notice.
        if mod.keybinds:
            root.addWidget(self._section("Touches"))
            root.addWidget(self._mono(", ".join(mod.keybinds)))
        if mod.commands:
            root.addWidget(self._section("Commandes console"))
            root.addWidget(self._mono(", ".join(mod.commands)))

        if doc.warnings:
            root.addWidget(self._section("À savoir"))
            for w in doc.warnings:
                item = self._bullet(w, "!")
                item.setStyleSheet(f"color:{PALETTE.warn};")
                root.addWidget(item)

        origin = {"notice": "Notice rédigée pour le launcher",
                  "readme": "Texte repris du README du mod",
                  "en-tête": "Texte repris de l'en-tête du mod",
                  "aucune": ""}.get(doc.source, "")
        if origin:
            src = QLabel(origin)
            src.setObjectName("Dim")
            root.addWidget(src)

        root.addStretch(1)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lbl.setContentsMargins(0, METRICS.pad_sm, 0, 0)
        return lbl

    @staticmethod
    def _bullet(text: str, marker: str) -> QLabel:
        lbl = QLabel(f"{marker}  {text}")
        lbl.setWordWrap(True)
        lbl.setContentsMargins(METRICS.pad_sm, 0, 0, 0)
        return lbl

    @staticmethod
    def _mono(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("Mono")
        lbl.setWordWrap(True)
        lbl.setContentsMargins(METRICS.pad_sm, 0, 0, 0)
        lbl.setStyleSheet(f"font-family:{METRICS.mono}; color:{PALETTE.accent};")
        return lbl
