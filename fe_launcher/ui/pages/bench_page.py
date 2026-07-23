"""Banc d'essai : conduire une campagne de mesure HIT/MISS sans se raconter d'histoires.

Pourquoi cette page existe
--------------------------
La chasse aux glitchs de Fading Echo est une campagne de mesure, pas un bricolage : on
fait varier UN paramètre (le délai grab→void du mod `ue4ss-FEInfiniteCore`), on note HIT
ou MISS 15 à 20 fois par palier, et on compare les taux. Cette grille se tient
aujourd'hui à la main, sur du papier. Cette page la remplace — et surtout, elle remplace
la lecture à l'œil de cette grille, qui est l'endroit où le papier trompe.

Ce que la page refuse de faire
------------------------------
Elle n'affiche NULLE PART un « meilleur palier » sorti du classement des taux. Sur
15 essais, 3 réussites (20 %) et 6 réussites (40 %) semblent doubler la performance ;
Fisher donne p ≈ 0,43, c'est-à-dire du bruit pur. Un outil qui pointerait « 40 % =
gagnant » entraînerait l'utilisateur à croire du bruit plus vite qu'il ne le ferait à la
main — il serait pire que le papier. Le seul énoncé de conclusion affiché est
`Campaign.verdict()`, qui dit « aucun écart significatif, il faut plus d'essais » quand
c'est le cas, et chaque taux du tableau est accompagné de son intervalle de confiance.

Aucun calcul n'est refait ici : Wilson, Fisher, le verdict et la grille exportable
vivent dans `core.bench`. Cette page est une surface de saisie et d'affichage.

Le framerate est mis en avant, et ce n'est pas décoratif
--------------------------------------------------------
La cause racine du glitch est une course d'UNE frame. Un délai en millisecondes ne
signifie donc rien sans le framerate associé : 300 ms à 60 fps (18 frames) et 300 ms à
144 fps (43 frames) ne testent pas la même chose. Une campagne sans framerate verrouillé
produit des chiffres qu'on ne peut comparer ni entre paliers si le fps a dérivé, ni avec
la session de quelqu'un d'autre. La page l'affiche donc comme un avertissement visible,
pas comme une note de bas de page.

Saisie au clavier
-----------------
Entre deux essais, l'utilisateur a une main sur le clavier et l'autre sur la manette :
H = hit, M = miss, J = jeter, Ctrl+Z = annuler. Ces raccourcis sont implémentés dans
`keyPressEvent` plutôt qu'avec des `QShortcut` : un raccourci à une seule lettre vole le
caractère aux champs de texte de la page (on ne pourrait plus taper « Hall » dans le nom
de la campagne). En passant par la propagation normale des événements, un champ de
saisie qui a le focus consomme la touche, et la page ne la reçoit que lorsque le focus
est ailleurs — ce qui est exactement le comportement voulu.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core import luaconf
from ...core.bench import Campaign, Outcome
from ..main_window import Page
from ..theme import METRICS, PALETTE
from ..widgets import Badge, Card, ComboBox, PageHeader, separator

#: Mod piloté par défaut, et constante qu'il expose. Ce sont les valeurs de départ ;
#: la campagne chargée depuis un JSON peut en désigner d'autres.
DEFAULT_MOD = "ue4ss-FEInfiniteCore"
DEFAULT_PARAM = "VOID_DELAY_MS"

#: Framerates proposés. « Non verrouillé » est en tête pour être l'état par défaut
#: honnête : on ne veut pas qu'un 60 fps présélectionné laisse croire que le jeu y est
#: réellement bridé alors que personne n'a rien verrouillé.
FPS_CHOICES: tuple[tuple[str, float], ...] = (
    ("Non verrouillé", 0.0),
    ("30 fps", 30.0),
    ("60 fps", 60.0),
    ("120 fps", 120.0),
    ("144 fps", 144.0),
    ("165 fps", 165.0),
    ("240 fps", 240.0),
)

_SPLIT_RE = re.compile(r"[^\d.,]+")


def parse_steps(text: str) -> list[float]:
    """« 150/300, 500 800 » → [150.0, 300.0, 500.0, 800.0].

    Tolérante par construction : l'utilisateur note ses paliers comme il les dit à voix
    haute, avec des barres obliques, des virgules ou des espaces. Refuser une saisie
    pour un séparateur inattendu, au milieu d'une session de mesure, serait absurde.
    Les doublons sont écrasés et la liste triée : deux fois le même palier donnerait
    deux lignes de tableau pour un seul `Bucket`.
    """
    out: list[float] = []
    for chunk in _SPLIT_RE.split(text.replace(",", " ")):
        if not chunk:
            continue
        try:
            out.append(float(chunk))
        except ValueError:
            continue
    return sorted(dict.fromkeys(out))


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^\w-]+", "-", name.strip(), flags=re.UNICODE).strip("-")
    return (cleaned or "campagne")[:60]


class BenchPage(Page):
    """Conduite d'une campagne de mesure, de la saisie au verdict."""

    title = "Banc d'essai"
    icon = "◎"

    def __init__(self, ctx, parent: QWidget | None = None):
        super().__init__(ctx, parent)
        self.campaign = Campaign(name="Campagne sans titre")
        #: Palier en cours de mesure. `None` tant qu'aucun palier n'est défini.
        self.current: float | None = None

        # Sans focus sur la page elle-même, aucun événement clavier ne lui parvient et
        # les raccourcis de saisie seraient morts dès qu'aucun bouton n'a le focus.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        self.header = PageHeader(
            "Banc d'essai",
            "Faire varier un paramètre, compter les réussites, et ne conclure "
            "que lorsque l'écart est réel.")
        root.addWidget(self.header)

        self.load_btn = QPushButton("Charger…")
        self.load_btn.clicked.connect(self._load)
        self.save_btn = QPushButton("Enregistrer")
        self.save_btn.clicked.connect(self._save)
        self.copy_btn = QPushButton("Copier la grille")
        self.copy_btn.setToolTip(
            "Copie la grille ASCII de la campagne dans le presse-papier — "
            "c'est le format que la communauté s'échange.")
        self.copy_btn.clicked.connect(self._copy_grid)
        for b in (self.load_btn, self.save_btn, self.copy_btn):
            self.header.add_action(b)

        root.addWidget(self._build_setup_card())
        root.addWidget(self._build_record_card())
        root.addWidget(self._build_table_card())
        root.addWidget(self._build_verdict_card())
        root.addStretch(1)

        self._sync_from_fields()
        self.refresh()

    # --- construction ------------------------------------------------------------

    def _build_setup_card(self) -> Card:
        card = Card()
        title = QLabel("Configuration de la campagne")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(METRICS.pad)
        grid.setVerticalSpacing(METRICS.pad_sm)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.name_edit = QLineEdit(self.campaign.name)
        self.name_edit.editingFinished.connect(self._sync_from_fields)
        grid.addWidget(QLabel("Nom"), 0, 0)
        grid.addWidget(self.name_edit, 0, 1)

        self.setup_edit = QLineEdit()
        self.setup_edit.setPlaceholderText("Zone, forme, type de core — ex. « Quarry, Human One, core bleu »")
        self.setup_edit.setToolTip(
            "Décrit les conditions du test. Deux campagnes faites dans des zones "
            "différentes ne se comparent pas : c'est ici qu'on note pourquoi.")
        self.setup_edit.editingFinished.connect(self._sync_from_fields)
        grid.addWidget(QLabel("Setup"), 0, 2)
        grid.addWidget(self.setup_edit, 0, 3)

        self.steps_edit = QLineEdit("150 / 300 / 500 / 800")
        self.steps_edit.setPlaceholderText("Délais à tester, en ms — ex. 150 / 300 / 500 / 800")
        self.steps_edit.editingFinished.connect(self._sync_from_fields)
        grid.addWidget(QLabel("Paliers (ms)"), 1, 0)
        grid.addWidget(self.steps_edit, 1, 1)

        self.target_spin = QSpinBox()
        self.target_spin.setRange(1, 500)
        self.target_spin.setValue(15)
        self.target_spin.setSuffix(" essais / palier")
        self.target_spin.setToolTip(
            "Objectif d'essais par palier. En dessous de 15, l'intervalle de "
            "confiance est si large qu'aucun écart ne peut ressortir.")
        self.target_spin.valueChanged.connect(lambda _: self.refresh())
        grid.addWidget(QLabel("Objectif"), 1, 2)
        grid.addWidget(self.target_spin, 1, 3)

        self.fps_combo = ComboBox()
        for label, value in FPS_CHOICES:
            self.fps_combo.addItem(label, value)
        self.fps_combo.currentIndexChanged.connect(lambda _: self._sync_from_fields())
        grid.addWidget(QLabel("Framerate"), 2, 0)
        grid.addWidget(self.fps_combo, 2, 1)

        self.build_edit = QLineEdit()
        self.build_edit.setPlaceholderText("Build du jeu — ex. 1.0.4")
        self.build_edit.editingFinished.connect(self._sync_from_fields)
        grid.addWidget(QLabel("Build"), 2, 2)
        grid.addWidget(self.build_edit, 2, 3)

        holder = QWidget()
        holder.setLayout(grid)
        card.body.addWidget(holder)

        # L'avertissement framerate n'est pas une note de bas de page : sans lui, la
        # campagne produit des chiffres qui ne se comparent à rien.
        self.fps_notice = QLabel()
        self.fps_notice.setWordWrap(True)
        card.body.addWidget(self.fps_notice)
        return card

    def _build_record_card(self) -> Card:
        card = Card()

        head = QHBoxLayout()
        title = QLabel("Saisie des essais")
        title.setObjectName("SectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(QLabel("Palier courant"))
        self.step_combo = ComboBox()
        self.step_combo.setMinimumWidth(150)
        self.step_combo.currentIndexChanged.connect(self._step_changed)
        head.addWidget(self.step_combo)
        holder = QWidget()
        holder.setLayout(head)
        card.body.addWidget(holder)

        # État du pilotage du mod. La page reste pleinement utilisable sans le mod :
        # on mesure alors un délai réglé à la main, et c'est un usage légitime.
        self.mod_row = QHBoxLayout()
        self.mod_badge = Badge("—", "muted")
        self.mod_row.addWidget(self.mod_badge)
        # L'explication va sur SA PROPRE ligne, sous les contrôles. Repliée à l'intérieur
        # d'une rangée horizontale, elle se retrouve écrasée par ses voisins de hauteur
        # fixe (case à cocher, bouton) et le texte est tronqué à l'affichage.
        self.mod_label = QLabel()
        self.mod_label.setObjectName("Dim")
        self.mod_label.setWordWrap(True)
        self.mod_row.addStretch(1)
        self.autopush = QCheckBox("Écrire le palier dans le mod")
        self.autopush.setToolTip(
            "À chaque changement de palier, réécrit la constante du mod et journalise "
            "la modification (annulable depuis la page Désinstallation).")
        self.autopush.setChecked(True)
        self.mod_row.addWidget(self.autopush)
        self.push_btn = QPushButton("Appliquer maintenant")
        self.push_btn.clicked.connect(lambda: self._push_to_mod(self.current, manual=True))
        self.mod_row.addWidget(self.push_btn)
        mod_holder = QWidget()
        mod_holder.setLayout(self.mod_row)
        card.body.addWidget(mod_holder)
        card.body.addWidget(self.mod_label)

        card.body.addWidget(separator())

        buttons = QHBoxLayout()
        buttons.setSpacing(METRICS.pad)

        self.hit_btn = QPushButton("HIT   (H)")
        self.hit_btn.setObjectName("Primary")
        self.hit_btn.setMinimumHeight(56)
        self.hit_btn.clicked.connect(lambda: self.record(Outcome.HIT))
        buttons.addWidget(self.hit_btn, 3)

        self.miss_btn = QPushButton("MISS   (M)")
        self.miss_btn.setMinimumHeight(56)
        self.miss_btn.clicked.connect(lambda: self.record(Outcome.MISS))
        buttons.addWidget(self.miss_btn, 3)

        self.void_btn = QPushButton("Essai à jeter   (J)")
        self.void_btn.setMinimumHeight(56)
        self.void_btn.setToolTip(
            "Départ sur un état sale, mauvaise manip, crash. L'essai est conservé "
            "dans le journal mais ne compte pas au dénominateur.")
        self.void_btn.clicked.connect(lambda: self.record(Outcome.VOID))
        buttons.addWidget(self.void_btn, 2)

        self.undo_btn = QPushButton("Annuler le dernier   (Ctrl+Z)")
        self.undo_btn.setMinimumHeight(56)
        self.undo_btn.clicked.connect(self.undo_last)
        buttons.addWidget(self.undo_btn, 2)

        btn_holder = QWidget()
        btn_holder.setLayout(buttons)
        card.body.addWidget(btn_holder)

        self.last_label = QLabel(
            "Au clavier : H = hit, M = miss, J = essai à jeter, Ctrl+Z = annuler. "
            "Les touches n'agissent que si le focus n'est pas dans un champ de saisie.")
        self.last_label.setObjectName("Dim")
        self.last_label.setWordWrap(True)
        card.body.addWidget(self.last_label)
        return card

    def _build_table_card(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        title = QLabel("Mesures")
        title.setObjectName("SectionTitle")
        row.addWidget(title)
        row.addStretch(1)
        self.total_label = QLabel()
        self.total_label.setObjectName("Dim")
        row.addWidget(self.total_label)
        holder = QWidget()
        holder.setLayout(row)
        card.body.addWidget(holder)

        cols = ["Palier", "Frames", "HIT", "n", "Taux", "IC 95 %", "Rejetés"]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        for i in range(len(cols)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        card.body.addWidget(self.table)

        # L'intervalle de confiance est la colonne qui empêche de lire le taux tout
        # seul : on le dit explicitement plutôt que d'espérer qu'il soit compris.
        hint = QLabel("Un taux se lit toujours avec son intervalle : « 40% [20% – 64%] » "
                      "veut dire qu'on ne sait pas encore grand-chose.")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        return card

    def _build_verdict_card(self) -> Card:
        card = Card()
        title = QLabel("Verdict")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)

        self.verdict_label = QLabel()
        self.verdict_label.setWordWrap(True)
        font = QFont()
        font.setPointSizeF(font.pointSizeF() + 1.5)
        self.verdict_label.setFont(font)
        card.body.addWidget(self.verdict_label)

        self.suggest_label = QLabel()
        self.suggest_label.setObjectName("Dim")
        self.suggest_label.setWordWrap(True)
        card.body.addWidget(self.suggest_label)
        return card

    # --- synchronisation champs ↔ campagne ---------------------------------------

    def _sync_from_fields(self) -> None:
        """Recopie les champs de configuration dans la campagne, puis réaffiche.

        Un palier retiré du champ disparaît du tableau — mais SEULEMENT s'il est vide.
        Un palier qui porte des essais est conservé quoi qu'il arrive : les essais sont
        de la donnée, pas de la configuration, et une faute de frappe dans la liste ne
        doit pas effacer vingt mesures. Ils réapparaissent donc dans le champ au
        rafraîchissement suivant.
        """
        self.campaign.name = self.name_edit.text().strip() or "Campagne sans titre"
        self.campaign.setup = self.setup_edit.text().strip()
        self.campaign.game_build = self.build_edit.text().strip()
        self.campaign.fps_lock = float(self.fps_combo.currentData() or 0.0)

        wanted = parse_steps(self.steps_edit.text())
        self.campaign.buckets = [b for b in self.campaign.buckets
                                 if b.trials or b.value in wanted]
        for value in wanted:
            self.campaign.bucket(value)
        self.steps_edit.setText(" / ".join(f"{b.value:g}" for b in self.campaign.buckets))
        self.refresh()

    def _fill_fields_from_campaign(self) -> None:
        """Sens inverse, après un chargement de campagne depuis le disque."""
        self.name_edit.setText(self.campaign.name)
        self.setup_edit.setText(self.campaign.setup)
        self.build_edit.setText(self.campaign.game_build)
        index = self.fps_combo.findData(self.campaign.fps_lock)
        if index < 0:
            # Framerate exotique enregistré ailleurs : on l'ajoute plutôt que de le
            # perdre en retombant sur « non verrouillé », ce qui serait un mensonge.
            self.fps_combo.addItem(f"{self.campaign.fps_lock:g} fps", self.campaign.fps_lock)
            index = self.fps_combo.count() - 1
        self.fps_combo.setCurrentIndex(index)
        self.steps_edit.setText(" / ".join(f"{b.value:g}" for b in self.campaign.buckets))

    # --- rendu -------------------------------------------------------------------

    def refresh(self) -> None:
        self._render_fps_notice()
        self._render_steps()
        self._render_mod_state()
        self._render_table()
        self._render_verdict()

    def _render_fps_notice(self) -> None:
        if self.campaign.fps_lock > 0:
            fps = self.campaign.fps_lock
            self.fps_notice.setText(
                f"Framerate verrouillé à {fps:g} fps : une frame dure "
                f"{1000 / fps:.1f} ms, et les délais sont convertis en frames dans le "
                "tableau. Les mesures resteront comparables entre sessions.")
            self.fps_notice.setStyleSheet(
                f"color:{PALETTE.text_dim}; background:transparent; padding:6px 0;")
            return
        self.fps_notice.setText(
            "⚠  Framerate non verrouillé — délais non comparables entre sessions. "
            "La cause du glitch est une course d'UNE frame : 300 ms à 60 fps valent "
            "18 frames, 300 ms à 144 fps en valent 43. Sans framerate fixé, deux "
            "paliers peuvent différer parce que le jeu a ralenti, pas parce que le "
            "délai a changé. Bridez le jeu avant de mesurer.")
        self.fps_notice.setStyleSheet(
            f"color:{PALETTE.warn}; background:{PALETTE.warn_bg};"
            f"border:1px solid {PALETTE.warn}44; border-radius:{METRICS.radius_sm}px;"
            f"padding:{METRICS.pad_sm}px;")

    def _render_steps(self) -> None:
        values = [b.value for b in self.campaign.buckets]
        previous = self.current
        self.step_combo.blockSignals(True)
        self.step_combo.clear()
        for value in values:
            self.step_combo.addItem(f"{value:g} ms", value)
        if values:
            self.current = previous if previous in values else values[0]
            self.step_combo.setCurrentIndex(values.index(self.current))
        else:
            self.current = None
        self.step_combo.blockSignals(False)

        has_step = self.current is not None
        for btn in (self.hit_btn, self.miss_btn, self.void_btn, self.undo_btn):
            btn.setEnabled(has_step)
        if not has_step:
            self.last_label.setText(
                "Saisissez au moins un palier de délai pour commencer à mesurer.")

    def _render_mod_state(self) -> None:
        mod = self._mod()
        if mod is None or mod.script is None:
            self.mod_badge.set_kind("SAISIE MANUELLE", "muted")
            self.mod_label.setText(
                f"Le mod {self.campaign.mod} n'est pas installé. La campagne reste "
                "utilisable : réglez le délai vous-même dans le jeu et notez les "
                "essais ici — rien n'est bloqué.")
            self.autopush.setEnabled(False)
            self.push_btn.setEnabled(False)
            return

        setting = luaconf.read(mod.script, self.campaign.parameter)
        if setting is None:
            self.mod_badge.set_kind("CONSTANTE ABSENTE", "warn")
            self.mod_label.setText(
                f"{mod.name} est installé mais n'expose pas « {self.campaign.parameter} » : "
                "sa version diffère de celle attendue. Saisie manuelle uniquement.")
            self.autopush.setEnabled(False)
            self.push_btn.setEnabled(False)
            return

        text = f"{mod.name} · {self.campaign.parameter} = {setting.raw_value}"
        if self.current is not None and setting.value != self.current:
            # Le mod et le palier courant divergent : le dire, sinon l'utilisateur
            # mesure un délai en croyant en mesurer un autre — le pire cas possible
            # pour une campagne, parce que rien ne le signale dans les résultats.
            self.mod_badge.set_kind("À APPLIQUER", "warn")
            text += (f"  ≠ palier courant ({self.current:g} ms) — "
                     "cliquez « Appliquer maintenant ».")
        else:
            self.mod_badge.set_kind("MOD PILOTÉ", "ok")
        self.mod_label.setText(text)
        self.autopush.setEnabled(True)
        self.push_btn.setEnabled(self.current is not None)

    def _render_table(self) -> None:
        fps = self.campaign.fps_lock
        buckets = self.campaign.buckets
        self.table.setRowCount(len(buckets))
        for row, b in enumerate(buckets):
            is_current = self.current is not None and b.value == self.current
            cells = [
                ("▶ " if is_current else "   ") + f"{b.value:g} ms",
                f"{b.frames(fps):.1f}" if fps else "—",
                str(b.hits),
                str(b.n),
                f"{b.rate:.0%}" if b.n else "—",
                str(b.ci) if b.n else "—",
                str(b.voided) if b.voided else "",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col:  # les colonnes chiffrées se lisent en colonne, alignées à droite
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                    item.setFont(QFont(METRICS.mono.split(",")[0].strip("' ")))
                if is_current:
                    item.setBackground(QColor(PALETTE.surface_alt))
                    item.setForeground(QColor(PALETTE.accent))
                self.table.setItem(row, col, item)

        # Le tableau ne défile pas sur lui-même : la page entière est déjà défilante,
        # deux barres imbriquées rendraient la lecture pénible.
        rows_h = self.table.horizontalHeader().sizeHint().height()
        rows_h += sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        rows_h += 2 * self.table.frameWidth() + 4
        self.table.setFixedHeight(max(rows_h, 90))

        counted = self.campaign.total_trials
        voided = sum(b.voided for b in buckets)
        text = f"{counted} essai(s) compté(s)"
        if voided:
            text += f" · {voided} rejeté(s)"
        self.total_label.setText(text)

    def _render_verdict(self) -> None:
        # Le verdict est le SEUL énoncé de conclusion de la page. Aucun « meilleur
        # palier » n'est affiché à côté : ce serait exactement le raccourci que le
        # module de mesure existe pour empêcher.
        self.verdict_label.setText(self.campaign.verdict())
        pool = [b for b in self.campaign.buckets if b.n]
        self.verdict_label.setStyleSheet(
            f"color:{PALETTE.text if len(pool) >= 2 else PALETTE.text_dim};")

        target = self.target_spin.value()
        nxt = self.campaign.suggest_next(target)
        if not self.campaign.buckets:
            self.suggest_label.setText(
                "Saisissez les délais à comparer dans « Paliers », séparés par des "
                "barres obliques ou des espaces.")
        elif nxt is None:
            self.suggest_label.setText(
                f"Tous les paliers atteignent l'objectif de {target} essais.")
        else:
            self.suggest_label.setText(
                f"Prochain palier conseillé : {nxt.value:g} ms "
                f"({nxt.n}/{target} essais) — on équilibre les effectifs plutôt que "
                "de finir un palier, pour qu'une campagne interrompue reste comparable.")

    # --- actions de mesure -------------------------------------------------------

    def record(self, outcome: Outcome) -> None:
        """Enregistre un essai sur le palier courant."""
        if self.current is None:
            return
        self.campaign.record(self.current, outcome)
        label = {Outcome.HIT: "HIT", Outcome.MISS: "MISS", Outcome.VOID: "rejeté"}[outcome]
        color = {Outcome.HIT: PALETTE.hit, Outcome.MISS: PALETTE.miss,
                 Outcome.VOID: PALETTE.voided}[outcome]
        bucket = self.campaign.bucket(self.current)
        self.last_label.setText(
            f"Dernier essai : {label} à {self.current:g} ms "
            f"— {bucket.hits}/{bucket.n} sur ce palier.")
        self.last_label.setStyleSheet(f"color:{color};")
        self.refresh()

    def undo_last(self) -> None:
        """Annule le dernier essai du palier courant."""
        if self.current is None:
            return
        removed = self.campaign.undo(self.current)
        if removed is None:
            self.last_label.setText(f"Aucun essai à annuler sur le palier {self.current:g} ms.")
        else:
            self.last_label.setText(
                f"Essai annulé ({removed.outcome.value}) sur le palier {self.current:g} ms.")
        self.last_label.setStyleSheet(f"color:{PALETTE.text_dim};")
        self.refresh()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — API Qt
        """Raccourcis de saisie. Ne reçoit l'événement que si aucun champ ne l'a pris."""
        key = event.key()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                self.undo_last()
                return
        elif key == Qt.Key.Key_H:
            self.record(Outcome.HIT)
            return
        elif key == Qt.Key.Key_M:
            self.record(Outcome.MISS)
            return
        elif key == Qt.Key.Key_J:
            self.record(Outcome.VOID)
            return
        super().keyPressEvent(event)

    # --- pilotage du mod ---------------------------------------------------------

    def _mod(self):
        return next((m for m in self.ctx.mods if m.name == self.campaign.mod), None)

    def _step_changed(self, index: int) -> None:
        if index < 0:
            return
        self.current = float(self.step_combo.itemData(index))
        if self.autopush.isChecked():
            self._push_to_mod(self.current)
        self.refresh()

    def _push_to_mod(self, value: float | None, *, manual: bool = False) -> None:
        """Écrit le palier dans la constante du mod, et le journalise.

        Journaliser une écriture de constante n'est pas de la paperasse : au bout de
        quarante paliers, le fichier du mod ne ressemble plus à ce que l'utilisateur y
        avait mis, et le journal est le seul moyen de revenir à sa valeur d'origine.
        """
        if value is None:
            return
        mod = self._mod()
        if mod is None or mod.script is None:
            return
        before = luaconf.read(mod.script, self.campaign.parameter)
        if before is None:
            return
        if before.value == value and not manual:
            return  # rien à écrire : évite de remplir le journal de doublons
        try:
            after = luaconf.write(mod.script, self.campaign.parameter, value)
        except (KeyError, luaconf.NotEditable, OSError) as exc:
            QMessageBox.warning(
                self, "Écriture impossible",
                f"Le palier n'a pas pu être écrit dans {mod.name} :\n\n{exc}\n\n"
                "La campagne reste utilisable en saisie manuelle.")
            return
        self.ctx.ledger.lua_set(
            mod.script, self.campaign.parameter, before.value, after.value,
            label=f"banc d'essai « {self.campaign.name} » : palier {value:g}",
            group=f"bench:{_slug(self.campaign.name)}")
        # Les mods sont relus pour que les autres pages voient la nouvelle valeur.
        self.ctx.refresh()

    # --- persistance et export ---------------------------------------------------

    @property
    def campaigns_dir(self) -> Path:
        return Path(self.ctx.data_dir) / "campaigns"

    def _save(self) -> None:
        self._sync_from_fields()
        path = self.campaigns_dir / f"{_slug(self.campaign.name)}.json"
        try:
            self.campaign.save(path)
        except OSError as exc:
            QMessageBox.warning(self, "Enregistrement impossible", str(exc))
            return
        self.last_label.setText(f"Campagne enregistrée dans {path}")
        self.last_label.setStyleSheet(f"color:{PALETTE.text_dim};")

    def _load(self) -> None:
        self.campaigns_dir.mkdir(parents=True, exist_ok=True)
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Charger une campagne", str(self.campaigns_dir),
            "Campagnes (*.json)")
        if chosen:
            self.load_file(Path(chosen))

    def load_file(self, path: Path) -> bool:
        """Charge une campagne depuis un fichier. Retourne False si elle est illisible."""
        try:
            self.campaign = Campaign.load(path)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(
                self, "Campagne illisible",
                f"{path.name} n'a pas pu être relu :\n\n{exc}")
            return False
        self.current = None
        self._fill_fields_from_campaign()
        self.refresh()
        return True

    def _copy_grid(self) -> None:
        grid = self.campaign.to_grid()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(grid)
        self.last_label.setText(
            "Grille copiée dans le presse-papier (verdict compris).")
        self.last_label.setStyleSheet(f"color:{PALETTE.text_dim};")
