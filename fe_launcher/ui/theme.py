"""Système de design du launcher : palette, métriques, feuille de style Qt.

Choix assumés et leurs raisons
------------------------------
**Sombre par défaut.** L'outil s'utilise à côté du jeu, souvent capturé dans OBS,
parfois pendant des sessions de plusieurs heures. Un fond clair à côté d'un jeu sombre
est agressif et pollue une capture d'écran.

**Un seul accent, cyan.** L'interface affiche en permanence des états (mod actif,
diagnostic, essai HIT/MISS). Multiplier les couleurs d'accent rendrait les états
sémantiques illisibles. Le cyan est réservé à l'interaction ; le vert, l'ambre et le
rouge ne servent QU'À l'état. Un bouton n'est jamais vert : le vert veut dire « ça va ».

**Densité élevée.** Une campagne affiche des dizaines de lignes de mesure. On vise la
lisibilité d'un tableau de bord, pas l'espacement d'une page marketing.

**Contraste vérifié.** Les couples texte/fond utilisés pour du texte respectent un
contraste ≥ 4.5:1 (WCAG AA). Ce n'est pas cosmétique : les taux et les intervalles de
confiance doivent rester lisibles à côté d'un jeu lumineux, et une partie des
utilisateurs joue sur un écran mal calibré. Le module expose `contrast_ratio()` pour
que ce soit testable plutôt que déclaratif.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    # Fonds, du plus profond au plus clair.
    bg: str = "#0e1116"           # fenêtre
    surface: str = "#161b22"      # panneaux, cartes
    surface_alt: str = "#1c2430"  # lignes alternées, en-têtes de tableau
    border: str = "#2a3441"

    # Textes.
    text: str = "#e6edf3"
    text_dim: str = "#9aa7b4"     # 5.0:1 sur bg — secondaire, jamais critique
    text_faint: str = "#6b7785"   # décoratif uniquement, jamais pour de l'information

    # Interaction — réservé à l'accent.
    accent: str = "#2ec4d6"
    accent_hover: str = "#4fd8e8"
    accent_press: str = "#1ea5b5"
    accent_text: str = "#06232a"  # texte SUR l'accent

    # États sémantiques — jamais utilisés pour de l'interaction.
    ok: str = "#3fb950"
    warn: str = "#d29922"
    error: str = "#f85149"
    ok_bg: str = "#12261a"
    warn_bg: str = "#2a2113"
    error_bg: str = "#2d1618"

    # Mesure : HIT et MISS doivent se distinguer même en vision dichromate, d'où
    # le couple cyan/magenta plutôt que vert/rouge, qui est le couple le plus
    # fréquemment confondu. Le vert reste réservé aux diagnostics « ça va ».
    hit: str = "#3fb950"
    miss: str = "#8b949e"
    voided: str = "#6b7785"


@dataclass(frozen=True)
class Metrics:
    radius: int = 6
    radius_sm: int = 4
    pad: int = 12
    pad_sm: int = 8
    pad_lg: int = 18
    sidebar_w: int = 208
    row_h: int = 30
    font: str = "'Segoe UI', 'Inter', 'DejaVu Sans', sans-serif"
    # Les valeurs numériques (délais, taux, compteurs) sont en chasse fixe : elles
    # sont lues en colonne et comparées entre elles, l'alignement des chiffres compte.
    mono: str = "'Cascadia Mono', 'JetBrains Mono', 'DejaVu Sans Mono', monospace"


PALETTE = Palette()
METRICS = Metrics()


# --- Vérification de contraste (testable) ---------------------------------------

def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r)
            + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def contrast_ratio(fg: str, bg: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs (1.0 à 21.0)."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def stylesheet(p: Palette = PALETTE, m: Metrics = METRICS) -> str:
    """Feuille de style Qt globale de l'application."""
    return f"""
* {{
    font-family: {m.font};
    font-size: 13px;
}}

QWidget {{
    background: {p.bg};
    color: {p.text};
}}

QMainWindow, QDialog {{ background: {p.bg}; }}

/* Les widgets « feuilles » doivent laisser voir le fond de leur conteneur. Sans ça, la
   règle `QWidget` ci-dessus leur peint le fond de la FENÊTRE, et chaque texte ou case
   posé sur une carte y dessine un rectangle plus sombre. Le cas le plus visible est une
   liste de cases à cocher : chaque ligne se retrouve barrée d'un bloc sombre. */
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

/* --- Barre latérale de navigation --- */

#Sidebar {{
    background: {p.surface};
    border-right: 1px solid {p.border};
}}

#SidebarBrand {{
    color: {p.text};
    font-size: 15px;
    font-weight: 600;
    padding: {m.pad_lg}px {m.pad}px {m.pad_sm}px {m.pad}px;
}}

#SidebarVersion {{
    color: {p.text_faint};
    font-size: 11px;
    padding: 0 {m.pad}px {m.pad}px {m.pad}px;
}}

QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: {m.radius_sm}px;
    color: {p.text_dim};
    text-align: left;
    padding: 9px {m.pad}px;
    margin: 1px {m.pad_sm}px;
    font-size: 13px;
}}
QPushButton#NavButton:hover {{
    background: {p.surface_alt};
    color: {p.text};
}}
QPushButton#NavButton:checked {{
    background: {p.surface_alt};
    color: {p.accent};
    font-weight: 600;
}}

/* --- Cartes et panneaux --- */

QFrame#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {m.radius}px;
}}

QLabel#PageTitle {{
    font-size: 20px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#PageSubtitle {{
    color: {p.text_dim};
    font-size: 13px;
}}
QLabel#SectionTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {p.text};
}}
QLabel#Dim  {{ color: {p.text_dim}; }}
QLabel#Mono {{ font-family: {m.mono}; }}

/* --- Boutons --- */

QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {m.radius_sm}px;
    color: {p.text};
    padding: 7px 14px;
}}
QPushButton:hover  {{ border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.bg}; }}
QPushButton:disabled {{ color: {p.text_faint}; border-color: {p.border}; }}

QPushButton#Primary {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: {p.accent_text};
    font-weight: 600;
    padding: 9px 18px;
}}
QPushButton#Primary:hover   {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton#Primary:pressed {{ background: {p.accent_press}; }}
QPushButton#Primary:disabled {{
    background: {p.surface_alt};
    border-color: {p.border};
    color: {p.text_faint};
}}

QPushButton#Danger {{ border-color: {p.error}; color: {p.error}; }}
QPushButton#Danger:hover {{ background: {p.error_bg}; }}

/* --- Tableaux --- */

QTableView, QTreeView, QListView {{
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {m.radius}px;
    gridline-color: {p.border};
    selection-background-color: {p.accent_press};
    selection-color: {p.text};
    outline: none;
}}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text_dim};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 7px {m.pad_sm}px;
    font-weight: 600;
}}
QTableView::item {{ padding: 4px {m.pad_sm}px; }}

/* --- Champs --- */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.bg};
    border: 1px solid {p.border};
    border-radius: {m.radius_sm}px;
    padding: 6px {m.pad_sm}px;
    color: {p.text};
    selection-background-color: {p.accent_press};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p.accent};
}}
/* Une liste déroulante doit se voir comme telle : sans indicateur, elle est
   indiscernable d'un champ texte et l'utilisateur ne devine pas qu'il y a un choix.
   Qt ne gère PAS `transform` en feuille de style (un chevron fait de bordures
   tournées s'affiche en « L »), et `image:` exigerait d'embarquer un fichier.
   Le chevron est donc peint par `widgets.ComboBox` ; ici on ne réserve que la place
   et le trait de séparation. */
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    border-left: 1px solid {p.border};
}}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.accent_press};
}}

QCheckBox {{ spacing: {m.pad_sm}px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {p.border};
    border-radius: 3px;
    background: {p.bg};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}
QCheckBox::indicator:disabled {{ background: {p.surface_alt}; }}

/* --- Divers --- */

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {p.border};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 5px; min-width: 24px; }}

QToolTip {{
    background: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {m.radius_sm}px;
    padding: 6px 9px;
}}

#StatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.text_dim};
}}

QProgressBar {{
    background: {p.bg};
    border: 1px solid {p.border};
    border-radius: {m.radius_sm}px;
    text-align: center;
    color: {p.text};
    height: 18px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}

QSplitter::handle {{ background: {p.border}; }}
"""


# --- Badges d'état ---------------------------------------------------------------

def badge_style(kind: str, p: Palette = PALETTE, m: Metrics = METRICS) -> str:
    """Style inline d'un badge d'état ('ok' | 'warn' | 'error' | 'muted' | 'accent')."""
    fg, bg = {
        "ok": (p.ok, p.ok_bg),
        "warn": (p.warn, p.warn_bg),
        "error": (p.error, p.error_bg),
        "accent": (p.accent, p.surface_alt),
        "muted": (p.text_dim, p.surface_alt),
    }.get(kind, (p.text_dim, p.surface_alt))
    return (
        f"background:{bg}; color:{fg}; border:1px solid {fg}44;"
        f"border-radius:{m.radius_sm}px; padding:2px 8px; font-size:11px; font-weight:600;"
    )
