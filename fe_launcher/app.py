"""Point d'entrée du launcher."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .ui.context import AppContext
from .ui.main_window import MainWindow
from .ui.pages import BenchPage, ModsPage, SavesPage, SettingsPage, SkinsPage
from .ui.theme import stylesheet


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Fading Echo Launcher")
    app.setStyleSheet(stylesheet())

    ctx = AppContext()
    ctx.discover()

    window = MainWindow(ctx)
    # Ordre délibéré : le tableau de bord d'abord (il est enregistré par MainWindow),
    # puis ce qu'on manipule au quotidien, et les réglages en dernier — c'est là que
    # vivent le mode développeur et la désinstallation.
    for page_cls in (ModsPage, SkinsPage, BenchPage, SavesPage, SettingsPage):
        window.register_page(page_cls(ctx))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
