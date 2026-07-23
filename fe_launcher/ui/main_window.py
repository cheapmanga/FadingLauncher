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
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import doctor, logs, portraits, ue4ss_setup
from ..core.doctor import Level
from ..core.launch import LaunchMode, is_running, launch
from ..core.logs import LogReport
from ..core.mods import ModState
from ..core.paths import Edition, GameInstall
from ..core.ue4ss_setup import SetupReport, looks_like_ue4ss_zip
from .context import AppContext
from .theme import METRICS, PALETTE
from .widgets import Badge, Card, ComboBox, PageHeader, separator

# Libellés utilisateur des éditions. Isolé ici parce qu'il sert à deux endroits (le badge
# de la carte install et le libellé du sélecteur d'installation) et qu'un jeu complet
# affiché « DEMO » enverrait l'utilisateur chercher un problème inexistant.
_EDITION_LABEL = {
    Edition.DEMO: "Démo",
    Edition.FULL: "Jeu complet",
    Edition.UNKNOWN: "Édition inconnue",
}


def _install_label(inst: GameInstall) -> str:
    """« Project Ygrό — Jeu complet » : nom du dossier + édition en clair.

    Le nom seul ne suffit pas à choisir entre deux installs (démo et complète portent
    des dossiers différents mais l'utilisateur ne les distingue pas de tête) ; l'édition
    seule non plus si les deux sont du même type. On donne les deux.
    """
    return f"{inst.name} — {_EDITION_LABEL.get(inst.edition, _EDITION_LABEL[Edition.UNKNOWN])}"

_LEVEL_KIND = {Level.OK: "ok", Level.WARN: "warn", Level.ERROR: "error"}

_BRAND_SIZE = 34


def _brand_avatar() -> QLabel | None:
    """Vignette ronde de l'avatar de One pour la bannière, ou None si l'asset manque.

    L'image vient du jeu (`HUD_Avatar_One_Shard.png`) : elle ancre le launcher dans
    Fading Echo. Absente (build sans portraits), on renvoie None et la bannière tient
    sans elle — jamais de carré vide.
    """
    path = portraits.RESOURCES / "HUD_Avatar_One_Shard.png"
    if not path.is_file():
        return None
    pix = QPixmap(str(path))
    if pix.isNull():
        return None
    lbl = QLabel()
    lbl.setFixedSize(_BRAND_SIZE, _BRAND_SIZE)
    lbl.setScaledContents(True)
    lbl.setPixmap(pix.scaled(_BRAND_SIZE, _BRAND_SIZE, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation))
    lbl.setStyleSheet(
        f"border:1px solid {PALETTE.border_glow}; border-radius:{_BRAND_SIZE // 2}px;"
        f"background:{PALETTE.surface_alt};")
    return lbl


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


