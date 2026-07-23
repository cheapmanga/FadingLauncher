"""Préférences du launcher, persistées hors du dossier du jeu.

Volontairement séparé du journal (`ledger`) : les préférences décrivent l'outil, le
journal décrit ce que l'outil a fait au jeu. Une désinstallation défait le second et
efface le premier, mais ce sont deux choses différentes — confondre les deux ferait
qu'annuler une modification remettrait aussi le thème par défaut.

Le mode développeur mérite un mot. Il ne débloque rien de dangereux pour la machine :
il rend visibles des mods qui touchent à l'outillage interne du studio (voir `moddocs`).
Il est désactivé par défaut et ne s'active qu'explicitement, parce qu'un utilisateur qui
découvre l'outil n'a aucune raison de tomber dessus par hasard.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_DIR_NAME = "FadingEchoLauncher"


def app_data_dir() -> Path:
    """Dossier de données du launcher, selon la plateforme."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / APP_DIR_NAME
    # Poste de dev / usage Linux : convention XDG.
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / APP_DIR_NAME


@dataclass
class Settings:
    """Préférences utilisateur."""

    #: Rend visibles les mods à accès restreint (voir moddocs.RESTRICTED).
    developer_mode: bool = False
    #: Montre les constantes brutes des mods au lieu des seuls réglages utiles.
    advanced_settings: bool = False
    #: Racines de jeu ajoutées à la main, quand la détection Steam ne suffit pas.
    extra_game_roots: list[str] = field(default_factory=list)
    #: Dernière install sélectionnée, pour rouvrir sur la même.
    last_install: str = ""
    #: Mode de lancement retenu.
    launch_mode: str = "steam"
    #: Avertir avant d'appliquer un profil qui écrase des réglages.
    confirm_profile_apply: bool = True
    #: Proposer de lire UE4SS.log à la fermeture du jeu.
    review_logs_on_close: bool = True
    #: Mode stream : quand le launcher est branché sur Steam et intercepte le
    #: lancement, se lancer en DISCRET (applique + lance + s'efface) au lieu d'ouvrir
    #: la fenêtre complète. Désactivé par défaut, comme demandé.
    stream_mode: bool = False
    #: Chemin de l'exe du launcher, pour composer l'option de lancement Steam.
    #: Vide = déduit à l'exécution.
    launcher_exe: str = ""

    # --- persistance ---

    @staticmethod
    def path(root: Path | None = None) -> Path:
        return (root or app_data_dir()) / "settings.json"

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        p = cls.path(root)
        if not p.is_file():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Des préférences illisibles ne doivent jamais empêcher l'outil de démarrer :
            # on repart des valeurs par défaut plutôt que de refuser de s'ouvrir.
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, root: Path | None = None) -> Path:
        p = self.path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, p)
        return p
