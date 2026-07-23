"""Gestion des paks custom : le mod « lourd », celui qui remplace des assets du jeu.

Ce que l'on sait, et d'où ça vient
----------------------------------
VÉRIFIÉ — les paks se déposent dans `<install>\\UE_YGRO\\Content\\Paks\\`
(`GameInstall.paks_dir`). C'est le seul emplacement sourcé.

VÉRIFIÉ — un pakchunk modifié y est chargé sans aucun contrôle d'intégrité : le
conteneur du jeu n'est ni signé ni chiffré. C'est ce qui rend le modding d'assets
possible, et c'est aussi pourquoi ce module doit être prudent : rien côté jeu ne
rattrapera une erreur d'écriture, elle se manifestera par un crash au démarrage.

VÉRIFIÉ — un pak n'est pas un fichier mais un TRIPLET indissociable :
    <base>.pak + <base>.ucas + <base>.utoc
Les trois partagent le même nom de base. Le `.pak` est un conteneur quasi vide, le
`.utoc` est la table des matières et le `.ucas` porte les données. En manipuler un
sans les autres produit un état corrompu — d'où le fait que TOUTE opération de ce
module traite les trois ensemble, avec restauration si l'une échoue à mi-chemin.

Ce que l'on ne sait PAS (hypothèses, non testées sur Fading Echo)
-----------------------------------------------------------------
HYPOTHÈSE — le suffixe `_P` (« patch ») donnerait une priorité de montage supérieure.
C'est la convention UE4/UE5 générale, mais elle n'a pas été vérifiée sur ce jeu.
On l'expose donc en INFORMATION (`PakSet.patch_suffix`) et on ne code AUCUNE logique
de tri ou de renommage automatique qui en dépende.

HYPOTHÈSE — le sous-dossier `~mods` serait scanné en plus de `Paks/`. Non vérifié ici :
on installe donc à plat dans `Paks/`, qui est le seul chemin sourcé.

HYPOTHÈSE — `LogicMods/` serait le dossier des paks de blueprints chargés par
BPModLoaderMod. Le mod existe bien dans le `mods.txt` observé, mais le lien avec ce
dossier n'a pas été vérifié sur cette install.

Cas réel à garder en tête : dans la bibliothèque de l'utilisateur, `AA_Alien_P.*` et
`pakchunk10-Windows.*` sont le MÊME contenu sous deux nommages (tailles identiques).
Installer les deux revient probablement à monter deux fois le même mod — d'où
`duplicates()`, qui le signale avant que l'utilisateur ne s'en rende compte en jeu.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import GameInstall

# Les trois extensions d'un triplet, dans l'ordre où on les manipule.
PAK_PARTS = (".pak", ".ucas", ".utoc")

# Même convention que mods.py : on renomme plutôt que supprimer. Un pak pèse des
# centaines de Mo — le supprimer pour le « désactiver » serait à la fois lent et
# destructeur, alors qu'un renommage est instantané et réversible.
DISABLED_SUFFIX = ".disabled"

# Paks de base livrés avec le jeu. Les désactiver, c'est empêcher le jeu de démarrer,
# et l'utilisateur n'a aucun moyen simple de deviner que c'est la cause.
# VÉRIFIÉ : `UE_YGRO-Windows.*` est le conteneur de base observé dans Content/Paks.
BASE_PREFIXES = ("UE_YGRO-Windows", "pakchunk0-Windows", "global")


class PakError(Exception):
    """Erreur de gestion de paks. Le message est destiné à l'utilisateur (français)."""


class ProtectedPak(PakError):
    """Opération refusée sur un pak de base du jeu."""


class IncompletePak(PakError):
    """Le triplet n'est pas complet : opération refusée pour ne pas figer un état sale."""


