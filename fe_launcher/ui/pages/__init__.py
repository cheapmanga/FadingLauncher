"""Pages de l'interface, une par écran de la barre latérale.

Chaque page hérite de `main_window.Page` : elle reçoit l'`AppContext` et se rebranche
sur son signal `changed`. Elles ne se parlent jamais entre elles — cocher un mod dans
la page Mods se propage à la page Paramètres par le contexte, pas par une référence
directe. C'est ce qui permet d'en ajouter une sans toucher aux autres.
"""

from __future__ import annotations

from .bench_page import BenchPage
from .mods_page import ModsPage
from .skins_page import SkinsPage
from .saves_page import SavesPage
from .settings_page import SettingsPage

__all__ = [
    "SkinsPage","BenchPage", "ModsPage", "SavesPage", "SettingsPage"]
