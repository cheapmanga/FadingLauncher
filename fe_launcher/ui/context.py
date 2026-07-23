"""État partagé de l'application, passé à toutes les pages.

Rassemble ce qui doit être unique dans le processus : l'installation sélectionnée, la
liste des mods, les préférences, et surtout le journal des mutations. Le journal en
particulier NE DOIT PAS être instancié par chaque page — deux instances écriraient dans
le même fichier sans se voir, et une annulation en perdrait la moitié.

Les pages ne rechargent pas les mods elles-mêmes : elles appellent `refresh()` et
écoutent `changed`. Sinon deux pages affichent des états divergents du même dossier —
typiquement, on désactive un mod dans la page Mods et le tableau de bord continue de le
compter comme actif.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core import doctor, mods as mods_mod, paths, settings as settings_mod
from ..core.ledger import Ledger
from ..core.paths import GameInstall
from ..core.settings import Settings, app_data_dir


class AppContext(QObject):
    """Modèle de l'application. Émet `changed` dès que l'état disque a bougé."""

    changed = Signal()
    install_changed = Signal()

    def __init__(self, *, data_dir: Path | None = None):
        super().__init__()
        self.data_dir = Path(data_dir) if data_dir else app_data_dir()
        self.settings: Settings = Settings.load(self.data_dir)
        self.ledger = Ledger(self.data_dir)
        self.installs: list[GameInstall] = []
        self.install: GameInstall | None = None
        self.mods: list[mods_mod.Mod] = []
        self.diagnoses: list[doctor.Diagnosis] = []

    # --- découverte ---

    def discover(self) -> None:
        extra = [Path(p) for p in self.settings.extra_game_roots]
        self.installs = paths.discover(extra_roots=extra)

        chosen = None
        if self.settings.last_install:
            chosen = next((i for i in self.installs
                           if str(i.root) == self.settings.last_install), None)
        # Sans install mémorisée, on PRÉFÈRE le jeu complet à la démo : quelqu'un qui a
        # les deux veut jouer au vrai jeu, pas à la démo. Ne rien préférer faisait
        # démarrer la démo au hasard de l'ordre de détection.
        self.select(chosen or self._default_install())

    def _default_install(self) -> "GameInstall | None":
        if not self.installs:
            return None
        from ..core.paths import Edition
        full = [i for i in self.installs if i.edition is Edition.FULL]
        if full:
            return full[0]
        return self.installs[0]

    def select(self, install: GameInstall | None) -> None:
        self.install = install
        if install is not None:
            self.settings.last_install = str(install.root)
            self.settings.save(self.data_dir)
        self.refresh()
        self.install_changed.emit()

    def add_root(self, root: Path) -> GameInstall | None:
        """Ajoute une install désignée à la main. Retourne None si ce n'en est pas une."""
        inst = paths.inspect(Path(root), source="manuel")
        if inst is None:
            return None
        key = str(inst.root)
        if key not in self.settings.extra_game_roots:
            self.settings.extra_game_roots.append(key)
            self.settings.save(self.data_dir)
        if not any(str(i.root) == key for i in self.installs):
            self.installs.append(inst)
        self.select(inst)
        return inst

    # --- rafraîchissement ---

    def refresh(self) -> None:
        """Relit l'état disque : mods puis diagnostics. Émet `changed`."""
        if self.install is None or self.install.ue4ss is None:
            self.mods = []
        else:
            self.mods = mods_mod.load(self.install.ue4ss)

        # Les diagnostics ne sont jamais mis en cache entre deux appels : une mise à
        # jour Steam peut recréer le dossier au nom grec pendant que l'outil est ouvert.
        self.diagnoses = (doctor.run(self.install, self.mods)
                          if self.install is not None else [])
        self.changed.emit()

    # --- vues pratiques ---

    @property
    def visible_mods(self) -> list[mods_mod.Mod]:
        """Mods à présenter, mode développeur pris en compte."""
        from ..core import moddocs  # import tardif : évite un cycle
        return moddocs.visible_mods(self.mods, developer_mode=self.settings.developer_mode)

    @property
    def enabled_mods(self) -> list[mods_mod.Mod]:
        return [m for m in self.mods if m.state is mods_mod.ModState.ENABLED]

    @property
    def conflicts(self) -> list[mods_mod.Conflict]:
        return mods_mod.conflicts(self.mods)

    def worst_level(self) -> doctor.Level:
        return doctor.worst(self.diagnoses) if self.diagnoses else doctor.Level.OK

    def save_settings(self) -> None:
        self.settings.save(self.data_dir)