@dataclass
class PakSet:
    """Un triplet .pak/.ucas/.utoc partageant le même nom de base.

    Les chemins pointent vers les fichiers TELS QU'ILS SONT sur disque, suffixe
    `.disabled` compris. Ne jamais reconstruire un chemin à partir de `name` seul.
    """

    name: str                       # nom de base, sans extension ni suffixe
    directory: Path
    pak: Path | None = None
    ucas: Path | None = None
    utoc: Path | None = None
    size: int = 0                   # somme des parties présentes, en octets
    enabled: bool = True

    @property
    def parts(self) -> list[Path]:
        """Les fichiers réellement présents, dans l'ordre PAK_PARTS."""
        return [p for p in (self.pak, self.ucas, self.utoc) if p is not None]

    @property
    def missing(self) -> list[str]:
        """Extensions manquantes du triplet."""
        return [
            ext for ext, p in zip(PAK_PARTS, (self.pak, self.ucas, self.utoc))
            if p is None
        ]

    @property
    def complete(self) -> bool:
        """Le triplet est-il entier ? Un triplet incomplet est un état corrompu :
        le jeu peut refuser de démarrer, sans indiquer quel fichier manque."""
        return not self.missing

    @property
    def half_disabled(self) -> bool:
        """Les parties ne sont pas toutes dans le même état (renommage interrompu).

        État à signaler haut et fort : le jeu voit alors un triplet amputé, et le
        message d'erreur qu'il produit ne mentionne pas le pak fautif.
        """
        states = {p.name.endswith(DISABLED_SUFFIX) for p in self.parts}
        return len(states) > 1

    @property
    def is_base(self) -> bool:
        """Pak livré avec le jeu — à ne jamais désactiver ni supprimer."""
        low = self.name.lower()
        return any(low.startswith(p.lower()) for p in BASE_PREFIXES)

    @property
    def patch_suffix(self) -> bool:
        """Le nom finit-il par `_P` ?

        HYPOTHÈSE, non vérifiée sur ce jeu : ce suffixe donnerait une priorité de
        montage supérieure. Purement informatif — aucune logique du module n'en dépend.
        """
        return self.name.endswith("_P")

    @property
    def status(self) -> str:
        """Résumé lisible pour l'UI."""
        if not self.complete:
            return f"incomplet — il manque {', '.join(self.missing)}"
        if self.half_disabled:
            return "état incohérent — parties activées et désactivées mélangées"
        if self.is_base:
            return "pak de base du jeu"
        return "activé" if self.enabled else "désactivé"


def _split(filename: str) -> tuple[str, str, bool] | None:
    """`AA_Alien_P.ucas.disabled` -> ('AA_Alien_P', '.ucas', False). None si hors sujet."""
    name = filename
    enabled = True
    if name.endswith(DISABLED_SUFFIX):
        name = name[: -len(DISABLED_SUFFIX)]
        enabled = False
    for ext in PAK_PARTS:
        if name.lower().endswith(ext):
            return name[: -len(ext)], ext, enabled
    return None


def scan(directory: Path | str) -> list[PakSet]:
    """Regroupe en triplets tout ce qu'un dossier contient, trié par nom.

    Utilisé pour `Content/Paks` comme pour la bibliothèque locale : c'est le même
    format de dossier des deux côtés.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []

    sets: dict[str, PakSet] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []

    for entry in entries:
        if not entry.is_file():
            continue
        parsed = _split(entry.name)
        if parsed is None:
            continue
        base, ext, enabled = parsed
        ps = sets.get(base)
        if ps is None:
            ps = sets[base] = PakSet(name=base, directory=directory, enabled=enabled)
        attr = ext.lstrip(".")
        previous = getattr(ps, attr)
        if previous is not None and not enabled:
            # `X.utoc` ET `X.utoc.disabled` coexistent : reliquat d'un renommage
            # interrompu ou d'une manip manuelle. C'est le fichier ACTIF qui compte
            # pour le jeu, on garde donc celui-là et on ignore la copie désactivée.
            continue
        setattr(ps, attr, entry)
        try:
            ps.size += entry.stat().st_size
        except OSError:
            pass
        # Un triplet à moitié renommé est possible (renommage interrompu). On le
        # considère désactivé dès qu'une partie l'est : c'est l'état le plus sûr à
        # afficher, et `complete`/`consistent` signalent la vraie anomalie.
        if not enabled:
            ps.enabled = False

    return [sets[k] for k in sorted(sets, key=str.lower)]


def installed(install: GameInstall) -> list[PakSet]:
    """Les paks présents dans `Content/Paks` de l'installation."""
    return scan(install.paks_dir)


