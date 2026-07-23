"""Page Mods : la promesse « on ne touche jamais à du code », tenue à l'écran.

Pourquoi cette page est faite comme ça
--------------------------------------
Les mods de Fading Echo n'ont aucun fichier de configuration : activer un mod, c'est
créer un `enabled.txt`, et le régler, c'est réécrire un `local NOM = valeur` dans son
`main.lua`. Les deux opérations sont à la portée d'un éditeur de texte, et c'est
précisément ce qu'on veut éviter d'imposer. Ici, tout passe par une case à cocher et
des contrôles typés ; le Lua reste invisible.

**Deux colonnes plutôt qu'une liste et une fenêtre.** À gauche l'inventaire, à droite
la notice et les réglages du mod sélectionné. Une boîte de dialogue modale par mod
obligerait à ouvrir/fermer vingt fois pour comparer deux mods, et surtout empêcherait
de voir les conflits pendant qu'on règle.

**Les conflits sont affichés sur la ligne du mod, pas dans un panneau à part.** Ils
sont réels et fréquents dans ce projet : F7 est revendiquée par trois mods, F8 par
trois autres. Un panneau « 6 conflits » en haut de page ne dit pas lequel décocher ;
un badge « CONFLIT F7 » sur les trois lignes concernées, si. C'est le seul endroit de
l'application où l'utilisateur peut agir sur un conflit — le tableau de bord ne fait
que compter.

**Un mod non compilé est montré, pas masqué.** Trois mods C++ du projet n'ont jamais
été construits. Ils ont un `enabled.txt`, donc UE4SS les charge et échoue en silence.
Les cacher laisserait croire qu'ils n'existent pas ; les afficher comme actifs
laisserait croire qu'ils marchent. Ils reçoivent donc un badge propre et une phrase
qui dit que cocher n'aura aucun effet.

**Aucune écriture n'est faite sans journalisation.** Chaque modification de réglage
passe par `luaconf.write()` ET par `ledger.lua_set()`. Le journal est ce qui rend la
désinstallation capable de rendre les `.lua` dans leur état d'origine ; écrire sans
journaliser laisserait une trace indélébile dans un fichier que l'utilisateur a écrit
à la main.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ...core import luaconf, mods as mods_mod, moddocs
from ...core.mods import Mod, ModState
from ..context import AppContext
from ..main_window import Page
from ..theme import METRICS, PALETTE
from ..widgets import Badge, Card, ModDocPanel, PageHeader, build_editors, separator

#: Libellé et couleur de chaque état de mod. « NON COMPILÉ » plutôt que « CASSÉ » :
#: le mod n'est pas défectueux, il lui manque une étape de construction.
_STATE_BADGE = {
    ModState.ENABLED: ("ACTIF", "ok"),
    ModState.DISABLED: ("INACTIF", "muted"),
    ModState.BROKEN: ("NON COMPILÉ", "error"),
}


def display_name(mod: Mod) -> str:
    """`ue4ss-FEMoonJump` -> `FEMoonJump`.

    Le préfixe `ue4ss-` est une convention de dossier, identique sur les vingt mods :
    il n'apporte aucune information et mange la moitié de la largeur utile.
    """
    return mod.name.removeprefix("ue4ss-")


class ModRow(QFrame):
    """Une ligne de l'inventaire : case à cocher, état, conflits, touches.

    La ligne entière est cliquable pour la sélection, mais seule la case agit sur
    l'activation. Confondre les deux ferait qu'on activerait un mod en voulant lire
    sa notice — une erreur silencieuse qui ne se remarque qu'au lancement du jeu.
    """

    toggled_mod = Signal(str, bool)
    picked = Signal(str)

    def __init__(self, mod: Mod, conflicts: list[mods_mod.Conflict],
                 *, selected: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.mod_name = mod.name
        self.setObjectName("ModRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_selection(selected)

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_sm, METRICS.pad_sm,
                                METRICS.pad_sm, METRICS.pad_sm)
        root.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(METRICS.pad_sm)

        # La case est SANS TEXTE, et le nom du mod est un libellé distinct à côté.
        # Mettre le nom dans le texte de la case le rend cliquable : on active alors un
        # mod en croyant simplement le sélectionner pour lire sa notice. Vérifié — avec
        # `QCheckBox("FESkins")`, un clic jusqu'à 60 px du bord basculait l'état, et
        # d'autant plus loin que le nom est long. C'est une erreur silencieuse qui ne se
        # découvre qu'une fois en jeu, et elle invalide une campagne de mesure en cours.
        self.box = QCheckBox()
        # BROKEN veut dire « marqueur présent mais DLL absente » : la case est donc
        # bien cochée, c'est l'effet qui manque, pas l'activation.
        self.box.setChecked(mod.state in (ModState.ENABLED, ModState.BROKEN))
        self.box.toggled.connect(self._on_toggled)
        self.box.setToolTip("Activer ou désactiver ce mod")
        head.addWidget(self.box, 0)

        self.name_label = QLabel(display_name(mod))
        head.addWidget(self.name_label, 1)

        text, kind = _STATE_BADGE[mod.state]
        head.addWidget(Badge(text, kind), 0)
        root.addLayout(head)

        # Les conflits d'abord : c'est l'information qui demande une décision.
        if conflicts:
            root.addLayout(self._conflict_row(conflicts))

        if mod.state is ModState.BROKEN:
            warn = QLabel("Aucune bibliothèque compilée : cocher ce mod n'aura aucun "
                          "effet en jeu tant qu'il n'est pas construit.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color:{PALETTE.warn};")
            root.addWidget(warn)

        if (binding := self._bindings_text(mod)):
            keys = QLabel(binding)
            keys.setWordWrap(True)
            keys.setStyleSheet(f"font-family:{METRICS.mono}; color:{PALETTE.text_dim};")
            root.addWidget(keys)
        elif mod.state is not ModState.BROKEN:
            none = QLabel("Aucune touche ni commande")
            none.setObjectName("Dim")
            root.addWidget(none)

    # --- rendu ---

    @staticmethod
    def _bindings_text(mod: Mod) -> str:
        """Touches et commandes, relues dans le code du mod et non dans sa notice."""
        bits = []
        if mod.keybinds:
            bits.append(" ".join(mod.keybinds))
        if mod.commands:
            bits.append(" ".join(f"`{c}`" for c in mod.commands))
        return "   ·   ".join(bits)

    def _conflict_row(self, conflicts: list[mods_mod.Conflict]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(METRICS.pad_sm)
        # Au-delà de trois badges la ligne devient illisible ; le reste est compté.
        for c in conflicts[:3]:
            badge = Badge(f"CONFLIT {c.resource}", "error")
            badge.setToolTip(c.message)
            row.addWidget(badge, 0)
        if len(conflicts) > 3:
            more = QLabel(f"+{len(conflicts) - 3}")
            more.setObjectName("Dim")
            row.addWidget(more, 0)
        row.addStretch(1)
        return row

    def _apply_selection(self, selected: bool) -> None:
        border = PALETTE.accent if selected else PALETTE.border
        background = PALETTE.surface_alt if selected else PALETTE.surface
        self.setStyleSheet(
            f"#ModRow {{ background:{background}; border:1px solid {border};"
            f" border-radius:{METRICS.radius_sm}px; }}")

    # --- interaction ---

    def _on_toggled(self, checked: bool) -> None:
        # Cocher sélectionne aussi : après avoir activé un mod, l'utilisateur veut
        # presque toujours voir ce qu'il vient d'activer.
        self.picked.emit(self.mod_name)
        self.toggled_mod.emit(self.mod_name, checked)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — API Qt
        self.picked.emit(self.mod_name)
        super().mousePressEvent(event)


class ModsPage(Page):
    """Inventaire des mods à gauche, notice et réglages du mod choisi à droite."""

    title = "Mods"
    icon = "◆"

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(ctx, parent)
        self._selected: str | None = None
        self._filter = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(METRICS.pad_lg, METRICS.pad_lg,
                                METRICS.pad_lg, METRICS.pad_lg)
        root.setSpacing(METRICS.pad)

        self.header = PageHeader(
            "Mods",
            "Cochez pour activer. Tout se règle ici : aucun fichier à éditer.")
        # Bouton d'installation des mods embarqués : le launcher livre ses mods, ce
        # bouton les copie dans le jeu (ceux qui manquent) en une fois.
        self.install_btn = QPushButton("Installer les mods fournis")
        self.install_btn.clicked.connect(self._install_bundled)
        self.header.add_action(self.install_btn)
        root.addWidget(self.header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher un mod, une touche, une commande…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        root.addWidget(self.search)

        columns = QHBoxLayout()
        columns.setSpacing(METRICS.pad)

        # Colonne gauche : l'inventaire. Un peu plus étroite que le détail, qui doit
        # accueillir des phrases de notice et des libellés de réglage.
        left = QVBoxLayout()
        left.setSpacing(METRICS.pad_sm)
        self.count_label = QLabel()
        self.count_label.setObjectName("Dim")
        left.addWidget(self.count_label)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(METRICS.pad_sm)
        left.addWidget(self.list_holder)
        left.addStretch(1)
        columns.addLayout(left, 4)

        # Aligné en haut : sans ça, le panneau de détail s'étire sur toute la hauteur
        # de la liste et laisse un grand rectangle vide sous les réglages.
        self.detail_card = Card()
        self.detail_card.setSizePolicy(QSizePolicy.Policy.Preferred,
                                       QSizePolicy.Policy.Maximum)
        columns.addWidget(self.detail_card, 5, Qt.AlignmentFlag.AlignTop)

        root.addLayout(columns, 1)
        self.refresh()

    # --- helpers de rendu ---

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if (w := item.widget()) is not None:
                w.setParent(None)
                w.deleteLater()
            elif (sub := item.layout()) is not None:
                ModsPage._clear(sub)

    def _conflicts_by_mod(self) -> dict[str, list[mods_mod.Conflict]]:
        """Index conflit → mods concernés, pour pouvoir l'afficher ligne par ligne."""
        index: dict[str, list[mods_mod.Conflict]] = {}
        for c in self.ctx.conflicts:
            for name in c.mods:
                index.setdefault(name, []).append(c)
        return index

    def _matches(self, mod: Mod) -> bool:
        if not self._filter:
            return True
        haystack = " ".join([
            mod.name, mod.description,
            " ".join(mod.keybinds), " ".join(mod.commands),
        ]).lower()
        return self._filter in haystack

    # --- rafraîchissement ---

    def refresh(self) -> None:
        """Reconstruit l'inventaire et le détail à partir de l'état disque."""
        # `visible_mods` et non `mods` : les mods restreints restent masqués tant que
        # le mode développeur n'est pas activé dans les paramètres.
        visible = [m for m in self.ctx.visible_mods if self._matches(m)]
        # Les mods du projet d'abord, les mods livrés avec UE4SS ensuite. Par ordre
        # alphabétique strict, `ActorDumperMod` et `BPModLoaderMod` occupent le haut de
        # la liste alors que personne ne vient ici pour eux : ce qu'on cherche, ce sont
        # les mods Fading Echo, qui se retrouvent enterrés sous l'outillage d'UE4SS.
        visible.sort(key=lambda m: (not m.name.startswith("ue4ss-"), m.name.lower()))
        conflicts = self._conflicts_by_mod()

        # La sélection survit à un rafraîchissement tant que le mod reste affiché,
        # sinon le panneau de droite se viderait à chaque case cochée.
        names = {m.name for m in visible}
        if self._selected not in names:
            self._selected = visible[0].name if visible else None

        self._clear(self.list_layout)

        if self.ctx.install is None or not self.ctx.install.has_ue4ss:
            self._render_no_ue4ss()
            self._render_detail(None)
            return

        total = len(self.ctx.visible_mods)
        if self._filter:
            self.count_label.setText(f"{len(visible)} affiché(s) sur {total}")
        else:
            # Les mods non compilés sont comptés à part : les additionner aux actifs
            # annoncerait un nombre de mods opérants qui est faux.
            active = sum(1 for m in self.ctx.visible_mods
                         if m.state is ModState.ENABLED)
            broken = sum(1 for m in self.ctx.visible_mods
                         if m.state is ModState.BROKEN)
            text = f"{active} actif(s) sur {total}"
            if broken:
                text += f"   ·   {broken} non compilé(s), sans effet"
            self.count_label.setText(text)

        if not visible:
            empty = QLabel("Aucun mod ne correspond à cette recherche."
                           if self._filter else "Aucun mod installé.")
            empty.setObjectName("Dim")
            empty.setWordWrap(True)
            self.list_layout.addWidget(empty)

        for mod in visible:
            row = ModRow(mod, conflicts.get(mod.name, []),
                         selected=mod.name == self._selected)
            row.toggled_mod.connect(self._on_toggle)
            row.picked.connect(self._on_pick)
            self.list_layout.addWidget(row)

        self._render_detail(self._mod(self._selected))

    def _render_no_ue4ss(self) -> None:
        self.count_label.setText("")
        msg = QLabel("UE4SS n'est pas installé : aucun mod ne peut être chargé.\n"
                     "Le tableau de bord indique comment le mettre en place.")
        msg.setObjectName("Dim")
        msg.setWordWrap(True)
        self.list_layout.addWidget(msg)

    def _mod(self, name: str | None) -> Mod | None:
        return next((m for m in self.ctx.visible_mods if m.name == name), None)

    def _render_detail(self, mod: Mod | None) -> None:
        """Notice puis réglages du mod sélectionné.

        La notice vient d'abord : savoir à quoi sert un mod précède le réglage de ses
        constantes. L'ordre inverse mettrait « Void delay ms » devant quelqu'un qui ne
        sait pas encore ce qu'est un void.
        """
        self._clear(self.detail_card.body)

        if mod is None:
            hint = QLabel("Choisissez un mod à gauche pour voir sa notice et ses réglages.")
            hint.setObjectName("Dim")
            hint.setWordWrap(True)
            self.detail_card.body.addWidget(hint)
            self.detail_card.body.addStretch(1)
            return

        self.detail_card.body.addWidget(ModDocPanel(mod, moddocs.doc_for(mod)))
        self.detail_card.body.addWidget(separator())

        title = QLabel("Réglages")
        title.setObjectName("SectionTitle")
        self.detail_card.body.addWidget(title)

        if mod.script is None:
            no_script = QLabel(
                "Ce mod est écrit en C++ : ses réglages sont dans son code source, "
                "il n'y a rien à régler ici.")
            no_script.setObjectName("Dim")
            no_script.setWordWrap(True)
            self.detail_card.body.addWidget(no_script)
            self.detail_card.body.addStretch(1)
            return

        advanced = self.ctx.settings.advanced_settings
        if advanced:
            note = QLabel("Options avancées : toutes les constantes du mod sont "
                          "affichées, y compris les valeurs internes.")
            note.setObjectName("Dim")
            note.setWordWrap(True)
            self.detail_card.body.addWidget(note)

        editors_widget, _ = build_editors(
            mod.settings,
            lambda name, value, m=mod: self._on_setting(m, name, value),
            advanced=advanced,
        )
        self.detail_card.body.addWidget(editors_widget)
        self.detail_card.body.addStretch(1)

    # --- actions ---

    def _install_bundled(self) -> None:
        from ...core import modinstall
        inst = self.ctx.install
        if inst is None or inst.ue4ss is None:
            QMessageBox.warning(
                self, "UE4SS requis",
                "Les mods s'installent dans UE4SS, qui n'est pas présent. "
                "Installez d'abord UE4SS depuis le tableau de bord.")
            return
        missing = [m.name for m in modinstall.bundled_mods()
                   if not modinstall.is_installed(inst.ue4ss, m.name)]
        if not missing:
            QMessageBox.information(self, "Rien à installer",
                                    "Tous les mods fournis sont déjà installés.")
            return
        confirm = QMessageBox.question(
            self, "Installer les mods",
            f"{len(missing)} mod(s) fourni(s) vont être installés dans le jeu "
            f"(et UEHelpers, dont ils dépendent). C'est réversible depuis les "
            f"paramètres.\n\nContinuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm is not QMessageBox.StandardButton.Yes:
            return
        report = modinstall.install_all(inst.ue4ss, self.ctx.ledger, names=missing)
        QMessageBox.information(
            self, "Installation" if report.ok else "Installation incomplète",
            report.message)
        self.ctx.refresh()

    def _on_search(self, text: str) -> None:
        self._filter = text.strip().lower()
        self.refresh()

    def _on_pick(self, name: str) -> None:
        if name == self._selected:
            return
        self._selected = name
        self.refresh()

    def _on_toggle(self, name: str, checked: bool) -> None:
        mod = self._mod(name)
        if mod is None:
            return
        try:
            mods_mod.set_enabled(mod, checked)
        except OSError as exc:
            QMessageBox.warning(
                self, "Modification impossible",
                f"Impossible de {'activer' if checked else 'désactiver'} "
                f"{display_name(mod)} :\n\n{exc}")
        # Un refresh complet et non une mise à jour de la ligne : activer un mod peut
        # créer ou lever un conflit sur d'AUTRES lignes, qui doivent bouger aussi.
        self.ctx.refresh()

    def _on_setting(self, mod: Mod, name: str, value: object) -> None:
        """Écrit un réglage dans le `.lua` du mod, après l'avoir journalisé.

        L'ancienne valeur est relue sur le disque juste avant l'écriture plutôt que
        prise dans l'objet en mémoire : entre deux modifications, le fichier a pu
        changer (édition à la main, annulation partielle), et journaliser une valeur
        périmée rendrait l'annulation fausse plutôt qu'impossible — bien pire.
        """
        if mod.script is None:
            return
        current = luaconf.read(mod.script, name)
        if current is None:
            return
        if current.value == value:
            return  # rien à écrire : évite de gonfler le journal d'entrées vides

        # Journaliser AVANT d'écrire. Si l'écriture échoue, on a une entrée en trop —
        # sans danger. L'inverse perdrait la capacité de revenir à l'état d'origine.
        self.ctx.ledger.lua_set(
            mod.script, name, current.value, value,
            label=f"{display_name(mod)} — {name} : {current.value!r} → {value!r}",
            group="mod-settings")
        try:
            updated = luaconf.write(mod.script, name, value)
        except (OSError, KeyError, luaconf.NotEditable) as exc:
            QMessageBox.warning(
                self, "Réglage non enregistré",
                f"« {name} » n'a pas pu être écrit dans {mod.script.name} :\n\n{exc}")
            return

        # On met à jour l'objet en mémoire sans reconstruire la page : un refresh ici
        # détruirait le champ en cours de saisie et ferait perdre le focus à chaque
        # caractère tapé.
        if (existing := mod.setting(name)) is not None:
            existing.value = updated.value
            existing.raw_value = updated.raw_value
