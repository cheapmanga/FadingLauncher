"""Installation d'UE4SS et correctif du chemin grec, en une seule opération.

Ce module répond au bouton « Installer UE4SS » : il enchaîne, dans le bon ordre, tout ce
qu'il faut pour qu'un possesseur du jeu complet passe d'une install nue à une install
qui charge les mods.

    1. déposer UE4SS (dwmapi.dll + dossier ue4ss/) dans Binaries/Win64 ;
    2. corriger le chemin grec `Project Ygrό` qui, sinon, tue UE4SS au démarrage.

L'ordre compte : on installe UE4SS AVANT de renommer, parce que le renommage change le
chemin d'install ; l'inverse obligerait à retrouver le nouveau dossier.

Tout passe par le journal, donc l'ensemble est réversible et défait à la désinstallation.
La source d'UE4SS est un fichier .zip que l'utilisateur fournit (ou qui a été téléchargé
au préalable) : on ne code pas d'URL en dur, les liens de la build zDEV utilisée changent,
et un téléchargement silencieux d'un binaire injecté dans le jeu mérite que l'utilisateur
choisisse explicitement son fichier.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import doctor
from .ledger import Ledger
from .paths import GameInstall

LEDGER_GROUP = "ue4ss-setup"

# Fichiers/dossiers qui prouvent qu'une archive est bien UE4SS.
_UE4SS_MARKERS = ("dwmapi.dll", "UE4SS-settings.ini")


def _bundle_dir() -> Path:
    """Dossier du build UE4SS embarqué (l'install de référence, prouvée sur ce jeu)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "fe_launcher" / "resources" / "ue4ss_bundle"
    return Path(__file__).resolve().parent.parent / "resources" / "ue4ss_bundle"


def has_bundle() -> bool:
    b = _bundle_dir()
    return (b / "dwmapi.dll").is_file() and (b / "ue4ss" / "UE4SS-settings.ini").is_file()


def _foreign_mods(installed_mods: Path, bundle_mods: Path) -> set[str]:
    """Noms des dossiers de `Mods/` qui ne viennent PAS du build de référence.

    Réinstaller UE4SS ne doit pas emporter les mods que l'utilisateur a installés :
    ce sont deux choses distinctes dans l'interface (le bouton UE4SS et la case des
    mods), et les voir disparaître sans l'avoir demandé est une mauvaise surprise.
    Tout ce que le bundle ne fournit pas est donc préservé tel quel.
    """
    if not installed_mods.is_dir():
        return set()
    from_bundle = {d.name for d in bundle_mods.iterdir()} if bundle_mods.is_dir() else set()
    return {d.name for d in installed_mods.iterdir()
            if d.is_dir() and d.name not in from_bundle}


def _is_kept(f: Path, ue4ss_root: Path, kept: set[str]) -> bool:
    """Vrai si `f` appartient à un dossier de mod à préserver."""
    if not kept:
        return False
    try:
        rel = f.relative_to(ue4ss_root)
    except ValueError:
        return False
    return len(rel.parts) >= 2 and rel.parts[0] == "Mods" and rel.parts[1] in kept


def _prune_empty_dirs(root: Path) -> None:
    """Supprime les dossiers vides sous `root`, du plus profond vers la racine.

    Pas de journalisation : un dossier vide n'a aucun contenu à restaurer, et
    l'annulation des fichiers qu'il contenait recrée son arborescence au besoin.
    """
    for d in sorted((p for p in root.rglob("*") if p.is_dir()),
                    key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()  # ne réussit que s'il est vide
        except OSError:
            pass


def install_from_bundle(install: GameInstall, ledger: Ledger, report: SetupReport,
                        *, replace: bool = False) -> bool:
    """Installe le build UE4SS embarqué dans le jeu, structure NESTED exacte.

    C'est la voie normale : on copie l'install de référence — celle qui fonctionne
    réellement sur ce jeu, avec ses réglages (`GraphicsAPI = opengl`, `RenderMode =
    ExternalThread`, indispensables sur ce moteur DX12), ses templates de layout mémoire
    et ses signatures. Pas de téléchargement, pas de build au hasard.

    Structure posée, identique au PC de jeu :
        Win64/dwmapi.dll          (le proxy que le jeu charge)
        Win64/ue4ss/…             (UE4SS.dll, settings, Mods, templates, signatures)
    """
    if install.has_ue4ss and not replace:
        report.add("UE4SS déjà présent", True, "aucune réinstallation.")
        return True
    src = _bundle_dir()
    if not has_bundle():
        return False

    win64 = install.engine_dir

    # RÉINSTALLATION = vrai remplacement, pas un écrasement partiel. On SUPPRIME d'abord
    # l'ancien UE4SS (le dossier `ue4ss/` complet + `dwmapi.dll`) puis on réécrit à neuf.
    # Sinon les fichiers d'un ancien build qui n'existent pas dans le nouveau resteraient
    # (orphelins) et pourraient entrer en conflit. Chaque suppression passe par le journal
    # (sauvegardée, donc annulable). Les mods sont ensuite regérés par la case dédiée.
    if replace:
        # Sous Windows, supprimer un fichier verrouillé (dwmapi.dll chargée par le jeu
        # en cours, .ini tenu par un antivirus) lève PermissionError. Sans ce try, ça
        # remonterait jusqu'au slot Qt et l'assistant CRASHERAIT au lieu d'afficher un
        # rapport rouge. On rend l'échec propre, avec le conseil qui va bien.
        try:
            removed = 0
            kept = _foreign_mods(win64 / "ue4ss" / "Mods", src / "ue4ss" / "Mods")
            for old in (win64 / "ue4ss", win64 / "dwmapi.dll"):
                if old.is_dir():
                    for f in sorted(old.rglob("*"), reverse=True):
                        if f.is_file() and not _is_kept(f, old, kept):
                            ledger.delete_file(f, label=f"ancien UE4SS : {f.name}",
                                               group=LEDGER_GROUP)
                            removed += 1
                    # Supprimer les FICHIERS laisse l'arborescence de dossiers debout.
                    # Un `Mods/ue4ss-FECoreGiver/` vidé de son script reste un dossier :
                    # `modinstall.is_installed` le voyait comme installé et refusait de
                    # le reposer, et si son `enabled.txt` survivait, UE4SS le démarrait
                    # puis échouait sur « main.lua not found ». On balaie donc les
                    # dossiers devenus vides, du plus profond vers la racine.
                    _prune_empty_dirs(old)
                elif old.is_file():
                    ledger.delete_file(old, label=f"ancien UE4SS : {old.name}",
                                       group=LEDGER_GROUP)
                    removed += 1
            if removed:
                detail = f"{removed} fichier(s) supprimé(s) avant réécriture propre."
                if kept:
                    detail += f" {len(kept)} mod(s) installé(s) conservé(s)."
                report.add("Ancien UE4SS retiré", True, detail)
        except OSError as exc:
            report.add("Suppression de l'ancien UE4SS", False,
                       f"{exc} — fermez complètement le jeu et Steam, puis réessayez.")
            return False

    try:
        # 1. le proxy à la racine de Win64.
        ledger.create_file(win64 / "dwmapi.dll", (src / "dwmapi.dll").read_bytes(),
                           label="UE4SS : dwmapi.dll", group=LEDGER_GROUP)
        # 2. tout le reste dans Win64/ue4ss/, en préservant l'arborescence.
        ue4ss_src = src / "ue4ss"
        for f in ue4ss_src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(ue4ss_src)
                ledger.create_file(win64 / "ue4ss" / rel, f.read_bytes(),
                                   label=f"UE4SS : ue4ss/{rel}", group=LEDGER_GROUP)
    except OSError as exc:
        report.add("Installation d'UE4SS", False, str(exc))
        return False

    report.add("UE4SS installé", True,
               "build de référence posé : dwmapi.dll dans Win64\\, le reste dans "
               "Win64\\ue4ss\\ (avec templates, signatures et réglages OpenGL).")
    return True

# Dépôt officiel d'UE4SS. On vise la release `experimental-latest` (la nightly), pas la
# `latest` stable : c'est la nightly zDEV qui fonctionne sur ce jeu (fork UE 5.6.1). Le
# build de référence embarqué en vient — repli seulement, la source normale est le bundle.
UE4SS_RELEASES_API = ("https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/"
                      "experimental-latest")


@dataclass
class DownloadResult:
    ok: bool
    path: Path | None
    version: str = ""
    message: str = ""


def _pick_asset(assets: list[dict]) -> dict | None:
    """Choisit le meilleur .zip d'une release UE4SS.

    On préfère le build **zDEV** (`zDEV-UE4SS_v*.zip`), pas le standard. Fading Echo est
    un fork custom d'UE 5.6.1 : sans les dossiers `MemberVarLayoutTemplates` /
    `VTableLayoutTemplates` (présents dans zDEV, absents du build standard), UE4SS ne
    trouve pas la disposition mémoire du moteur et meurt à l'init — log à 0 octet, aucune
    console. Le build standard est plus léger mais ne démarre pas sur ce jeu. Vérifié.
    Les autres extras (`zCustomGameConfigs`, `zMapGenBP`) ne sont pas des builds complets.
    """
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    if not zips:
        return None
    zdev = [a for a in zips if a["name"].lower().startswith("zdev-ue4ss")]
    standard = [a for a in zips
                if a["name"].lower().startswith("ue4ss_")
                and not a["name"].lower().startswith("z")]
    return (zdev or standard or zips)[0]


def download_ue4ss(dest_dir: Path, *, timeout: int = 60) -> DownloadResult:
    """Télécharge la dernière release d'UE4SS depuis GitHub, dans `dest_dir`.

    L'utilisateur n'a plus rien à fournir : le launcher va chercher UE4SS tout seul.
    Échoue proprement (sans lever) en cas d'absence de réseau ou d'API indisponible —
    l'assistant propose alors de fournir un .zip à la main en repli.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(
            UE4SS_RELEASES_API,
            headers={"User-Agent": "fe-launcher",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            release = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return DownloadResult(False, None,
                              message=f"Téléchargement impossible (pas de réseau ?) : {exc}")

    asset = _pick_asset(release.get("assets", []))
    if asset is None:
        return DownloadResult(False, None, release.get("tag_name", ""),
                              "Aucune archive UE4SS dans la dernière release.")

    out = dest_dir / asset["name"]
    try:
        req = urllib.request.Request(asset["browser_download_url"],
                                     headers={"User-Agent": "fe-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as r, out.open("wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        return DownloadResult(False, None, release.get("tag_name", ""),
                              f"Échec du téléchargement de l'archive : {exc}")

    if not looks_like_ue4ss_zip(out):
        return DownloadResult(False, None, release.get("tag_name", ""),
                              "L'archive téléchargée ne ressemble pas à UE4SS.")
    return DownloadResult(True, out, release.get("tag_name", ""),
                          f"UE4SS {release.get('tag_name', '')} téléchargé.")


@dataclass
class SetupStep:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class SetupReport:
    ok: bool
    steps: list[SetupStep] = field(default_factory=list)
    message: str = ""

    def add(self, label: str, ok: bool, detail: str = "") -> None:
        self.steps.append(SetupStep(label, ok, detail))


def looks_like_ue4ss_zip(zip_path: Path) -> bool:
    """L'archive contient-elle bien UE4SS ? Évite d'extraire n'importe quoi dans le jeu."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = "\n".join(z.namelist()).lower()
    except (OSError, zipfile.BadZipFile):
        return False
    return all(m.lower() in names for m in _UE4SS_MARKERS)


def _safe_members(z: zipfile.ZipFile, dest: Path) -> list[zipfile.ZipInfo]:
    """Membres de l'archive dont l'extraction reste SOUS `dest`.

    Un zip peut contenir des chemins `../…` ou absolus (zip-slip) qui écriraient hors
    du dossier cible. On rejette ces membres plutôt que de leur faire confiance.
    """
    dest = dest.resolve()
    out = []
    for info in z.infolist():
        target = (dest / info.filename).resolve()
        if target == dest or dest in target.parents:
            out.append(info)
    return out


def install_ue4ss(install: GameInstall, zip_path: Path, ledger: Ledger,
                  report: SetupReport, *, replace: bool = False) -> bool:
    """Extrait UE4SS dans Binaries/Win64. Chaque fichier créé est journalisé.

    Par défaut on n'écrase pas un UE4SS déjà présent (la config pourrait être
    personnalisée). Avec `replace=True`, on réinstalle par-dessus : les fichiers d'UE4SS
    sont réécrits (sauvegardés au journal, donc réversibles), ce qui permet de remplacer
    un build cassé ou incomplet sans que l'utilisateur ait à nettoyer à la main. Les mods
    du dossier `Mods/` ne sont pas touchés (le zip ne les contient pas).
    """
    if install.has_ue4ss and not replace:
        report.add("UE4SS déjà présent", True, "aucune réinstallation.")
        return True
    if not looks_like_ue4ss_zip(zip_path):
        report.add("Archive UE4SS invalide", False,
                   "le .zip ne contient pas dwmapi.dll + UE4SS-settings.ini.")
        return False

    win64 = install.engine_dir
    # LAYOUT NESTED, tel que l'install qui fonctionne sur ce jeu : SEUL `dwmapi.dll` (le
    # proxy que le jeu charge) reste dans Win64 ; TOUT le reste — UE4SS.dll, settings,
    # Mods, templates de layout, signatures — va dans `Win64/ue4ss/`. Une extraction à
    # plat (tout dans Win64) fait que `dwmapi.dll` ne trouve pas `ue4ss/UE4SS.dll` et
    # UE4SS ne démarre pas (log à 0 octet). C'est le layout exact du PC de jeu.
    ue4ss_dir = win64 / "ue4ss"
    try:
        with zipfile.ZipFile(zip_path) as z:
            members = _safe_members(z, win64)
            for info in members:
                if info.is_dir():
                    continue
                name = info.filename
                # Le proxy reste à la racine de Win64 ; le reste descend dans ue4ss/.
                # Path(name).name : le proxy peut être sous un dossier de tête dans
                # certaines archives (`UE4SS/dwmapi.dll`). Comparer le nom complet le
                # raterait et dwmapi finirait dans ue4ss/, UE4SS ne se chargerait jamais.
                if Path(name).name.lower() == "dwmapi.dll":
                    target = win64 / "dwmapi.dll"
                else:
                    target = ue4ss_dir / name
                data = z.read(info)
                # create_file écrit puis journalise : réversible, et refuse d'écraser un
                # fichier existant sans le sauvegarder.
                ledger.create_file(target, data,
                                   label=f"UE4SS : {name}", group=LEDGER_GROUP)
    except (OSError, zipfile.BadZipFile) as exc:
        report.add("Extraction d'UE4SS", False, str(exc))
        return False

    report.add("UE4SS installé", True, "dwmapi.dll dans Win64\\, le reste dans Win64\\ue4ss\\")
    _deploy_signatures(win64, ledger, report)
    return True


def _bundled_signatures_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "fe_launcher" / "resources" / "ue4ss_signatures"
    return Path(__file__).resolve().parent.parent / "resources" / "ue4ss_signatures"


def _deploy_signatures(win64: Path, ledger: Ledger, report: SetupReport) -> None:
    """Dépose les signatures custom nécessaires à Fading Echo à côté d'UE4SS-settings.ini.

    Pourquoi c'est indispensable : sur Fading Echo, le scan automatique d'UE4SS ne trouve
    PAS `StaticConstructObject_Internal` (vérifié sur le log réel : il est résolu « <- Lua
    Script », donc par une signature custom). Sans elle, tout mod qui fait apparaître un
    objet — les cores, par exemple — échoue. Le zip standard d'UE4SS ne la contient pas.

    UE4SS cherche ces fichiers dans `UE4SS_Signatures/` À CÔTÉ de son `UE4SS-settings.ini`.
    On repère donc où le settings a atterri (à plat dans Win64, ou dans Win64/ue4ss) et on
    dépose la signature là.
    """
    src = _bundled_signatures_dir()
    if not src.is_dir():
        return
    # Où est UE4SS-settings.ini ? c'est le dossier de travail d'UE4SS.
    for base in (win64 / "ue4ss", win64):
        if (base / "UE4SS-settings.ini").is_file():
            target_dir = base / "UE4SS_Signatures"
            for sig in src.glob("*.lua"):
                ledger.create_file(target_dir / sig.name, sig.read_bytes(),
                                   label=f"signature UE4SS : {sig.name}", group=LEDGER_GROUP)
            report.add("Signatures Fading Echo", True,
                       "StaticConstructObject déployée (spawn d'objets).")
            return


def run(install: GameInstall, ledger: Ledger, *,
        ue4ss_zip: Path | None = None,
        download_dir: Path | None = None,
        allow_download: bool = True,
        reinstall: bool = False,
        probe=doctor.steam_processes_running) -> SetupReport:
    """Installe UE4SS puis corrige le chemin grec au besoin.

    Ordre des sources d'UE4SS, de la plus fiable à la moins :
      1. le build EMBARQUÉ (`install_from_bundle`) — l'install de référence prouvée sur ce
         jeu, avec ses réglages OpenGL et ses templates. C'est la voie normale.
      2. un `ue4ss_zip` fourni à la main (hors ligne, version précise).
      3. à défaut, téléchargement de la nightly zDEV (structure à plat, réglages par
         défaut : moins bon, mais mieux que rien).
    `reinstall=True` réinstalle par-dessus un UE4SS déjà présent.

    Retourne un rapport détaillé étape par étape.
    """
    report = SetupReport(ok=True)
    needs_ue4ss = reinstall or not install.has_ue4ss

    if needs_ue4ss and ue4ss_zip is None and has_bundle():
        # Voie normale : le build de référence embarqué.
        if not install_from_bundle(install, ledger, report, replace=reinstall):
            report.ok = False
    else:
        # Replis : zip fourni, sinon téléchargement de la nightly.
        if needs_ue4ss and ue4ss_zip is None and allow_download:
            dest = download_dir or (Path(ledger.root) / "downloads")
            dl = download_ue4ss(dest)
            report.add("Téléchargement d'UE4SS", dl.ok, dl.message)
            if dl.ok:
                ue4ss_zip = dl.path
            else:
                report.ok = False
        if ue4ss_zip is not None:
            if not install_ue4ss(install, Path(ue4ss_zip), ledger, report,
                                 replace=reinstall):
                report.ok = False
        elif not install.has_ue4ss:
            report.add("UE4SS à installer", False,
                       "build embarqué absent et téléchargement indisponible.")

    # 2. Correctif du chemin grec, uniquement s'il est nécessaire.
    if install.non_ascii_path:
        result = doctor.fix_non_ascii_path(install, probe=probe, ledger=ledger)
        report.add("Correctif du chemin non-ASCII", result.ok, result.message)
        if not result.ok:
            report.ok = False
    else:
        report.add("Chemin d'install", True, "déjà en ASCII, aucun correctif nécessaire.")

    done = sum(1 for s in report.steps if s.ok)
    report.message = (f"{done}/{len(report.steps)} étape(s) réussie(s). "
                      + ("Relancez le jeu via le launcher." if report.ok
                         else "Certaines étapes ont échoué — voir le détail."))
    return report