class Ue4ssSetupDialog(QDialog):
    """Assistant « Installer UE4SS et corriger le jeu ».

    Pourquoi ce dialogue existe
    ---------------------------
    Sur le jeu complet, deux problèmes se cumulent et rendent les mods muets : UE4SS peut
    être absent, ET le dossier `Project Ygrό` porte un omicron grec qui tue UE4SS au
    démarrage. Les deux se règlent en une passe (`ue4ss_setup.run`), mais l'opération
    touche au disque et peut être REFUSÉE (Steam ouvert). On ne cache jamais ce refus : le
    rapport étape par étape le montre tel quel, sinon l'utilisateur relancerait le jeu en
    croyant le correctif appliqué.

    Le .zip d'UE4SS est fourni par l'utilisateur (aucune URL n'est codée en dur : injecter
    un binaire dans le jeu mérite un choix explicite). Il est OPTIONNEL : si UE4SS est déjà
    là et qu'il ne reste que le chemin grec à corriger, on lance sans zip.
    """

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._zip: Path | None = None
        self.setWindowTitle("Installer UE4SS")
        self.resize(600, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        head = QLabel("Installer UE4SS et corriger le jeu")
        head.setObjectName("SectionTitle")
        head.setWordWrap(True)
        root.addWidget(head)

        intro = QLabel(
            "Le launcher télécharge UE4SS tout seul depuis GitHub (l'extension qui permet "
            "au jeu de charger les mods), l'installe, et corrige le dossier au caractère "
            "grec qui empêche UE4SS de démarrer. Vous n'avez rien à fournir.")
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # Le correctif du chemin RENOMME le dossier du jeu : Steam doit être fermé, sinon
        # il tient le dossier ouvert et le renommage est refusé. On le dit d'emblée plutôt
        # que de laisser l'utilisateur le découvrir dans un rapport rouge.
        note = QLabel("Le correctif du dossier exige que Steam soit entièrement fermé "
                      "(icône de la barre des tâches → Quitter).")
        note.setObjectName("Dim")
        note.setWordWrap(True)
        root.addWidget(note)

        root.addWidget(separator())

        # Choix d'un .zip local, EN OPTION : le cas normal est le téléchargement auto.
        # Utile hors ligne, ou pour imposer une version précise d'UE4SS.
        zip_row = QHBoxLayout()
        self.zip_btn = QPushButton("Utiliser un .zip local (optionnel)…")
        self.zip_btn.clicked.connect(self._choose_zip)
        zip_row.addWidget(self.zip_btn, 0)
        self.zip_label = QLabel("Par défaut, UE4SS est téléchargé automatiquement.")
        self.zip_label.setObjectName("Dim")
        self.zip_label.setWordWrap(True)
        zip_row.addWidget(self.zip_label, 1)
        zip_holder = QWidget()
        zip_holder.setLayout(zip_row)
        root.addWidget(zip_holder)

        # Avertissement d'archive non reconnue, masqué tant qu'il n'y a rien à signaler.
        self.zip_warning = QLabel()
        self.zip_warning.setWordWrap(True)
        self.zip_warning.setStyleSheet(f"color:{PALETTE.error};")
        self.zip_warning.hide()
        root.addWidget(self.zip_warning)

        # Installer les mods dans la foulée : c'est le geste que l'utilisateur veut
        # presque toujours (UE4SS ne sert à rien sans mods). Coché par défaut, mais
        # décochable pour qui veut choisir ses mods à la main.
        self.install_mods_box = QCheckBox("Installer aussi les mods fournis (recommandé)")
        self.install_mods_box.setChecked(True)
        root.addWidget(self.install_mods_box)

        # Zone de rapport, remplie après le lancement.
        self.report_holder = QWidget()
        self.report_layout = QVBoxLayout(self.report_holder)
        self.report_layout.setContentsMargins(0, 0, 0, 0)
        self.report_layout.setSpacing(METRICS.pad_sm)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(self.report_holder)
        root.addWidget(area, 1)

        buttons = QHBoxLayout()
        self.run_btn = QPushButton("Lancer l'installation")
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._run)
        buttons.addWidget(self.run_btn, 0)
        buttons.addStretch(1)
        self.close_btn = QPushButton("Fermer")
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn, 0)
        root.addLayout(buttons)

    def _choose_zip(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Archive UE4SS", "", "Archives ZIP (*.zip)")
        if not chosen:
            return
        self._set_zip(Path(chosen))

    def _set_zip(self, path: Path) -> None:
        """Enregistre le zip choisi et valide qu'il ressemble bien à UE4SS.

        Séparé de `_choose_zip` pour rester pilotable en test sans QFileDialog. On ne
        REFUSE pas un zip non reconnu (l'utilisateur peut savoir mieux), on avertit : mais
        l'avertissement est rouge et visible, car extraire n'importe quoi dans Binaries est
        le genre d'erreur qu'on ne remarque qu'au prochain crash.
        """
        self._zip = path
        self.zip_label.setText(str(path))
        if looks_like_ue4ss_zip(path):
            self.zip_warning.hide()
        else:
            self.zip_warning.setText(
                "Cette archive ne ressemble pas à UE4SS (dwmapi.dll + UE4SS-settings.ini "
                "introuvables). Vérifiez que c'est bien le bon .zip.")
            self.zip_warning.show()

    def _run(self) -> None:
        """Lance l'installation et affiche le rapport étape par étape.

        Passe par `ue4ss_setup.run` (référencé via le module pour rester remplaçable en
        test). `ctx.discover()` reconstruit ensuite l'état disque : le renommage a changé
        le chemin de l'install, la garder en mémoire pointerait sur un dossier disparu.
        """
        # Si UE4SS est déjà là, on RÉINSTALLE par-dessus : c'est le cas quand un build
        # cassé ou incomplet a été posé et qu'il faut le remplacer.
        reinstall = self.ctx.install is not None and self.ctx.install.has_ue4ss
        report = ue4ss_setup.run(
            self.ctx.install, self.ctx.ledger,
            ue4ss_zip=self._zip, reinstall=reinstall,
            probe=doctor.steam_processes_running)
        # `discover()` reconstruit l'état : le renommage a changé le chemin de l'install.
        self.ctx.discover()

        # Installer les mods APRÈS le discover : ils doivent aller dans l'install
        # fraîchement re-détectée (au nouveau chemin ASCII), pas dans l'ancien dossier
        # grec qui vient d'être renommé. On ne le fait que si UE4SS est bien en place.
        if (self.install_mods_box.isChecked() and self.ctx.install is not None
                and self.ctx.install.has_ue4ss):
            from ..core import modinstall
            mods_report = modinstall.install_all(
                self.ctx.install.ue4ss, self.ctx.ledger,
                include_restricted=self.ctx.settings.developer_mode)
            report.add("Mods fournis", mods_report.ok, mods_report.message)
            self.ctx.refresh()

        self._render_report(report)

        # Installation réussie : plus rien à relancer. Le bouton « Lancer » invite alors
        # à recommencer une opération déjà faite ; on le transforme en « Fermer » pour que
        # le geste évident (sortir) soit celui qui reste en avant.
        if report.ok:
            # La question qui suit systématiquement une install réussie est « et
            # maintenant, où est la fenêtre UE4SS ? ». Elle ne s'ouvre pas seule : il
            # faut la demander en jeu. Le dire ici évite de la croire absente.
            report.add("En jeu", True,
                       "Ctrl+O ouvre la console UE4SS, F10 la console du jeu "
                       "(pour taper les commandes des mods).")
            self._render_report(report)
            self.run_btn.setText("Fermer")
            try:
                self.run_btn.clicked.disconnect(self._run)
            except (TypeError, RuntimeError):
                pass
            self.run_btn.clicked.connect(self.accept)
            self.close_btn.hide()

    def _render_report(self, report: SetupReport) -> None:
        while self.report_layout.count():
            item = self.report_layout.takeAt(0)
            if (w := item.widget()) is not None:
                w.deleteLater()

        summary = QLabel(report.message)
        summary.setObjectName("SectionTitle")
        summary.setWordWrap(True)
        self.report_layout.addWidget(summary)

        for step in report.steps:
            self.report_layout.addWidget(self._step_row(step))
        self.report_layout.addStretch(1)

    def _step_row(self, step: ue4ss_setup.SetupStep) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(METRICS.pad_sm)

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{PALETTE.ok if step.ok else PALETTE.error};")
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        label = QLabel(step.label)
        label.setWordWrap(True)
        col.addWidget(label)
        if step.detail:
            detail = QLabel(step.detail)
            detail.setObjectName("Dim")
            detail.setWordWrap(True)
            col.addWidget(detail)
        row.addLayout(col, 1)
        return holder


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
                          "Indiquez son dossier à la main pour continuer. Vous pouvez en "
                          "désigner plusieurs — elles apparaîtront dans un sélecteur.")
            hint.setObjectName("Dim")
            hint.setWordWrap(True)
            self.install_card.body.addWidget(hint)
            btn = QPushButton("Indiquer le dossier du jeu…")
            btn.clicked.connect(self._browse)
            self.install_card.body.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
            return

        # Sélecteur d'installation. Le launcher choisit tout seul une install au démarrage
        # (souvent la démo, découverte en premier), et sans ce sélecteur l'utilisateur du
        # jeu complet n'a AUCUN moyen de basculer dessus : il diagnostiquerait la démo en
        # croyant regarder son jeu. On ne l'affiche qu'à partir de deux installs, sinon
        # c'est une liste déroulante à un seul choix, du bruit pur.
        if len(self.ctx.installs) > 1:
            self.install_picker = ComboBox()
            for i in self.ctx.installs:
                self.install_picker.addItem(_install_label(i))
            current = next((n for n, i in enumerate(self.ctx.installs)
                            if i.root == inst.root), 0)
            # On positionne l'index AVANT de brancher le signal : sinon la simple
            # construction déclencherait un select() (et un refresh réentrant).
            self.install_picker.setCurrentIndex(current)
            self.install_picker.currentIndexChanged.connect(self._on_pick_install)
            self.install_card.body.addWidget(self.install_picker)

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

        # Bouton d'installation/réparation d'UE4SS, TOUJOURS proposé :
        #  - UE4SS absent    → « Installer UE4SS » ;
        #  - chemin non-ASCII (piège `Project Ygrό`, UE4SS « présent » mais mort au boot)
        #    ou UE4SS déjà là → « Réinstaller UE4SS » pour remplacer un build cassé.
        # Sans un moyen de réinstaller, un utilisateur coincé avec un UE4SS qui ne démarre
        # pas (mauvais build) ne pourrait rien faire depuis le launcher.
        # « corriger le dossier » n'est mentionné QUE s'il y a réellement un chemin grec à
        # corriger : sur une démo (chemin ASCII), promettre une correction inexistante est
        # une sur-promesse.
        if not inst.has_ue4ss:
            label = ("Installer UE4SS et corriger le dossier" if inst.non_ascii_path
                     else "Installer UE4SS")
        elif inst.non_ascii_path:
            label = "Réparer UE4SS et corriger le dossier"
        else:
            label = "Réinstaller UE4SS"
        self.ue4ss_btn = QPushButton(label)
        self.ue4ss_btn.setObjectName("Primary")
        self.ue4ss_btn.clicked.connect(self._install_ue4ss)
        self.install_card.body.addWidget(
            self.ue4ss_btn, 0, Qt.AlignmentFlag.AlignLeft)

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

    def _on_pick_install(self, index: int) -> None:
        """Bascule l'install active depuis le sélecteur. Ignore un index hors liste
        (peut arriver le temps d'une reconstruction du combo pendant un refresh)."""
        if 0 <= index < len(self.ctx.installs):
            self.ctx.select(self.ctx.installs[index])

    def _install_ue4ss(self) -> None:
        """Ouvre l'assistant d'installation d'UE4SS pour l'install active."""
        if self.ctx.install is None:
            return
        dialog = Ue4ssSetupDialog(self.ctx, self)
        self._present_dialog(dialog)

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
        # résumé des logs. On MÉMORISE l'install lancée : si l'utilisateur bascule le
        # sélecteur pendant qu'il joue, le résumé doit rester celui du jeu qui a
        # réellement tourné, pas de l'install affichée à la fermeture.
        self._watched_install = inst
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
        # L'install LANCÉE, pas celle actuellement sélectionnée : l'utilisateur a pu
        # changer de sélecteur entre-temps.
        watched = getattr(self, "_watched_install", None) or self.ctx.install
        layout = watched.ue4ss if watched is not None else None
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

        # Marque : l'avatar de One (image du jeu) posé à côté du nom, pour ancrer le
        # launcher dans l'univers de Fading Echo dès le premier coup d'œil.
        brand_row = QWidget()
        brow = QHBoxLayout(brand_row)
        brow.setContentsMargins(METRICS.pad, METRICS.pad, METRICS.pad, 0)
        brow.setSpacing(METRICS.pad_sm)
        avatar = _brand_avatar()
        if avatar is not None:
            brow.addWidget(avatar, 0)
        wordmark = QLabel("FADING ECHO")
        wordmark.setObjectName("SidebarBrand")
        wordmark.setContentsMargins(0, 0, 0, 0)
        brow.addWidget(wordmark, 1)
        layout.addWidget(brand_row)

        sub = QLabel("SPEEDRUN LAUNCHER")
        sub.setObjectName("SidebarBrandSub")
        layout.addWidget(sub)

        # Liseré des cinq cores : l'identité chromatique du jeu en une bande.
        art = QLabel()
        art.setObjectName("SidebarArt")
        layout.addWidget(art)

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
