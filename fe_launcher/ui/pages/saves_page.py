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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

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
            "Aucune édition de sauvegarde n'est proposée — ni débloquer une zone, ni "
            "ajouter des objets, ni changer un compteur. Uniquement la copie et la "
            "restauration de fichiers entiers. Ce n'est pas une limite technique qu'on "
            "lèvera plus tard : le format de ces sauvegardes contient un cadrage entre "
            "objets qui n'est pas rétro-conçu, et toute écriture qui change une "
            "longueur le décale. Le fichier reste chargeable en apparence et casse "
            "plus tard, sans message. Une copie de fichier, elle, est exacte à l'octet "
            "près.")
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
