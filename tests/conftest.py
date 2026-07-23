"""Fixtures communes : une fausse install de Fading Echo, jetable, par test.

Le poste de dev n'a ni Windows ni le jeu. Tout ce qui suit s'appuie donc sur
tools/make_fixture.py, qui reproduit les deux layouts réellement observés dans les
logs UE4SS du PC de jeu.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from fe_launcher.core import paths  # noqa: E402
from tools import make_fixture  # noqa: E402

SAMPLE_MODS = ["ue4ss-FEInfiniteCore", "ue4ss-FEMoonJump", "ue4ss-FESkins"]


def make_install(dest: Path, *, full: bool = True, with_ue4ss: bool = True,
                 mod_names: list[str] | None = None) -> paths.GameInstall:
    root = make_fixture.build_install(
        dest, full=full, with_ue4ss=with_ue4ss,
        mods=SAMPLE_MODS if mod_names is None else mod_names,
    )
    install = paths.inspect(root, source="fixture")
    assert install is not None, "le fixture doit produire une install détectable"
    return install


@pytest.fixture
def install(tmp_path: Path) -> paths.GameInstall:
    """Jeu complet + UE4SS imbriqué + 3 mods Lua activés."""
    return make_install(tmp_path / "lib")


@pytest.fixture
def demo_install(tmp_path: Path) -> paths.GameInstall:
    """Démo : UE4SS à plat, chemin ASCII pur."""
    return make_install(tmp_path / "libdemo", full=False)


def write_triplet(directory: Path, base: str, *, sizes: tuple[int, int, int] = (10, 20, 30),
                  parts: tuple[str, ...] = (".pak", ".ucas", ".utoc"),
                  disabled: bool = False) -> None:
    """Fabrique un triplet de pak. `parts` réduit permet de simuler un triplet incomplet."""
    directory.mkdir(parents=True, exist_ok=True)
    for ext, size in zip((".pak", ".ucas", ".utoc"), sizes):
        if ext not in parts:
            continue
        name = f"{base}{ext}" + (".disabled" if disabled else "")
        (directory / name).write_bytes(b"\0" * size)
