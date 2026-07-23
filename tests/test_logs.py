

"""Lecture d'UE4SS.log."""
from __future__ import annotations

from pathlib import Path

from fe_launcher.core import logs

LOGDIR = Path("/home/pb/devDocker/antoine/glitch-hunting/AZAMA logs et tout")


import os as _os
pytestmark = __import__("pytest").mark.skipif(not _os.path.isdir('/home/pb/devDocker/antoine/glitch-hunting'), reason="données locales absentes")

def test_session_normale():
    r = logs.read(None, path=LOGDIR / "UE4SS(2).log")
    assert r.exists and r.started
    assert len(r.mods) >= 10
    assert not r.errors
    # sortie d'un mod lue depuis le log
    assert any("core" in " ".join(m.output).lower() for m in r.mods)


def test_crash_unicode_detecte():
    r = logs.read(None, path=LOGDIR / "fini" / "UE4SS jeu complet.log")
    assert r.errors
    txt = " ".join(logs.explain(r))
    assert "non-ASCII" in txt or "caractère" in txt


def test_log_absent_degrade_proprement():
    r = logs.read(None, path=Path("/nexiste/pas/UE4SS.log"))
    assert not r.exists
    assert "Aucun journal" in r.headline


def test_disabled_dedoublonnes():
    r = logs.read(None, path=LOGDIR / "UE4SS(2).log")
    assert len(r.disabled) == len(set(r.disabled))
