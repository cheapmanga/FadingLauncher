"""Système de design du launcher : palette, métriques, feuille de style Qt.

Choix assumés et leurs raisons
------------------------------
**Sombre par défaut.** L'outil s'utilise à côté du jeu, souvent capturé dans OBS,
parfois pendant des sessions de plusieurs heures. Un fond clair à côté d'un jeu sombre
est agressif et pollue une capture d'écran.

**Un accent d'interaction, cyan — le core d'eau du jeu.** L'interface affiche en
permanence des états (mod actif, diagnostic, essai HIT/MISS) : l'accent cyan est réservé
à l'INTERACTION, et le vert/ambre/rouge QU'À l'état sémantique. Un bouton n'est jamais
vert : le vert veut dire « ça va ». Les couleurs des cinq cores (eau, lave, déchet,
corruption, énergie) forment, elles, l'identité Fading Echo : elles servent de touches
DÉCORATIVES (bannière, liserés, badges d'élément), jamais à coder un état.

**Atmosphère, pas platitude.** Fonds bleu-nuit dégradés (indigo → noir profond) sur la
barre latérale et les en-têtes, bordures qui s'illuminent à l'accent : un look de
launcher fanmade autour du jeu, pas un tableur gris.

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
    # Fonds, du plus profond au plus clair. Teintés bleu-nuit plutôt que gris neutre :
    # le monde de Fading Echo est éthéré, pas terne. Ces valeurs servent aussi de bornes
    # aux dégradés atmosphériques posés sur la barre latérale et les en-têtes.
    bg: str = "#080b11"           # fenêtre
    bg_deep: str = "#05070b"      # borne basse des dégradés
    indigo: str = "#0f1830"       # borne haute des dégradés (nuit indigo)
    surface: str = "#111823"      # panneaux, cartes
    surface_alt: str = "#1a2533"  # lignes alternées, en-têtes de tableau, tuiles
    border: str = "#26333f"
    border_glow: str = "#2ec4d6"  # bordure d'emphase, teinte accent

    # Textes.
    text: str = "#e9f1f8"
    text_dim: str = "#98a7b6"     # secondaire, jamais critique
    text_faint: str = "#66727f"   # décoratif uniquement, jamais pour de l'information

    # Interaction — l'accent signature, le core d'eau du jeu.
    accent: str = "#33cfe0"
    accent_hover: str = "#5ce2f1"
    accent_press: str = "#1fa7b8"
    accent_text: str = "#03212a"  # texte SUR l'accent

    # États sémantiques — jamais utilisés pour de l'interaction.
    ok: str = "#46c95a"
    warn: str = "#e0a62b"
    error: str = "#fb5a52"
    ok_bg: str = "#0f2a1b"
    warn_bg: str = "#2c2412"
    error_bg: str = "#2f1719"

    # --- Cores élémentaires de Fading Echo ---
    # L'identité visuelle du jeu. Servent de touches décoratives (bannière, accents de
    # cartes, badges d'éléments) pour casser la monotonie — jamais pour un état sémantique.
    water: str = "#33cfe0"
    lava: str = "#ff7a45"
    waste: str = "#b6e14b"
    corruption: str = "#b072ff"
    power: str = "#ffd24a"

    # Mesure : HIT et MISS doivent se distinguer même en vision dichromate. Le vert
    # reste réservé aux diagnostics « ça va ».
    hit: str = "#46c95a"
    miss: str = "#8b98a6"
    voided: str = "#66727f"

    @property
    def elements(self) -> tuple[str, ...]:
        """Les cinq cores, dans l'ordre du jeu — pour un liseré arc-en-ciel, etc."""
        return (self.water, self.lava, self.waste, self.corruption, self.power)


@dataclass(frozen=True)
class Metrics:
    radius: int = 6
    radius_sm: int = 4
    # Espacements partagés par TOUTE l'interface (marges de cartes, écarts de listes,
    # rythme des pages). Montés d'un cran — l'ancien jeu (8/12/18) tassait le contenu au
    # point d'être indigeste. Un seul endroit à régler, tous les écrans respirent.
    pad: int = 16
    pad_sm: int = 10
    pad_lg: int = 26
    sidebar_w: int = 232
    row_h: int = 34
    font: str = "'Segoe UI', 'Inter', 'DejaVu Sans', sans-serif"
    # Les valeurs numériques (délais, taux, compteurs) sont en chasse fixe : elles
    # sont lues en colonne et comparées entre elles, l'alignement des chiffres compte.
    mono: str = "'Cascadia Mono', 'JetBrains Mono', 'DejaVu Sans Mono', monospace"


