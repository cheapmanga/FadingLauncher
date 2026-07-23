"""Exécution de sous-processus sans fenêtre parasite.

Sur Windows, `subprocess.run(["tasklist", …])` ouvre une fenêtre de console qui
apparaît puis disparaît aussitôt. Ce n'est pas gênant pour un appel isolé, mais le
launcher sonde les process du jeu TOUTES LES ~3 SECONDES pour détecter sa fermeture :
sans précaution, une fenêtre noire clignote en permanence pendant qu'on joue.

`CREATE_NO_WINDOW` demande à Windows de ne pas créer de console pour le process lancé.
Sur les autres plateformes, le drapeau n'existe pas et n'est pas nécessaire.
"""

from __future__ import annotations

import subprocess
import sys


def no_window_kwargs() -> dict:
    """kwargs à passer à subprocess pour ne PAS ouvrir de fenêtre de console."""
    if sys.platform == "win32":
        # 0x08000000 = CREATE_NO_WINDOW. On passe aussi un STARTUPINFO qui masque la
        # fenêtre, par ceinture-et-bretelles selon la version de Windows.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}
    return {}


def run_hidden(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` sans fenêtre de console. Mêmes arguments que `subprocess.run`."""
    return subprocess.run(cmd, **no_window_kwargs(), **kwargs)  # noqa: S603
