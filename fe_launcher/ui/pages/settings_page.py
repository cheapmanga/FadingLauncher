"""Page Paramètres : préférences de l'outil, journal des modifications, désinstallation.

Pourquoi ces quatre blocs sur le même écran
-------------------------------------------
Ils répondent tous à la même question : « qu'est-ce que ce launcher fait à ma machine,
et comment je reviens en arrière ? » Éparpiller les préférences ici et l'historique
là-bas obligerait à chercher, or c'est exactement l'information qu'un utilisateur veut
trouver vite quand il commence à se méfier d'un outil qui écrit dans son dossier de jeu.

**Le journal est visible, pas juste annulable.** Afficher la liste des modifications
en vigueur coûte quelques lignes et transforme une promesse (« c'est réversible ») en
fait vérifiable. Sans elle, « Tout annuler » demande de croire l'outil sur parole.

**La désinstallation est en bas, dans les options avancées, et derrière une saisie.**
Trois précautions cumulées, pour trois raisons distinctes :
  * en bas, parce qu'on ne tombe pas dessus en cherchant à régler le mode de lancement ;
  * le plan détaillé AVANT, parce que l'opération touche des fichiers dans le dossier
    de jeu de l'utilisateur et qu'il a le droit de lire la liste exacte ;
  * un mot à taper, parce qu'un oui/non se clique par réflexe. Recopier « SUPPRIMER »
    ne s'obtient pas par inattention.

**L'ordre undo → purge n'est pas interchangeable, et un échec l'interrompt.** Purger
efface les sauvegardes ; si une annulation a échoué, ces sauvegardes sont le seul moyen
de réessayer plus tard. On préfère donc laisser le launcher installé avec un journal
intact plutôt que de rendre une réparation impossible. C'est le point le plus important
de ce module.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ...core import doctor, steamcfg
from ...core.launch import LaunchMode
from ...core.ledger import Entry, UndoResult
from ...core.settings import Settings
from ..context import AppContext
from ..main_window import Page
from ..theme import METRICS, PALETTE
from ..widgets import Badge, Card, ComboBox, PageHeader, separator

#: Mot à recopier pour confirmer une désinstallation. En français et en majuscules :
#: il doit être pénible à taper par distraction, mais évident à lire.
CONFIRM_WORD = "SUPPRIMER"

#: Ce que la désinstallation ne touche pas. Énuméré en toutes lettres à l'écran :
#: « seul ce que le launcher a fait est défait » est trop abstrait pour rassurer
#: quelqu'un qui a passé des heures à fabriquer ses paks.
UNTOUCHED = [
    "les mods que vous avez installés vous-même,",
    "les paks et fichiers de contenu que vous avez ajoutés,",
    "vos sauvegardes de partie,",
    "et le jeu lui-même, qui n'est jamais désinstallé.",
]


def _dim(text: str) -> QLabel:
    """Ligne d'explication sous un réglage. Toujours repliée, jamais tronquée."""
    label = QLabel(text)
    label.setObjectName("Dim")
    label.setWordWrap(True)
    return label