def available(library_dir: Path | str) -> list[PakSet]:
    """Les paks d'une bibliothèque locale (dossier où l'utilisateur range ses paks)."""
    return scan(library_dir)


def find(paksets: list[PakSet], name: str) -> PakSet | None:
    for ps in paksets:
        if ps.name == name:
            return ps
    return None


def duplicates(paksets: list[PakSet]) -> list[tuple[PakSet, ...]]:
    """Groupes de paks probablement identiques, d'après la taille de chaque partie.

    HEURISTIQUE assumée : on compare des tailles, pas des empreintes. Hacher 300 Mo
    à chaque rafraîchissement de l'UI serait disproportionné, et une collision de
    tailles sur les TROIS parties d'un pak est improbable. À traiter comme un
    avertissement (« ces deux paks semblent identiques »), jamais comme une certitude.
    """
    groups: dict[tuple, list[PakSet]] = {}
    for ps in paksets:
        if not ps.complete:
            continue
        sig = tuple(
            p.stat().st_size if p and p.is_file() else -1
            for p in (ps.pak, ps.ucas, ps.utoc)
        )
        groups.setdefault(sig, []).append(ps)
    return [tuple(g) for g in groups.values() if len(g) > 1]


# --- Écritures ------------------------------------------------------------------

def _rename_all(pairs: list[tuple[Path, Path]]) -> None:
    """Renomme une liste (source, destination) ou ne renomme rien.

    C'est le cœur de la sûreté du module : si le 2e des 3 renommages échoue (fichier
    verrouillé par le jeu qui tourne, disque plein, droits), on remet en place ce qui
    a déjà bougé avant de propager l'erreur. Sinon on laisserait un triplet mi-activé
    mi-désactivé, c'est-à-dire un jeu qui ne démarre plus.
    """
    done: list[tuple[Path, Path]] = []
    try:
        for src, dst in pairs:
            if dst.exists():
                raise PakError(f"Le fichier de destination existe déjà : {dst.name}")
            src.rename(dst)
            done.append((src, dst))
    except (OSError, PakError) as exc:
        for src, dst in reversed(done):
            try:
                dst.rename(src)
            except OSError:  # pragma: no cover — on ne peut plus rien garantir
                raise PakError(
                    f"Échec du renommage ({exc}), ET la restauration a échoué. "
                    f"Le pak est dans un état incohérent dans {src.parent} — "
                    "vérifiez les fichiers .pak/.ucas/.utoc à la main avant de lancer le jeu."
                ) from exc
        raise PakError(f"Opération annulée, rien n'a été modifié : {exc}") from exc


