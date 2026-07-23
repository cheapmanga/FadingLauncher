"""Fenêtre principale : barre latérale, pages, et tableau de bord.

Le tableau de bord est l'écran d'accueil parce que l'état de l'installation conditionne
tout le reste. Sur ce jeu en particulier, un utilisateur du jeu complet a de bonnes
chances d'avoir UE4SS cassé sans le savoir — le dossier d'installation contient un
caractère grec qui fait mourir UE4SS au démarrage. Ouvrir sur la liste des mods
laisserait cocher des cases pendant dix minutes avant de découvrir qu'aucune n'a d'effet.

Les pages sont enregistrées par `register_page()` : chacune est un widget autonome qui
reçoit l'`AppContext` et se rafraîchit sur son signal `changed`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import doctor, logs
from ..core.doctor import Level
from ..core.launch import LaunchMode, is_running, launch
from ..core.logs import LogReport
from ..core.mods import ModState
from .context import AppContext
from .theme import METRICS, PALETTE
from .widgets import Badge, Card, PageHeader, separator

_LEVEL_KIND = {Level.OK: "ok", Level.WARN: "warn", Level.ERROR: "error"}


def scrollable(widget: QWidget) -> QScrollArea:
    """Enveloppe une page dans une zone défilante.

    Systématique : les pages affichent des listes de longueur imprévisible (20 mods,
    N diagnostics, une campagne de 40 paliers). Une page non défilante tronque son
    contenu sans le dire, ce qui est le pire des comportements.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area


class Page(QWidget):
    """Base des pages : reçoit le contexte et se rebranche sur ses changements."""

    title = "Page"
    subtitle = ""
    icon = ""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.changed.connect(self.refresh)

    def refresh(self) -> None:
        """Appelé quand l'état disque a changé. À surcharger."""