def _format_time(iso: str) -> str:
    """`2026-07-22T21:03:11+00:00` -> `22/07/2026 21:03`. Retombe sur le brut si besoin."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return iso


def describe(entry: Entry) -> str:
    """Une entrée de journal en une ligne lisible.

    Le `label` est rédigé par l'appelant et vaut toujours mieux que l'action brute ;
    on ne retombe sur `action` + nom de fichier que pour les entrées anciennes ou
    écrites sans libellé.
    """
    return entry.label or f"{entry.action.value} — {Path(entry.target).name}"


class ReportDialog(QDialog):
    """Rapport ligne à ligne d'une série d'annulations.

    Une `QMessageBox` tronque au-delà de quelques lignes ; or le rapport peut contenir
    des dizaines d'opérations et c'est justement le détail qui compte quand l'une
    d'elles a échoué.
    """

    def __init__(self, title: str, headline: str, results: list[UndoResult],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        head = QLabel(headline)
        head.setWordWrap(True)
        head.setObjectName("SectionTitle")
        root.addWidget(head)

        failed = [r for r in results if not r.ok]
        counts = QHBoxLayout()
        counts.addWidget(Badge(f"{len(results) - len(failed)} RÉUSSIE(S)", "ok"))
        if failed:
            counts.addWidget(Badge(f"{len(failed)} ÉCHEC(S)", "error"))
        counts.addStretch(1)
        root.addLayout(counts)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setObjectName("Mono")
        body.setPlainText("\n".join(
            f"{'OK  ' if r.ok else 'ÉCHEC'}  {describe(r.entry)}\n        {r.message}"
            for r in results) or "Aucune opération à effectuer.")
        root.addWidget(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


class UninstallDialog(QDialog):
    """Plan détaillé de la désinstallation + confirmation écrite.

    Le bouton de validation reste désactivé tant que le mot exact n'est pas saisi.
    Le plan est affiché tel que le journal le calcule, sans résumé : « 14 opérations »
    ne permet pas de vérifier qu'on ne perdra rien, la liste si.
    """

    def __init__(self, plan: list[tuple[Entry, str]], prefs_path: Path,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Désinstallation complète")
        self.resize(680, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        title = QLabel("Ce que la désinstallation va faire")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        root.addWidget(_dim(
            "Chaque ligne ci-dessous correspond à une modification que le launcher a "
            "faite et qu'il va défaire, de la plus récente à la plus ancienne."))

        listing = QPlainTextEdit()
        listing.setReadOnly(True)
        listing.setObjectName("Mono")
        listing.setPlainText("\n".join(
            f"{i:>3}.  {action}\n      {Path(entry.target)}"
            for i, (entry, action) in enumerate(plan, start=1))
            or "Le launcher n'a rien modifié dans le jeu : il n'y a rien à défaire.")
        root.addWidget(listing, 1)

        root.addWidget(separator())

        keep = QLabel("Ce qui n'est PAS touché")
        keep.setObjectName("SectionTitle")
        root.addWidget(keep)
        for line in UNTOUCHED:
            root.addWidget(_dim(f"•  {line}"))
        root.addWidget(_dim(
            f"Les préférences du launcher ({prefs_path}) seront supprimées, ainsi que "
            "son journal et ses sauvegardes."))

        root.addWidget(separator())

        prompt = QLabel(f"Pour confirmer, tapez <b>{CONFIRM_WORD}</b> ci-dessous :")
        prompt.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(prompt)

        self.field = QLineEdit()
        self.field.setPlaceholderText(CONFIRM_WORD)
        self.field.textChanged.connect(self._on_typed)
        root.addWidget(self.field)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.confirm = QPushButton("Tout défaire et désinstaller")
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.accept)
        row.addWidget(self.confirm)
        root.addLayout(row)

    def _on_typed(self, text: str) -> None:
        # Comparaison stricte, sans normalisation de casse : recopier exactement est
        # tout l'intérêt du garde-fou.
        armed = text.strip() == CONFIRM_WORD
        self.confirm.setEnabled(armed)
        # Le style `#Danger` (sélecteur d'identifiant) l'emporte sur `:disabled` : sans
        # ça, le bouton reste rouge vif alors qu'il ne réagit pas, et on croit à un bug.
        # On lui retire donc son identité tant qu'il n'est pas armé.
        self.confirm.setObjectName("Danger" if armed else "")
        self.confirm.style().unpolish(self.confirm)
        self.confirm.style().polish(self.confirm)


class SettingsPage(Page):
    """Préférences, journal des modifications et désinstallation."""

    title = "Paramètres"
    icon = "⚙"

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(ctx, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        root.addWidget(PageHeader(
            "Paramètres",
            "Comportement du launcher, et tout ce qu'il a modifié sur votre machine."))

        root.addWidget(self._general_card())
        root.addWidget(self._advanced_card())
        root.addWidget(self._developer_card())
        root.addWidget(self._streaming_card())

        self.ledger_card = Card()
        root.addWidget(self.ledger_card)

        # La désinstallation ferme la page : rien en dessous, pour qu'on ne clique
        # jamais dessus en visant autre chose. Le trait et le rappel « option avancée »
        # marquent la rupture avec les réglages courants qui précèdent.
        root.addWidget(separator())
        advanced_note = _dim("Option avancée — irréversible une fois confirmée.")
        advanced_note.setContentsMargins(0, METRICS.pad_sm, 0, 0)
        root.addWidget(advanced_note)
        root.addWidget(self._uninstall_card())
        root.addStretch(1)

        self._render_ledger()

    # --- sections ---

    def _general_card(self) -> Card:
        card = Card()
        title = QLabel("Général")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(METRICS.pad)
        label = QLabel("Mode de lancement")
        label.setMinimumWidth(190)
        row.addWidget(label, 0)

        self.launch_combo = ComboBox()
        for mode in LaunchMode:
            self.launch_combo.addItem(mode.label, mode.value)
        current = self.launch_combo.findData(self.ctx.settings.launch_mode)
        self.launch_combo.setCurrentIndex(max(0, current))
        self.launch_combo.currentIndexChanged.connect(self._on_launch_mode)
        row.addWidget(self.launch_combo, 1)
        holder = QWidget()
        holder.setLayout(row)
        card.body.addWidget(holder)

        # Formulation directe : les trois modes ne sont pas trois goûts, il y en a un
        # qui marche et deux dont on ignore le comportement sur ce jeu précis.
        card.body.addWidget(_dim(
            "Seul le lancement via Steam est vérifié comme fonctionnel sur Fading Echo. "
            "Les deux autres modes démarrent le jeu sans l'environnement que Steam "
            "installe autour : ils n'ont jamais été testés sur ce jeu et peuvent ne "
            "rien afficher, ou se fermer aussitôt."))

        self.launch_warning = Badge("MODE NON VÉRIFIÉ", "warn")
        card.body.addWidget(self.launch_warning, 0, Qt.AlignmentFlag.AlignLeft)
        self._sync_launch_warning()

        card.body.addWidget(separator())

        self.confirm_box = QCheckBox("Demander confirmation avant d'appliquer un profil")
        self.confirm_box.setChecked(self.ctx.settings.confirm_profile_apply)
        self.confirm_box.toggled.connect(self._on_confirm_profile)
        card.body.addWidget(self.confirm_box)
        card.body.addWidget(_dim(
            "Appliquer un profil écrase les réglages actuels des mods concernés. "
            "La confirmation rappelle lesquels avant d'écrire."))

        card.body.addWidget(separator())

        self.review_logs_box = QCheckBox("Lire les journaux à la fermeture du jeu")
        self.review_logs_box.setChecked(self.ctx.settings.review_logs_on_close)
        self.review_logs_box.toggled.connect(self._on_review_logs)
        card.body.addWidget(self.review_logs_box)
        card.body.addWidget(_dim(
            "À la fermeture du jeu, proposer un résumé de ce qui s'est chargé : quels "
            "mods ont démarré, et ce qui a échoué dans UE4SS.log. Le mode d'échec "
            "dominant de ce jeu est le silence — ce résumé le rend visible."))
        return card

    def _advanced_card(self) -> Card:
        card = Card()
        title = QLabel("Options avancées")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)

        self.advanced_box = QCheckBox("Afficher tous les réglages des mods")
        self.advanced_box.setChecked(self.ctx.settings.advanced_settings)
        self.advanced_box.toggled.connect(self._on_advanced)
        card.body.addWidget(self.advanced_box)
        card.body.addWidget(_dim(
            "En plus des réglages utiles, affiche les constantes techniques internes "
            "de chaque mod : chemins d'objets du jeu, noms de classes, préfixes de "
            "journal. Les modifier ne règle rien et casse généralement le mod. "
            "Réservé à ceux qui savent ce qu'ils font."))
        return card

    def _developer_card(self) -> Card:
        card = Card()
        title = QLabel("Mode développeur")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)

        self.developer_box = QCheckBox("Activer le mode développeur")
        self.developer_box.setChecked(self.ctx.settings.developer_mode)
        self.developer_box.toggled.connect(self._on_developer)
        card.body.addWidget(self.developer_box)
        card.body.addWidget(_dim(
            "Rend visibles dans la page Mods des mods qui touchent à l'outillage de "
            "développement interne du jeu : fonctions de triche du studio, cartes de "
            "test, déblocage global. Ce n'est pas prévu pour un usage normal et peut "
            "rendre une partie incohérente. Rien n'est installé ni activé en cochant "
            "cette case : les mods concernés deviennent simplement visibles."))
        return card

    def _streaming_card(self) -> Card:
        """Branchement du launcher sur Steam + option de lancement discret.

        Pourquoi tout est réuni ici
        ---------------------------
        Le branchement automatique (écriture dans localconfig.vdf) est le seul geste de
        l'outil qui puisse casser la configuration Steam de l'utilisateur ; il est donc
        entouré de garde-fous côté cœur (`steamcfg.wire` refuse si Steam n'est pas prouvé
        fermé). Ici l'UI se contente de RELAYER ces refus tels quels — un refus n'est pas
        une erreur à masquer, c'est l'information utile — et de garder VISIBLE en
        permanence la ligne à coller à la main, même quand l'écriture auto a réussi : le
        repli manuel doit toujours rester à portée.
        """
        card = Card()
        title = QLabel("Streaming / Steam")
        title.setObjectName("SectionTitle")
        card.body.addWidget(title)
        card.body.addWidget(_dim(
            "Branchez le launcher sur Steam pour que « Jouer » depuis Steam ouvre "
            "d'abord le launcher : il applique vos réglages, puis lance le jeu."))

        # --- Exe du launcher : ce qui va dans l'option de lancement ---
        card.body.addWidget(separator())
        row = QHBoxLayout()
        row.setSpacing(METRICS.pad_sm)
        exe_label = QLabel("Exécutable du launcher")
        exe_label.setMinimumWidth(190)
        row.addWidget(exe_label, 0)
        self.launcher_exe_field = QLineEdit(self._launcher_exe())
        self.launcher_exe_field.setObjectName("Mono")
        self.launcher_exe_field.editingFinished.connect(self._on_launcher_exe_edited)
        row.addWidget(self.launcher_exe_field, 1)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._on_browse_launcher_exe)
        row.addWidget(browse, 0)
        holder = QWidget()
        holder.setLayout(row)
        card.body.addWidget(holder)
        card.body.addWidget(_dim(
            "Chemin utilisé pour composer l'option de lancement Steam. Sur ce poste de "
            "développement, l'interpréteur Python est pris par défaut, faute d'un vrai "
            "exécutable installé."))

        # --- État du branchement ---
        card.body.addWidget(separator())
        state_row = QHBoxLayout()
        state_row.setSpacing(METRICS.pad_sm)
        state_title = QLabel("État du branchement")
        state_title.setObjectName("SectionTitle")
        state_row.addWidget(state_title, 0)
        self.steam_status_badge = Badge("", "muted")
        state_row.addWidget(self.steam_status_badge, 0)
        state_row.addStretch(1)
        state_holder = QWidget()
        state_holder.setLayout(state_row)
        card.body.addWidget(state_holder)

        self.steam_status_label = _dim("")
        card.body.addWidget(self.steam_status_label)
        self.steam_current_label = _dim("")
        card.body.addWidget(self.steam_current_label)

        btn_row = QHBoxLayout()
        self.wire_btn = QPushButton("Brancher sur Steam")
        self.wire_btn.clicked.connect(self._on_wire)
        btn_row.addWidget(self.wire_btn, 0)
        self.unwire_btn = QPushButton("Débrancher")
        self.unwire_btn.clicked.connect(self._on_unwire)
        btn_row.addWidget(self.unwire_btn, 0)
        btn_row.addStretch(1)
        card.body.addLayout(btn_row)

        # --- Repli manuel : TOUJOURS visible, même après un branchement réussi ---
        card.body.addWidget(separator())
        card.body.addWidget(_dim(
            "Ligne à coller à la main dans Steam → Propriétés du jeu → Options de "
            "lancement. Elle reste disponible même si le branchement automatique a "
            "réussi : c'est le repli si Steam réécrit sa configuration."))
        copy_row = QHBoxLayout()
        copy_row.setSpacing(METRICS.pad_sm)
        self.steam_copy_line = QLineEdit()
        self.steam_copy_line.setReadOnly(True)
        self.steam_copy_line.setObjectName("Mono")
        copy_row.addWidget(self.steam_copy_line, 1)
        copy_btn = QPushButton("Copier")
        copy_btn.clicked.connect(self._on_copy_launch_line)
        copy_row.addWidget(copy_btn, 0)
        card.body.addLayout(copy_row)

        # --- Mode discret (stream) ---
        card.body.addWidget(separator())
        self.stream_mode_box = QCheckBox("Mode discret (stream)")
        self.stream_mode_box.setChecked(self.ctx.settings.stream_mode)
        self.stream_mode_box.toggled.connect(self._on_stream_mode)
        card.body.addWidget(self.stream_mode_box)
        card.body.addWidget(_dim(
            "Par défaut, quand Steam lance le jeu via le launcher, celui-ci ajoute une "
            "étape (une fenêtre) avant le lancement. En mode discret, le launcher "
            "applique les réglages, lance le jeu et s'efface — sans fenêtre, pour ne "
            "pas apparaître à l'écran pendant un stream. Désactivé par défaut."))

        self._refresh_steam()
        return card

    def _launcher_exe(self) -> str:
        """Exe à brancher : le chemin renseigné, sinon l'interpréteur courant (dev).

        On ne devine jamais un chemin Windows ici : en développement il n'y a pas d'exe
        empaqueté, et `sys.executable` donne au moins une valeur réelle à afficher et à
        recopier, quitte à ce que l'utilisateur la remplace par le vrai exe.
        """
        return self.ctx.settings.launcher_exe or sys.executable

    def _refresh_steam(self) -> None:
        """Relit l'état Steam et met à jour badge, message, option actuelle et repli.

        `steamcfg.status` ne lève pas : sur un poste sans Steam (le cas de ce Pc Linux),
        il rend `supported=False` avec un message explicatif, que l'on affiche tel quel.
        """
        exe = self._launcher_exe()
        st = steamcfg.status(exe)
        if st.wired:
            self.steam_status_badge.set_kind("BRANCHÉ", "ok")
        elif st.supported:
            self.steam_status_badge.set_kind("NON BRANCHÉ", "muted")
        else:
            self.steam_status_badge.set_kind("STEAM ABSENT", "muted")
        self.steam_status_label.setText(st.message)
        if st.current:
            self.steam_current_label.setText(
                f"Option de lancement actuelle : {st.current}")
            self.steam_current_label.setVisible(True)
        else:
            self.steam_current_label.setVisible(False)
        self.unwire_btn.setEnabled(st.wired)
        # Le repli manuel suit l'exe choisi, indépendamment de tout branchement auto.
        self.steam_copy_line.setText(steamcfg.launch_line(exe))

    def _on_launcher_exe_edited(self) -> None:
        # Vide = on retombe sur sys.executable via `_launcher_exe`, d'où le strip sans
        # garde-fou : une chaîne vide est une valeur valide (« déduire à l'exécution »).
        self.ctx.settings.launcher_exe = self.launcher_exe_field.text().strip()
        self.ctx.save_settings()
        self._refresh_steam()

    def _on_browse_launcher_exe(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "Exécutable du launcher")
        if not chosen:
            return
        self.ctx.settings.launcher_exe = chosen
        self.ctx.save_settings()
        self.launcher_exe_field.setText(chosen)
        self._refresh_steam()

    def _on_wire(self) -> None:
        """Branche via `steamcfg.wire`. Affiche le message du cœur, refus compris.

        Le refus (Steam ouvert ou état inconnu) n'est pas masqué : c'est justement ce
        que l'utilisateur doit lire pour comprendre pourquoi coller la ligne à la main.
        """
        exe = self._launcher_exe()
        result = steamcfg.wire(exe, self.ctx.ledger,
                               steam_running=doctor.steam_processes_running())
        box = QMessageBox(self)
        box.setWindowTitle("Branchement Steam" if result.ok else "Branchement refusé")
        box.setText(result.message)
        box.setIcon(QMessageBox.Icon.Information if result.ok
                    else QMessageBox.Icon.Warning)
        box.exec()
        # `result.line` est toujours fourni (succès comme refus) : on garde le repli à jour.
        if result.line:
            self.steam_copy_line.setText(result.line)
        self._refresh_steam()
        self._render_ledger()

    def _on_unwire(self) -> None:
        result = steamcfg.unwire(self.ctx.ledger)
        box = QMessageBox(self)
        box.setWindowTitle("Débranchement" if result.ok else "Débranchement incomplet")
        box.setText(result.message)
        box.setIcon(QMessageBox.Icon.Information if result.ok
                    else QMessageBox.Icon.Warning)
        box.exec()
        self._refresh_steam()
        self._render_ledger()

    def _on_copy_launch_line(self) -> None:
        QApplication.clipboard().setText(self.steam_copy_line.text())

    def _on_stream_mode(self, checked: bool) -> None:
        self.ctx.settings.stream_mode = bool(checked)
        self.ctx.save_settings()

    def _on_review_logs(self, checked: bool) -> None:
        self.ctx.settings.review_logs_on_close = bool(checked)
        self.ctx.save_settings()

    def _uninstall_card(self) -> Card:
        card = Card()
        head = QHBoxLayout()
        title = QLabel("Désinstallation complète")
        title.setObjectName("SectionTitle")
        # Seul titre coloré de la page : le rouge est réservé à l'état, et « on va
        # défaire des choses dans votre dossier de jeu » en est un.
        title.setStyleSheet(f"color:{PALETTE.error};")
        head.addWidget(title, 1)
        head.addWidget(Badge("SENSIBLE", "error"), 0)
        card.body.addLayout(head)

        card.body.addWidget(_dim(
            "Défait toutes les modifications listées ci-dessus, puis efface le journal, "
            "les sauvegardes et les préférences du launcher."))

        keep = QLabel("Ne sont PAS touchés : " + " ".join(UNTOUCHED))
        keep.setWordWrap(True)
        keep.setStyleSheet(f"color:{PALETTE.text_dim};")
        card.body.addWidget(keep)

        card.body.addWidget(_dim(
            "Le détail exact de ce qui sera défait vous est présenté avant toute "
            "action, et il faudra le confirmer en le tapant."))

        row = QHBoxLayout()
        row.addStretch(1)
        self.uninstall_btn = QPushButton("Désinstaller le launcher…")
        self.uninstall_btn.setObjectName("Danger")
        self.uninstall_btn.clicked.connect(self._on_uninstall)
        row.addWidget(self.uninstall_btn, 0)
        card.body.addLayout(row)
        return card

    # --- journal ---

    @staticmethod
    def _clear(layout) -> None:
        """Vide un layout de ses widgets.

        `setParent(None)` avant `deleteLater()` n'est pas redondant : `deleteLater` ne
        détruit qu'au prochain tour de boucle d'événements, et d'ici là le widget reste
        un enfant visible. Sans ça, un rafraîchissement affiche brièvement l'ancien
        contenu par-dessus le nouveau.
        """
        while layout.count():
            item = layout.takeAt(0)
            if (w := item.widget()) is not None:
                w.setParent(None)
                w.deleteLater()
            elif (sub := item.layout()) is not None:
                SettingsPage._clear(sub)

    def _render_ledger(self) -> None:
        self._clear(self.ledger_card.body)
        pending = self.ctx.ledger.pending

        head = QHBoxLayout()
        title = QLabel("Modifications apportées par le launcher")
        title.setObjectName("SectionTitle")
        head.addWidget(title, 1)
        if pending:
            head.addWidget(Badge(f"{len(pending)} EN VIGUEUR", "accent"), 0)
            undo_all = QPushButton("Tout annuler")
            undo_all.clicked.connect(self._on_undo_all)
            head.addWidget(undo_all, 0)
        self.ledger_card.body.addLayout(head)

        if not pending:
            self.ledger_card.body.addWidget(_dim(
                "Le launcher n'a encore rien modifié. Rien à annuler, rien à défaire."))
            return

        # De la plus récente à la plus ancienne : c'est l'ordre dans lequel on cherche
        # « qu'est-ce que je viens de faire ? », et l'ordre où elles seront annulées.
        for entry in reversed(pending):
            self.ledger_card.body.addWidget(self._entry_row(entry))

    def _entry_row(self, entry: Entry) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 2, 0, 2)
        col.setSpacing(1)

        line = QHBoxLayout()
        line.setSpacing(METRICS.pad_sm)
        when = QLabel(_format_time(entry.at))
        when.setStyleSheet(f"font-family:{METRICS.mono}; color:{PALETTE.text_faint};")
        when.setMinimumWidth(120)
        line.addWidget(when, 0)
        what = QLabel(describe(entry))
        what.setWordWrap(True)
        line.addWidget(what, 1)
        col.addLayout(line)

        where = QLabel(str(entry.target))
        where.setObjectName("Dim")
        where.setWordWrap(True)
        where.setContentsMargins(120 + METRICS.pad_sm, 0, 0, 0)
        col.addWidget(where)
        return holder

    # --- actions de préférences ---

    def _sync_launch_warning(self) -> None:
        mode = LaunchMode(self.ctx.settings.launch_mode)
        self.launch_warning.setVisible(not mode.verified)

    def _on_launch_mode(self, index: int) -> None:
        self.ctx.settings.launch_mode = self.launch_combo.itemData(index)
        self.ctx.save_settings()
        self._sync_launch_warning()

    def _on_confirm_profile(self, checked: bool) -> None:
        self.ctx.settings.confirm_profile_apply = bool(checked)
        self.ctx.save_settings()

    def _on_advanced(self, checked: bool) -> None:
        self.ctx.settings.advanced_settings = bool(checked)
        self.ctx.save_settings()
        # Le changement ne se voit que sur la page Mods : c'est elle qui décide quels
        # réglages afficher. Le contexte la prévient.
        self.ctx.refresh()

    def _on_developer(self, checked: bool) -> None:
        self.ctx.settings.developer_mode = bool(checked)
        self.ctx.save_settings()
        # Fait réapparaître (ou disparaître) les mods restreints dans la page Mods.
        self.ctx.refresh()

    # --- annulation et désinstallation ---

    def refresh(self) -> None:
        self._render_ledger()

    def _on_undo_all(self) -> None:
        pending = self.ctx.ledger.pending
        if not pending:
            return
        confirm = QMessageBox.question(
            self, "Tout annuler",
            f"{len(pending)} modification(s) vont être défaites, de la plus récente "
            "à la plus ancienne.\n\nLe launcher reste installé et le journal est "
            "conservé.\n\nContinuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm is not QMessageBox.StandardButton.Yes:
            return

        results = self.ctx.ledger.undo()
        failed = [r for r in results if not r.ok]
        ReportDialog(
            "Annulation",
            "Toutes les modifications ont été défaites."
            if not failed else
            f"{len(failed)} opération(s) n'ont pas pu être défaites. Elles restent "
            "dans le journal : vous pouvez réessayer après avoir corrigé le problème.",
            results, self).exec()
        # L'état disque a bougé (fichiers restaurés, valeurs Lua remises) : les autres
        # pages doivent le relire.
        self.ctx.refresh()

    def _on_uninstall(self) -> None:
        """Plan, confirmation écrite, annulation, puis purge — dans cet ordre strict."""
        plan = self.ctx.ledger.uninstall_plan()
        prefs = Settings.path(self.ctx.data_dir)

        dialog = UninstallDialog(plan, prefs, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # 1. Défaire ce qui a été fait au jeu.
        results = self.ctx.ledger.undo()
        failed = [r for r in results if not r.ok]

        if results:
            ReportDialog(
                "Désinstallation — annulation des modifications",
                "Toutes les modifications ont été défaites."
                if not failed else
                f"{len(failed)} opération(s) n'ont pas pu être défaites.",
                results, self).exec()

        # 2. Un seul échec suffit à tout arrêter. Purger effacerait les sauvegardes
        #    qui permettent de réessayer : on préfère laisser le launcher en place
        #    avec un journal intact plutôt que rendre la réparation impossible.
        if failed:
            QMessageBox.warning(
                self, "Désinstallation interrompue",
                f"{len(failed)} modification(s) n'ont pas pu être défaites.\n\n"
                "Le journal et les sauvegardes ont été CONSERVÉS, et le launcher n'a "
                "pas été désinstallé. C'est volontaire : les effacer maintenant "
                "supprimerait justement ce qui permet de réessayer.\n\n"
                "Corrigez la cause indiquée dans le rapport (fichier ouvert ailleurs, "
                "dossier en lecture seule, jeu en cours d'exécution), puis relancez "
                "la désinstallation.")
            self.ctx.refresh()
            return

        # 3. Journal et sauvegardes, maintenant qu'ils ne servent plus à rien.
        removed = self.ctx.ledger.purge_self()

        # 4. Les préférences en dernier : elles ne touchent pas au jeu, leur perte
        #    n'empêcherait aucune réparation.
        try:
            if prefs.is_file():
                prefs.unlink()
                removed.append(str(prefs))
        except OSError as exc:
            removed.append(f"préférences non supprimées : {exc}")

        QMessageBox.information(
            self, "Désinstallation terminée",
            "Toutes les modifications du launcher ont été défaites, et ses données "
            "ont été effacées :\n\n" + "\n".join(f"• {r}" for r in removed) +
            "\n\nLe jeu, vos sauvegardes, vos paks et les mods que vous avez "
            "installés vous-même sont intacts.\n\n"
            "Vous pouvez maintenant fermer le launcher et supprimer son dossier.")
        self.ctx.refresh()