def set_enabled(pakset: PakSet, enabled: bool, *, force: bool = False) -> PakSet:
    """Active ou désactive un triplet en renommant ses TROIS fichiers, ou aucun.

    Désactiver = suffixer chaque partie de `.disabled`. Activer = retirer le suffixe.
    On ne supprime jamais : un pak pèse des centaines de Mo et l'utilisateur ne l'a
    pas forcément conservé ailleurs.

    Refuse de désactiver un pak de base du jeu (erreur irréversible pour l'utilisateur :
    le jeu ne démarre plus et rien ne lui dira pourquoi) et refuse d'ACTIVER un triplet
    incomplet, sauf `force=True`. Désactiver un triplet incomplet reste permis : c'est
    une opération de réparation.
    """
    if pakset.is_base and not enabled and not force:
        raise ProtectedPak(
            f"« {pakset.name} » est un pak de base de Fading Echo. Le désactiver "
            "empêcherait le jeu de démarrer ; l'opération est bloquée."
        )
    if enabled and not pakset.complete and not force:
        raise IncompletePak(
            f"« {pakset.name} » est incomplet (il manque {', '.join(pakset.missing)}). "
            "Activer un triplet partiel peut empêcher le jeu de démarrer."
        )

    pairs: list[tuple[Path, Path]] = []
    for part in pakset.parts:
        if enabled and part.name.endswith(DISABLED_SUFFIX):
            pairs.append((part, part.with_name(part.name[: -len(DISABLED_SUFFIX)])))
        elif not enabled and not part.name.endswith(DISABLED_SUFFIX):
            pairs.append((part, part.with_name(part.name + DISABLED_SUFFIX)))

    _rename_all(pairs)

    # On relit le dossier plutôt que de patcher l'objet : c'est l'état du disque qui
    # fait foi, et le dossier a pu changer entre-temps.
    refreshed = find(scan(pakset.directory), pakset.name)
    return refreshed if refreshed is not None else pakset


def install_pak(pakset: PakSet, install: GameInstall, *, overwrite: bool = False) -> PakSet:
    """Copie un triplet de la bibliothèque vers `Content/Paks`.

    Copie sous des noms temporaires puis renomme : tant que la copie n'est pas finie,
    le jeu ne peut pas tomber sur un `.ucas` tronqué. Si une copie échoue, les fichiers
    temporaires déjà écrits sont supprimés et le dossier du jeu reste tel qu'il était.
    """
    if not pakset.complete:
        raise IncompletePak(
            f"« {pakset.name} » est incomplet (il manque {', '.join(pakset.missing)}) — "
            "installation refusée : le jeu pourrait ne plus démarrer."
        )

    dest_dir = install.paks_dir
    dest_dir.mkdir(parents=True, exist_ok=True)

    existing = find(scan(dest_dir), pakset.name)
    if existing is not None and not overwrite:
        raise PakError(f"« {pakset.name} » est déjà installé dans Content/Paks.")

    staged: list[tuple[Path, Path]] = []   # (temporaire, définitif)
    try:
        for src in pakset.parts:
            # Le nom source peut porter `.disabled` : on installe toujours actif.
            final_name = src.name
            if final_name.endswith(DISABLED_SUFFIX):
                final_name = final_name[: -len(DISABLED_SUFFIX)]
            tmp = dest_dir / (final_name + ".part")
            shutil.copyfile(src, tmp)
            staged.append((tmp, dest_dir / final_name))
    except OSError as exc:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise PakError(f"Échec de la copie de « {pakset.name} » : {exc}") from exc

    if existing is not None:
        # overwrite : on retire l'ancien seulement une fois le nouveau intégralement
        # copié sur le disque de destination.
        for part in existing.parts:
            part.unlink(missing_ok=True)

    try:
        _rename_all(staged)
    except PakError:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise

    refreshed = find(scan(dest_dir), pakset.name)
    if refreshed is None:  # pragma: no cover — incohérent avec ce qui précède
        raise PakError(f"« {pakset.name} » copié mais introuvable après relecture.")
    return refreshed


def uninstall(pakset: PakSet, *, force: bool = False) -> None:
    """Supprime les trois fichiers d'un pak de `Content/Paks`.

    Refuse les paks de base : leur suppression oblige à vérifier l'intégrité des
    fichiers via Steam, et rien dans le jeu n'indiquera la cause du problème.
    """
    if pakset.is_base and not force:
        raise ProtectedPak(
            f"« {pakset.name} » est un pak de base de Fading Echo : suppression bloquée. "
            "Il faudrait une vérification des fichiers par Steam pour le récupérer."
        )
    for part in pakset.parts:
        try:
            part.unlink(missing_ok=True)
        except OSError as exc:
            raise PakError(
                f"Impossible de supprimer {part.name} : {exc}. "
                "Le jeu est peut-être en cours d'exécution."
            ) from exc
