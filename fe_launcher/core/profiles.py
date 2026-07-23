"""Profils : capturer un état complet du jeu, et le rejouer en un clic.

Pourquoi ce module existe
-------------------------
La configuration utile n'est jamais « un mod activé ». C'est une combinaison : quels
mods sont actifs, avec quelles constantes Lua, quels paks montés, à quel framerate.
Les cas réels sont « campagne ICG », « exploration OOB », « run propre » — et
aujourd'hui on passe d'un état à l'autre à la main, en éditant des .lua et en créant
des enabled.txt, ce qui est long et se trompe silencieusement.

Deux exigences non négociables
------------------------------
1. `apply()` rend un RAPPORT, jamais un booléen. Un profil touche des dizaines de
   fichiers ; « ça a échoué » est inutilisable. L'utilisateur doit lire quel mod n'a
   pas pu être activé et pourquoi, et le reste doit s'appliquer quand même — un mod
   absent de l'install ne fait pas capoter les neuf autres.

2. `apply()` est RÉVERSIBLE. Appliquer un profil réécrit les `Scripts/main.lua` de
   l'utilisateur, c'est-à-dire des fichiers qu'il a écrits à la main et dont il n'a
   pas de copie. Le rapport embarque donc un instantané complet de l'état d'AVANT
   (`ApplyReport.snapshot`), et `revert()` le rejoue. Le rapport est sérialisable pour
   que le retour arrière survive à une fermeture du launcher.

Les valeurs Lua capturées sont celles que `luaconf` sait relire ET réécrire (scalaires).
Une table Lua est en lecture seule : un profil ne peut donc pas la restaurer, et
`capture()` ne la met pas dans l'instantané — ne rien promettre qu'on ne sait pas tenir.

Les champs `fps_lock` et `save_slot` sont capturés et sérialisés mais PAS appliqués :
l'intégration des sauvegardes et du verrouillage de framerate viendra ensuite. `apply()`
le dit explicitement dans son rapport (statut SKIPPED) plutôt que de faire silence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from . import luaconf, mods, paks
from .mods import Conflict, Mod, ModState
from .paths import GameInstall

PROFILE_SUFFIX = ".json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Profile:
    """Un état reproductible du jeu, sérialisable en JSON."""

    name: str
    description: str = ""
    #  Mods à activer, par nom de dossier. Tout mod présent dans l'install et ABSENT
    #  de cette liste sera désactivé : un profil décrit un état complet, pas un delta.
    mods_enabled: list[str] = field(default_factory=list)
    #  {nom_du_mod: {CONSTANTE: valeur}} — appliqué via luaconf.write().
    lua_overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    #  Paks custom à activer, par nom de base du triplet. Les paks de base du jeu ne
    #  figurent jamais ici : ils ne sont ni capturés ni touchés.
    paks_enabled: list[str] = field(default_factory=list)
    fps_lock: int | None = None        # non appliqué pour l'instant
    save_slot: str | None = None       # non appliqué pour l'instant
    created: str = field(default_factory=_now)
    source_install: str = ""           # racine de l'install d'où vient la capture

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "mods_enabled": list(self.mods_enabled),
            "lua_overrides": {k: dict(v) for k, v in self.lua_overrides.items()},
            "paks_enabled": list(self.paks_enabled),
            "fps_lock": self.fps_lock,
            "save_slot": self.save_slot,
            "created": self.created,
            "source_install": self.source_install,
        }

    @staticmethod
    def from_dict(d: dict) -> "Profile":
        return Profile(
            name=d.get("name", "sans-nom"),
            description=d.get("description", ""),
            mods_enabled=list(d.get("mods_enabled", [])),
            lua_overrides={k: dict(v) for k, v in (d.get("lua_overrides") or {}).items()},
            paks_enabled=list(d.get("paks_enabled", [])),
            fps_lock=d.get("fps_lock"),
            save_slot=d.get("save_slot"),
            created=d.get("created", _now()),
            source_install=d.get("source_install", ""),
        )


# --- Rapport d'application -------------------------------------------------------

class ActionStatus(Enum):
    DONE = "done"
    SKIPPED = "skipped"      # volontairement non fait (protégé, non implémenté)
    FAILED = "failed"        # tenté, échoué — n'interrompt jamais le reste


@dataclass
class Action:
    """Une opération élémentaire du profil, avec son issue."""

    kind: str                # 'mod' | 'lua' | 'pak' | 'fps' | 'save'
    target: str              # nom du mod, du pak, ou 'MOD.CONSTANTE'
    detail: str              # phrase française prête à afficher
    status: ActionStatus = ActionStatus.DONE

    @property
    def ok(self) -> bool:
        return self.status is not ActionStatus.FAILED


@dataclass
class ApplyReport:
    """Ce que l'application d'un profil a fait, raté, et comment revenir en arrière."""

    profile: str
    actions: list[Action] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    #  État d'AVANT, capturé juste avant la première écriture. C'est la seule chose
    #  qui permette de rendre à l'utilisateur ses réglages Lua d'origine.
    snapshot: Profile | None = None
    at: str = field(default_factory=_now)

    def add(self, kind: str, target: str, detail: str,
            status: ActionStatus = ActionStatus.DONE) -> Action:
        action = Action(kind=kind, target=target, detail=detail, status=status)
        self.actions.append(action)
        return action

    @property
    def failures(self) -> list[Action]:
        return [a for a in self.actions if a.status is ActionStatus.FAILED]

    @property
    def skipped(self) -> list[Action]:
        return [a for a in self.actions if a.status is ActionStatus.SKIPPED]

    @property
    def applied(self) -> list[Action]:
        return [a for a in self.actions if a.status is ActionStatus.DONE]

    @property
    def ok(self) -> bool:
        """Tout ce qui devait être fait a été fait. Les conflits n'en font pas partie :
        ce sont des avertissements sur le résultat, pas des échecs d'écriture."""
        return not self.failures

    def summary(self) -> str:
        """Résumé français, une ligne par catégorie, destiné à l'UI."""
        lines = [
            f"Profil « {self.profile} » : {len(self.applied)} action(s) appliquée(s), "
            f"{len(self.failures)} échec(s), {len(self.skipped)} ignorée(s)."
        ]
        for action in self.failures:
            lines.append(f"  ÉCHEC  [{action.kind}] {action.target} : {action.detail}")
        for action in self.skipped:
            lines.append(f"  IGNORÉ [{action.kind}] {action.target} : {action.detail}")
        for conflict in self.conflicts:
            lines.append(f"  CONFLIT {conflict.message}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "at": self.at,
            "actions": [
                {"kind": a.kind, "target": a.target,
                 "detail": a.detail, "status": a.status.value}
                for a in self.actions
            ],
            "conflicts": [
                {"kind": c.kind, "resource": c.resource, "mods": list(c.mods)}
                for c in self.conflicts
            ],
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
        }

    @staticmethod
    def from_dict(d: dict) -> "ApplyReport":
        report = ApplyReport(profile=d.get("profile", ""), at=d.get("at", _now()))
        report.actions = [
            Action(kind=a["kind"], target=a["target"], detail=a["detail"],
                   status=ActionStatus(a.get("status", "done")))
            for a in d.get("actions", [])
        ]
        report.conflicts = [
            Conflict(kind=c["kind"], resource=c["resource"], mods=tuple(c["mods"]))
            for c in d.get("conflicts", [])
        ]
        snap = d.get("snapshot")
        report.snapshot = Profile.from_dict(snap) if snap else None
        return report

    def save(self, path: Path | str) -> None:
        """Écrit le rapport sur disque — pour que le retour arrière reste possible
        même si le launcher est fermé entre l'application et le regret."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                        encoding="utf-8")

    @staticmethod
    def load(path: Path | str) -> "ApplyReport":
        return ApplyReport.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# --- Capture ---------------------------------------------------------------------

def capture(install: GameInstall, name: str, description: str = "") -> Profile:
    """Photographie l'état courant de l'installation.

    On capture TOUS les réglages Lua éditables, pas seulement ceux qu'on s'apprête à
    changer : c'est ce qui permet à un instantané de servir de retour arrière complet,
    y compris si un `apply()` ultérieur touche à autre chose.
    """
    profile = Profile(name=name, description=description,
                      source_install=str(install.root))

    if install.ue4ss is not None:
        for mod in mods.load(install.ue4ss):
            # BROKEN = enabled.txt présent mais DLL absente. Du point de vue de l'état
            # du disque, le mod est bien « activé » : on le capture comme tel, sinon
            # un aller-retour capture/apply le désactiverait en douce.
            if mod.state in (ModState.ENABLED, ModState.BROKEN):
                profile.mods_enabled.append(mod.name)
            values = {s.name: s.value for s in mod.editable_settings}
            if values:
                profile.lua_overrides[mod.name] = values

    for pakset in paks.installed(install):
        if pakset.enabled and not pakset.is_base:
            profile.paks_enabled.append(pakset.name)

    return profile


# --- Application ------------------------------------------------------------------

def apply(profile: Profile, install: GameInstall, *,
          snapshot: bool = True) -> ApplyReport:
    """Applique un profil et retourne le détail de ce qui s'est passé.

    Ne lève jamais : chaque échec devient une action FAILED dans le rapport et
    l'application continue. Un mod du profil absent de l'install est signalé, pas fatal.

    `snapshot=True` capture l'état d'avant dans le rapport (`report.snapshot`), ce qui
    rend l'opération réversible via `revert()`. Ne le passer à False que pour un revert
    lui-même, pour ne pas empiler les instantanés.
    """
    report = ApplyReport(profile=profile.name)
    if snapshot:
        report.snapshot = capture(install, f"avant-{profile.name}",
                                  description=f"État capturé avant « {profile.name} »")

    _apply_mods(profile, install, report)
    _apply_lua(profile, install, report)
    _apply_paks(profile, install, report)

    if profile.fps_lock is not None:
        report.add("fps", str(profile.fps_lock),
                   "Verrouillage du framerate non implémenté : valeur enregistrée "
                   "dans le profil mais non appliquée au jeu.",
                   ActionStatus.SKIPPED)
    if profile.save_slot:
        report.add("save", profile.save_slot,
                   "Restauration de sauvegarde non implémentée : à venir.",
                   ActionStatus.SKIPPED)

    # Les conflits se calculent APRÈS coup, sur l'état réel du disque : un profil qui
    # active FEInfiniteCore et FEMoonJump crée un vrai conflit sur F7, et l'utilisateur
    # doit l'apprendre ici plutôt qu'en jeu quand une touche déclenche deux actions.
    if install.ue4ss is not None:
        report.conflicts = mods.conflicts(mods.load(install.ue4ss))

    return report


def _apply_mods(profile: Profile, install: GameInstall, report: ApplyReport) -> None:
    if install.ue4ss is None:
        report.add("mod", "*", "UE4SS n'est pas installé : aucun mod ne peut être activé.",
                   ActionStatus.FAILED)
        return

    present = {m.name: m for m in mods.load(install.ue4ss)}
    wanted = set(profile.mods_enabled)

    for missing in sorted(wanted - present.keys()):
        # Volontairement non fatal : un profil partagé entre deux PC référence souvent
        # un mod que celui-ci n'a pas. On le dit, et on applique tout le reste.
        report.add("mod", missing,
                   "Mod absent de cette installation : il n'a pas pu être activé.",
                   ActionStatus.FAILED)

    for name, mod in sorted(present.items()):
        target = name in wanted
        already = mod.state in (ModState.ENABLED, ModState.BROKEN)
        if target == already:
            continue
        try:
            state = mods.set_enabled(mod, target)
        except OSError as exc:
            report.add("mod", name,
                       f"{'Activation' if target else 'Désactivation'} impossible : {exc}",
                       ActionStatus.FAILED)
            continue
        if target and state is ModState.BROKEN:
            report.add("mod", name,
                       "Activé, mais inopérant : ce mod C++ n'a pas de DLL compilée.",
                       ActionStatus.DONE)
        else:
            report.add("mod", name, "Activé." if target else "Désactivé.")


def _apply_lua(profile: Profile, install: GameInstall, report: ApplyReport) -> None:
    if install.ue4ss is None:
        return
    present = {m.name: m for m in mods.load(install.ue4ss)}

    for mod_name, overrides in sorted(profile.lua_overrides.items()):
        mod: Mod | None = present.get(mod_name)
        if mod is None:
            report.add("lua", mod_name,
                       "Mod absent : ses réglages n'ont pas pu être appliqués.",
                       ActionStatus.FAILED)
            continue
        if mod.script is None:
            report.add("lua", mod_name,
                       "Ce mod n'a pas de Scripts/main.lua : aucun réglage à écrire.",
                       ActionStatus.SKIPPED)
            continue

        for const, value in sorted(overrides.items(), key=lambda kv: kv[0]):
            label = f"{mod_name}.{const}"
            current = luaconf.read(mod.script, const)
            if current is not None and current.value == value:
                continue  # rien à écrire : on n'ouvre pas le fichier pour rien
            try:
                updated = luaconf.write(mod.script, const, value)
            except KeyError:
                report.add("lua", label,
                           "Constante introuvable dans le fichier du mod "
                           "(le mod a peut-être changé de version).",
                           ActionStatus.FAILED)
            except luaconf.NotEditable as exc:
                report.add("lua", label, str(exc), ActionStatus.SKIPPED)
            except OSError as exc:
                report.add("lua", label, f"Écriture impossible : {exc}",
                           ActionStatus.FAILED)
            else:
                report.add("lua", label, f"Réglé sur {updated.raw_value}.")


def _apply_paks(profile: Profile, install: GameInstall, report: ApplyReport) -> None:
    present = paks.installed(install)
    wanted = set(profile.paks_enabled)

    for missing in sorted(wanted - {p.name for p in present}):
        report.add("pak", missing,
                   "Pak absent de Content/Paks : installez-le depuis la bibliothèque.",
                   ActionStatus.FAILED)

    for pakset in present:
        if pakset.is_base:
            continue  # jamais touché — les désactiver casse le démarrage du jeu
        target = pakset.name in wanted
        if target == pakset.enabled:
            continue
        try:
            paks.set_enabled(pakset, target)
        except paks.IncompletePak as exc:
            report.add("pak", pakset.name, str(exc), ActionStatus.FAILED)
        except paks.PakError as exc:
            report.add("pak", pakset.name, str(exc), ActionStatus.FAILED)
        else:
            report.add("pak", pakset.name, "Activé." if target else "Désactivé.")


def revert(report: ApplyReport, install: GameInstall) -> ApplyReport:
    """Rejoue l'instantané d'un rapport pour revenir à l'état d'avant.

    Retourne un nouveau rapport : le retour arrière peut lui aussi échouer partiellement
    (un fichier verrouillé parce que le jeu tourne, par exemple), et l'utilisateur doit
    le savoir aussi précisément que pour l'application.
    """
    if report.snapshot is None:
        out = ApplyReport(profile=f"retour-{report.profile}")
        out.add("mod", "*",
                "Aucun instantané n'a été pris lors de l'application : "
                "retour arrière impossible.",
                ActionStatus.FAILED)
        return out
    return apply(report.snapshot, install, snapshot=False)


# --- Persistance -------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    """Nom de fichier sûr à partir d'un nom de profil libre (« campagne ICG »)."""
    keep = [c if (c.isalnum() or c in " -_") else "_" for c in name.strip()]
    cleaned = "".join(keep).strip().replace(" ", "-")
    return cleaned or "profil"


def path_for(directory: Path | str, name: str) -> Path:
    return Path(directory) / (_safe_filename(name) + PROFILE_SUFFIX)


def save(profile: Profile, directory: Path | str) -> Path:
    """Écrit le profil en JSON et retourne le chemin du fichier."""
    path = path_for(directory, profile.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load(path: Path | str) -> Profile:
    return Profile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def list_profiles(directory: Path | str) -> list[Profile]:
    """Tous les profils lisibles d'un dossier, triés par nom.

    Un fichier illisible ou corrompu est ignoré plutôt que fatal : un JSON tronqué ne
    doit pas empêcher l'utilisateur d'accéder à ses autres profils.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out: list[Profile] = []
    for path in sorted(directory.glob(f"*{PROFILE_SUFFIX}")):
        try:
            out.append(load(path))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda p: p.name.lower())


def delete(directory: Path | str, name: str) -> bool:
    """Supprime un profil. True s'il existait."""
    path = path_for(directory, name)
    if path.is_file():
        path.unlink()
        return True
    return False