class LogReviewDialog(QDialog):
    """Résumé de la dernière session de jeu, lu dans UE4SS.log à sa fermeture.

    Pourquoi ce dialogue existe
    ---------------------------
    Le mode d'échec dominant de ce jeu est le SILENCE : UE4SS meurt dans un log que
    personne n'ouvre, un mod « actif » n'a jamais démarré. Proposer ce résumé juste après
    la partie est le seul moment où l'utilisateur pense encore à regarder — plus tard, le
    fichier aura été écrasé par le lancement suivant (d'où le bouton d'archivage).

    Le dialogue relaie `logs.explain`, la liste des mods démarrés et les erreurs (en
    rouge). Quand il n'y a pas de log du tout (`report.exists` faux — UE4SS absent, ou jeu
    jamais lancé avec), on le DIT plutôt que d'ouvrir une fenêtre vide qui laisserait
    croire à un bug.
    """

    def __init__(self, report: LogReport, archive_dir: Path,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._report = report
        self._archive_dir = Path(archive_dir)
        self.setWindowTitle("Journal de la dernière session")
        self.resize(640, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        head = QLabel(report.headline)
        head.setObjectName("SectionTitle")
        head.setWordWrap(True)
        root.addWidget(head)

        if not report.exists:
            # Pas de dialogue vide : le headline dit déjà pourquoi, on l'étoffe d'un mot.
            note = QLabel(
                "Rien à résumer pour cette session. Si vous attendiez des mods, "
                "vérifiez qu'UE4SS est bien installé (page Tableau de bord) — sans lui, "
                "aucun journal n'est écrit.")
            note.setObjectName("Dim")
            note.setWordWrap(True)
            root.addWidget(note)
            root.addStretch(1)
            root.addWidget(self._buttons(with_archive=False))
            return

        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(METRICS.pad_sm)

        for line in logs.explain(report):
            col.addWidget(self._bullet(line))

        col.addWidget(self._section("Mods chargés"))
        if report.mods:
            for m in report.mods:
                col.addWidget(self._bullet(f"{m.name}  ({m.via})"))
        else:
            col.addWidget(self._dim("Aucun mod n'a démarré."))

        if report.errors:
            col.addWidget(self._section("Erreurs"))
            for e in report.errors:
                item = self._bullet(e.message, marker="!")
                item.setStyleSheet(f"color:{PALETTE.error};")
                col.addWidget(item)
        col.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(body)
        root.addWidget(area, 1)
        root.addWidget(self._buttons(with_archive=True))

    def _buttons(self, *, with_archive: bool) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        if with_archive:
            archive = QPushButton("Archiver ce log")
            archive.clicked.connect(self._on_archive)
            row.addWidget(archive, 0)
        row.addStretch(1)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        row.addWidget(close, 0)
        return holder

    def _on_archive(self) -> None:
        dest = logs.archive(self._report, self._archive_dir)
        if dest is None:
            QMessageBox.warning(
                self, "Archivage impossible",
                "Le journal n'a pas pu être archivé (absent, ou écriture refusée).")
        else:
            QMessageBox.information(
                self, "Journal archivé",
                f"Une copie a été conservée :\n{dest}\n\nElle survivra au prochain "
                "lancement du jeu, qui écrasera UE4SS.log.")

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lbl.setContentsMargins(0, METRICS.pad_sm, 0, 0)
        return lbl

    @staticmethod
    def _bullet(text: str, marker: str = "•") -> QLabel:
        lbl = QLabel(f"{marker}  {text}")
        lbl.setWordWrap(True)
        lbl.setContentsMargins(METRICS.pad_sm, 0, 0, 0)
        return lbl

    @staticmethod
    def _dim(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("Dim")
        lbl.setWordWrap(True)
        return lbl


class DashboardPage(Page):
    """Accueil : état de l'installation, diagnostics, et lancement du jeu."""

    title = "Tableau de bord"
    icon = "◈"

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        self.header = PageHeader("Tableau de bord", "État de l'installation")
        root.addWidget(self.header)

        self.install_card = Card()
        root.addWidget(self.install_card)

        self.diag_card = Card()
        root.addWidget(self.diag_card)

        self.mods_card = Card()
        root.addWidget(self.mods_card)

        root.addStretch(1)

        play_row = QHBoxLayout()
        play_row.addStretch(1)
        self.play_btn = QPushButton("▶   Lancer le jeu")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setMinimumHeight(42)
        self.play_btn.setMinimumWidth(220)
        self.play_btn.clicked.connect(self._play)
        play_row.addWidget(self.play_btn)
        root.addLayout(play_row)

        # Détection de la fermeture du jeu, pour proposer le résumé des logs. On NE
        # bloque pas l'UI : un QTimer sonde l'état du process toutes les ~3 s. Le probe
        # est un attribut, donc injectable en test — sur ce poste de dev le jeu ne tourne
        # jamais, et sans ce point d'insertion le mécanisme serait invérifiable.
        self._running_probe: Callable[[], bool] = is_running
        self._watch_seen_running = False
        self._watch_done = False
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(3000)
        self._watch_timer.timeout.connect(self._poll_game)

        self.refresh()

    # --- rendu ---

    @staticmethod
    def _clear(card: Card) -> None:
        while card.body.count():
            item = card.body.takeAt(0)
            if (w := item.widget()) is not None:
                w.deleteLater()

    def refresh(self) -> None:
        self._render_install()
        self._render_diagnoses()
        self._render_mods()
        self.play_btn.setEnabled(self.ctx.install is not None)

    def _render_install(self) -> None:
        self._clear(self.install_card)
        inst = self.ctx.install

        if inst is None:
            self.install_card.body.addWidget(QLabel(
                "Aucune installation de Fading Echo trouvée."))
            hint = QLabel("Le jeu n'a pas été détecté dans vos bibliothèques Steam. "
                          "Indiquez son dossier à la main pour continuer.")
            hint.setObjectName("Dim")
            hint.setWordWrap(True)
            self.install_card.body.addWidget(hint)
            btn = QPushButton("Indiquer le dossier du jeu…")
            btn.clicked.connect(self._browse)
            self.install_card.body.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
            return

        row = QHBoxLayout()
        name = QLabel(inst.name)
        name.setObjectName("SectionTitle")
        row.addWidget(name)
        row.addWidget(Badge(
            {"full": "JEU COMPLET", "demo": "DÉMO"}.get(inst.edition.value, "ÉDITION INCONNUE"),
            "accent" if inst.edition.value != "unknown" else "warn"))
        if inst.has_ue4ss:
            row.addWidget(Badge("UE4SS", "ok"))
        else:
            row.addWidget(Badge("SANS UE4SS", "muted"))
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.install_card.body.addWidget(holder)

        path = QLabel(str(inst.root))
        path.setObjectName("Dim")
        path.setWordWrap(True)
        self.install_card.body.addWidget(path)

    def _render_diagnoses(self) -> None:
        self._clear(self.diag_card)
        diags = self.ctx.diagnoses

        title_row = QHBoxLayout()
        t = QLabel("Diagnostic")
        t.setObjectName("SectionTitle")
        title_row.addWidget(t)
        title_row.addStretch(1)
        # Sans installation, il n'y a rien à diagnostiquer — et afficher un « TOUT VA
        # BIEN » vert alors que le jeu est introuvable est un contresens : l'utilisateur
        # ira chercher le problème ailleurs. On dit qu'on attend, pas que tout va bien.
        if self.ctx.install is None:
            title_row.addWidget(Badge("EN ATTENTE", "muted"))
            holder = QWidget()
            holder.setLayout(title_row)
            self.diag_card.body.addWidget(holder)
            waiting = QLabel("Aucun diagnostic possible tant qu'aucun jeu n'est désigné.")
            waiting.setObjectName("Dim")
            waiting.setWordWrap(True)
            self.diag_card.body.addWidget(waiting)
            return

        level = self.ctx.worst_level()
        title_row.addWidget(Badge(
            {"ok": "TOUT VA BIEN", "warn": "À VÉRIFIER", "error": "PROBLÈME"}[level.value],
            _LEVEL_KIND[level]))
        holder = QWidget()
        holder.setLayout(title_row)
        self.diag_card.body.addWidget(holder)

        problems = [d for d in diags if d.level is not Level.OK]
        if not problems:
            ok = QLabel(doctor.summary(diags) if diags
                        else "Rien à signaler.")
            ok.setObjectName("Dim")
            self.diag_card.body.addWidget(ok)
            return

        for d in problems[:6]:
            self.diag_card.body.addWidget(self._diag_row(d))
        if len(problems) > 6:
            more = QLabel(f"…et {len(problems) - 6} autre(s).")
            more.setObjectName("Dim")
            self.diag_card.body.addWidget(more)

    def _diag_row(self, d: doctor.Diagnosis) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(METRICS.pad_sm)

        dot = QLabel("●")
        dot.setStyleSheet(
            f"color:{PALETTE.error if d.level is Level.ERROR else PALETTE.warn};")
        row.addWidget(dot, 0)

        text = QLabel(d.title)
        text.setWordWrap(True)
        row.addWidget(text, 1)

        # Un diagnostic porte SOIT un correctif unique (`fix`), SOIT plusieurs branches
        # (`options`) quand la bonne action dépend d'un choix — typiquement un conflit de
        # touches où le launcher ne peut pas deviner quel mod garder. Ces `options`
        # existaient dans doctor.py mais n'étaient rendues nulle part : le diagnostic
        # s'affichait sans bouton, sans aucun moyen de le résoudre depuis l'interface.
        if d.fix is not None:
            btn = QPushButton(d.fix_label or "Corriger")
            btn.clicked.connect(lambda _=False, diag=d: self._apply_fix(diag))
            row.addWidget(btn, 0)
        elif d.options:
            btn = QPushButton(d.fix_label or "Résoudre…")
            menu = QMenu(btn)
            for opt in d.options:
                menu.addAction(opt.label,
                               lambda o=opt, diag=d: self._apply_option(diag, o))
            btn.setMenu(menu)
            row.addWidget(btn, 0)
        return holder

    def _render_mods(self) -> None:
        self._clear(self.mods_card)
        t = QLabel("Mods")
        t.setObjectName("SectionTitle")
        self.mods_card.body.addWidget(t)

        if self.ctx.install is None or not self.ctx.install.has_ue4ss:
            lbl = QLabel("UE4SS n'est pas installé : aucun mod ne peut être chargé. "
                         "Le jeu fonctionne normalement sans.")
            lbl.setObjectName("Dim")
            lbl.setWordWrap(True)
            self.mods_card.body.addWidget(lbl)
            return

        enabled = len(self.ctx.enabled_mods)
        total = len(self.ctx.visible_mods)
        conflicts = len(self.ctx.conflicts)

        # Volontairement un résumé chiffré et rien de plus : le détail des conflits et
        # des mods non compilés est déjà dans la carte Diagnostic juste au-dessus.
        # Le répéter ici donnerait l'impression de deux problèmes distincts.
        summary = QLabel(f"{enabled} actif(s) sur {total}")
        self.mods_card.body.addWidget(summary)

        if conflicts:
            w = QLabel(f"{conflicts} conflit(s) entre mods actifs — voir le diagnostic.")
            w.setObjectName("Dim")
            self.mods_card.body.addWidget(w)

    # --- actions ---

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Dossier du jeu Fading Echo")
        if not chosen:
            return
        if self.ctx.add_root(chosen) is None:
            QMessageBox.warning(
                self, "Dossier non reconnu",
                "Ce dossier ne ressemble pas à une installation de Fading Echo.\n\n"
                "Le dossier attendu contient « UE_YGRO\\Binaries\\Win64 ».")

    def _apply_fix(self, d: doctor.Diagnosis) -> None:
        if d.fix is None:
            return
        confirm = QMessageBox.question(
            self, "Appliquer le correctif",
            f"{d.title}\n\n{d.detail}\n\n"
            f"{d.why}\n\nAppliquer ce correctif ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm is not QMessageBox.StandardButton.Yes:
            return

        # Le journal reçoit les mutations : c'est ce qui rend le correctif annulable
        # depuis la page Désinstallation.
        try:
            result = d.fix(ledger=self.ctx.ledger)
        except TypeError:
            result = d.fix()

        self._report_fix(result)

    def _apply_option(self, d: doctor.Diagnosis, option) -> None:
        confirm = QMessageBox.question(
            self, "Résoudre le conflit",
            f"{d.title}\n\n{d.why}\n\n{option.label}\n\nContinuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm is not QMessageBox.StandardButton.Yes:
            return
        try:
            result = option.run(ledger=self.ctx.ledger)
        except TypeError:
            result = option.run()
        self._report_fix(result)

    def _report_fix(self, result) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Correctif" if result.ok else "Correctif non appliqué")
        box.setText(result.message)
        box.setIcon(QMessageBox.Icon.Information if result.ok
                    else QMessageBox.Icon.Warning)
        box.exec()
        self.ctx.discover()

    def _play(self) -> None:
        inst = self.ctx.install
        if inst is None:
            return
        mode = LaunchMode(self.ctx.settings.launch_mode)
        result = launch(inst, mode=mode)
        if not result.ok:
            QMessageBox.warning(self, "Lancement impossible",
                                result.error or "Le jeu n'a pas pu être lancé.")
            return
        if result.warnings:
            QMessageBox.information(self, "Jeu lancé", "\n".join(result.warnings))
        # Le lancement a réussi : on commence à surveiller sa fermeture pour proposer le
        # résumé des logs. Toute la logique de lancement ci-dessus reste inchangée — si la
        # surveillance est indisponible, le jeu tourne quand même.
        self._begin_watching()

    # --- surveillance de la fermeture du jeu ---

    def _begin_watching(self) -> None:
        """Démarre le sondage périodique, sauf si l'utilisateur a coupé le résumé.

        Réinitialise l'état à chaque lancement : une session précédente a pu laisser
        `_watch_seen_running` à vrai.
        """
        if not self.ctx.settings.review_logs_on_close:
            return
        self._watch_seen_running = False
        self._watch_done = False
        if not self._watch_timer.isActive():
            self._watch_timer.start()

    def _poll_game(self) -> None:
        """Un tour de sonde. Déclenche le résumé au passage « tournait » → « fermé ».

        On n'agit qu'après avoir VU le jeu tourner au moins une fois : sinon un lancement
        Steam encore en cours de démarrage (process pas encore visible) serait pris pour
        une fermeture immédiate. Le résumé n'est proposé qu'une seule fois par session.
        """
        try:
            running = bool(self._running_probe())
        except Exception:
            # Une sonde qui échoue ne doit jamais faire remonter d'exception dans le
            # timer : on considère simplement qu'on ne sait pas, et on réessaiera.
            return
        if running:
            self._watch_seen_running = True
            return
        if self._watch_seen_running and not self._watch_done:
            self._watch_done = True
            self._watch_timer.stop()
            self._on_game_closed()

    def _on_game_closed(self) -> None:
        """Le jeu s'est fermé : lit UE4SS.log et propose le dialogue de résumé."""
        if not self.ctx.settings.review_logs_on_close:
            return
        layout = self.ctx.install.ue4ss if self.ctx.install is not None else None
        report = logs.read(layout)
        dialog = LogReviewDialog(report, self.ctx.data_dir / "logs", self)
        self._present_dialog(dialog)

    def _present_dialog(self, dialog: QDialog) -> None:
        """Affiche le dialogue de résumé. Point d'insertion des tests (non bloquant)."""
        dialog.exec()


class MainWindow(QWidget):
    """Coquille : barre latérale à gauche, pages à droite, barre d'état en bas."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("Fading Echo Launcher")
        self.resize(1120, 720)
        self.setMinimumSize(940, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar, 0)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        self.status = QLabel()
        self.status.setObjectName("StatusBar")
        self.status.setContentsMargins(METRICS.pad, 6, METRICS.pad, 6)
        outer.addWidget(self.status, 0)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        ctx.changed.connect(self._update_status)
        self.register_page(DashboardPage(ctx))
        # `discover()` est appelé AVANT la construction de la fenêtre : le signal
        # `changed` est donc déjà passé et la barre resterait vide jusqu'à la première
        # modification. On la remplit une fois au démarrage.
        self._update_status()

    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(METRICS.sidebar_w)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, METRICS.pad)
        layout.setSpacing(0)

        brand = QLabel("Fading Echo")
        brand.setObjectName("SidebarBrand")
        layout.addWidget(brand)

        version = QLabel(f"Launcher {__version__}")
        version.setObjectName("SidebarVersion")
        layout.addWidget(version)

        self.nav_layout = QVBoxLayout()
        self.nav_layout.setSpacing(0)
        layout.addLayout(self.nav_layout)
        layout.addStretch(1)
        return bar

    def register_page(self, page: Page) -> QPushButton:
        """Ajoute une page et son entrée de navigation."""
        index = self.stack.addWidget(scrollable(page))

        btn = QPushButton(f"  {page.icon}   {page.title}" if page.icon else page.title)
        btn.setObjectName("NavButton")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _=False, i=index: self.stack.setCurrentIndex(i))
        self._nav_group.addButton(btn)
        self.nav_layout.addWidget(btn)
        if index == 0:
            btn.setChecked(True)
        return btn

    def _update_status(self) -> None:
        inst = self.ctx.install
        if inst is None:
            self.status.setText("Aucune installation détectée")
            return
        bits = [inst.name]
        if inst.has_ue4ss and inst.ue4ss is not None:
            bits.append("UE4SS " + ("imbriqué" if inst.ue4ss.nested else "à plat"))
        bits.append(f"{len(self.ctx.enabled_mods)} mod(s) actif(s)")
        pending = len(self.ctx.ledger.pending)
        if pending:
            bits.append(f"{pending} modification(s) réversible(s)")
        self.status.setText("   ·   ".join(bits))