PALETTE = Palette()
METRICS = Metrics()


def rgba(hex_color: str, alpha: int) -> str:
    """`"#33cfe0", 40` -> `"rgba(51, 207, 224, 40)"` — pour des fonds teintés translucides."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def element_button_qss(hex_color: str) -> str:
    """Feuille de style d'un bouton plein dans la couleur d'un core élémentaire.

    Colorer les boutons « Charger » de chaque carte, pas juste un liseré : c'est ce qui
    rend la grille VIVE. Le texte reste sombre pour tenir sur une couleur lumineuse.
    """
    return (
        f"QPushButton {{ background: {hex_color}; color: #04181d; border: none;"
        f" border-radius: {METRICS.radius_sm}px; padding: 9px 16px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: {rgba(hex_color, 230)}; }}"
        f"QPushButton:disabled {{ background: {rgba(hex_color, 70)}; color: {rgba(hex_color, 130)}; }}")


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

/* Fond de fenêtre : un dégradé nuit très sombre plutôt qu'un aplat, pour donner de la
   profondeur sans jamais concurrencer le contenu. */
QMainWindow, QDialog {{
    background: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
        stop:0 {p.indigo}, stop:0.55 {p.bg}, stop:1 {p.bg_deep});
}}

/* Les widgets « feuilles » doivent laisser voir le fond de leur conteneur. Sans ça, la
   règle `QWidget` ci-dessus leur peint le fond de la FENÊTRE, et chaque texte ou case
   posé sur une carte y dessine un rectangle plus sombre. Le cas le plus visible est une
   liste de cases à cocher : chaque ligne se retrouve barrée d'un bloc sombre. */
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}

/* --- Barre latérale de navigation --- */

#Sidebar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p.indigo}, stop:0.5 {p.surface}, stop:1 {p.bg_deep});
    border-right: 1px solid {p.border};
}}

#SidebarBrand {{
    color: {p.text};
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 2px;
    padding: {m.pad}px 0 2px 0;
}}
#SidebarBrandSub {{
    color: {p.accent};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 2px;
    padding: 0 {m.pad}px {m.pad_sm}px {m.pad}px;
}}
#SidebarArt {{
    /* liseré des cinq cores sous la bannière : l'identité du jeu en une bande fine. */
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p.water}, stop:0.25 {p.lava}, stop:0.5 {p.waste},
        stop:0.75 {p.corruption}, stop:1 {p.power});
    min-height: 2px; max-height: 2px;
    margin: 0 {m.pad}px {m.pad_sm}px {m.pad}px;
    border-radius: 1px;
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
    padding: 11px {m.pad}px;
    margin: 2px {m.pad_sm}px;
    font-size: 13px;
}}
QPushButton#NavButton:hover {{
    background: {p.surface_alt};
    color: {p.text};
}}
QPushButton#NavButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p.accent_press}, stop:0.05 {p.surface_alt}, stop:1 {p.surface_alt});
    border-left: 3px solid {p.accent};
    padding-left: {m.pad_sm}px;
    color: {p.accent};
    font-weight: 600;
}}

/* --- Cartes et panneaux --- */

QFrame#Card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {p.surface_alt}, stop:0.12 {p.surface}, stop:1 {p.surface});
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
    padding: 9px 16px;
}}
QPushButton:hover  {{ border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.bg}; }}
QPushButton:disabled {{ color: {p.text_faint}; border-color: {p.border}; }}

QPushButton#Primary {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: {p.accent_text};
    font-weight: 600;
    padding: 11px 20px;
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
QTableView::item {{ padding: 7px {m.pad_sm}px; }}

/* --- Champs --- */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.bg};
    border: 1px solid {p.border};
    border-radius: {m.radius_sm}px;
    padding: 9px {m.pad_sm}px;
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
