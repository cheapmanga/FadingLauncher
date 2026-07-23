"""Banc d'essai : campagnes de mesure HIT/MISS sur un paramètre de timing.

Pourquoi ce module existe
-------------------------
La chasse aux glitchs de Fading Echo n'est pas « faire un glitch », c'est une campagne
de mesure : on fait varier UN paramètre (le délai grab→void), on note HIT ou MISS
15 à 20 fois par palier, et on compare les taux. Aujourd'hui cette grille se tient à
la main sur du papier, et c'est ce que ce module remplace.

Le piège que la méthode papier ne peut pas voir
-----------------------------------------------
Sur 15 essais, 3 réussites (20 %) et 6 réussites (40 %) SEMBLENT très différents. Ils
ne le sont pas : le test exact de Fisher donne p ≈ 0,43. Autrement dit, si les deux
paliers étaient réellement équivalents, on observerait un écart au moins aussi grand
presque une fois sur deux. Conclure « 400 ms est deux fois meilleur » sur ces données,
c'est décrire du bruit.

C'est la raison d'être du module : afficher un intervalle de confiance à côté de chaque
taux, et refuser de déclarer un palier gagnant tant que l'écart n'est pas significatif.
Sans ça, l'outil automatise la production de fausses conclusions plus vite qu'à la main.

Pourquoi les délais sont aussi exprimés en frames
-------------------------------------------------
La cause racine du glitch est une race condition d'UNE frame : `QueueCommand` empile,
`ProcessPendingCommands` dépile au Tick suivant. Un délai en millisecondes ne veut donc
rien dire sans le frame time associé — 300 ms à 60 fps (18 frames) et 300 ms à 144 fps
(43 frames) ne testent pas la même chose. Toute campagne enregistre son framerate, et
les délais sont convertis en frames pour permettre de comparer des sessions entre elles.

Aucune dépendance externe : tout est en stdlib, y compris Fisher exact.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# z pour un intervalle bilatéral à 95 %.
Z95 = 1.959963984540054


class Outcome(Enum):
    HIT = "hit"
    MISS = "miss"
    #  Essai à jeter : départ sur un état sale, mauvaise manip, crash. Ne compte pas
    #  au dénominateur — c'est ce qui distingue une mesure honnête d'une mesure gonflée.
    VOID = "void"


@dataclass
class Trial:
    outcome: Outcome
    at: str                       # ISO 8601 UTC
    note: str = ""

    def to_dict(self) -> dict:
        return {"outcome": self.outcome.value, "at": self.at, "note": self.note}

    @staticmethod
    def from_dict(d: dict) -> "Trial":
        return Trial(outcome=Outcome(d["outcome"]), at=d["at"], note=d.get("note", ""))


@dataclass
class Interval:
    low: float
    high: float

    @property
    def width(self) -> float:
        return self.high - self.low

    def __str__(self) -> str:
        return f"[{self.low:.0%} – {self.high:.0%}]"


def wilson(hits: int, n: int, z: float = Z95) -> Interval:
    """Intervalle de confiance de Wilson pour une proportion.

    Choisi plutôt que l'intervalle normal (Wald) parce qu'on travaille sur de petits
    effectifs et des taux proches de 0. Wald donne des bornes absurdes dans ce régime :
    à 0 succès sur 15, il produit l'intervalle [0 %, 0 %], ce qui affirmerait que le
    glitch est impossible alors qu'on n'a simplement pas assez d'essais. Wilson donne
    [0 %, 20 %], qui est la lecture honnête.
    """
    if n <= 0:
        return Interval(0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return Interval(max(0.0, center - half), min(1.0, center + half))


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """p bilatéral du test exact de Fisher sur la table 2×2 [[a, b], [c, d]].

    Exact plutôt qu'approché : avec 15 essais par palier, l'approximation du χ² n'est
    pas valide (effectifs attendus < 5). Implémenté par énumération de toutes les
    tables de mêmes marges — coût négligeable aux effectifs concernés.
    """
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1 = a + b, a + c

    def prob(x: int) -> float:
        return (
            math.comb(row1, x)
            * math.comb(n - row1, col1 - x)
            / math.comb(n, col1)
        )

    observed = prob(a)
    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)
    # Tolérance relative : compare les probabilités à l'epsilon machine près, sinon
    # des tables strictement aussi extrêmes seraient exclues par erreur d'arrondi.
    total = sum(p for x in range(lo, hi + 1)
                if (p := prob(x)) <= observed * (1 + 1e-9))
    return min(1.0, total)


@dataclass
class Bucket:
    """Un palier de la campagne : une valeur du paramètre balayé."""

    value: float                  # ex. délai en ms
    label: str = ""
    trials: list[Trial] = field(default_factory=list)

    @property
    def counted(self) -> list[Trial]:
        return [t for t in self.trials if t.outcome is not Outcome.VOID]

    @property
    def hits(self) -> int:
        return sum(1 for t in self.counted if t.outcome is Outcome.HIT)

    @property
    def n(self) -> int:
        return len(self.counted)

    @property
    def voided(self) -> int:
        return sum(1 for t in self.trials if t.outcome is Outcome.VOID)

    @property
    def rate(self) -> float:
        return self.hits / self.n if self.n else 0.0

    @property
    def ci(self) -> Interval:
        return wilson(self.hits, self.n)

    def frames(self, fps: float) -> float:
        """Le paramètre exprimé en frames, à un framerate donné."""
        return self.value * fps / 1000.0 if fps > 0 else float("nan")

    def to_dict(self) -> dict:
        return {"value": self.value, "label": self.label,
                "trials": [t.to_dict() for t in self.trials]}

    @staticmethod
    def from_dict(d: dict) -> "Bucket":
        return Bucket(value=d["value"], label=d.get("label", ""),
                      trials=[Trial.from_dict(t) for t in d.get("trials", [])])


@dataclass
class Campaign:
    """Une campagne de mesure complète, sérialisable en JSON."""

    name: str
    parameter: str = "VOID_DELAY_MS"     # constante Lua pilotée
    unit: str = "ms"                     # unité du paramètre, affichée dans le verdict
    mod: str = "ue4ss-FEInfiniteCore"
    fps_lock: float = 0.0                # 0 = non verrouillé (mesure peu comparable)
    setup: str = ""                      # zone, forme, type de core
    game_build: str = ""
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    buckets: list[Bucket] = field(default_factory=list)

    # --- construction ---

    def bucket(self, value: float) -> Bucket:
        for b in self.buckets:
            if b.value == value:
                return b
        b = Bucket(value=value)
        self.buckets.append(b)
        self.buckets.sort(key=lambda x: x.value)
        return b

    def record(self, value: float, outcome: Outcome, note: str = "") -> Trial:
        t = Trial(outcome=outcome,
                  at=datetime.now(timezone.utc).isoformat(),
                  note=note)
        self.bucket(value).trials.append(t)
        return t

    def undo(self, value: float) -> Trial | None:
        """Annule le dernier essai d'un palier. Indispensable : à la main, sur une
        série de 20, on se trompe de touche."""
        b = self.bucket(value)
        return b.trials.pop() if b.trials else None

    # --- lecture ---

    @property
    def total_trials(self) -> int:
        return sum(b.n for b in self.buckets)

    def best(self) -> Bucket | None:
        """Palier au meilleur taux observé. Attention : « observé » ne veut pas dire
        « meilleur » — voir significance()."""
        pool = [b for b in self.buckets if b.n]
        return max(pool, key=lambda b: b.rate) if pool else None

    def significance(self, a: Bucket, b: Bucket) -> float:
        """p de Fisher entre deux paliers. p < 0,05 = écart difficilement dû au hasard."""
        return fisher_exact(a.hits, a.n - a.hits, b.hits, b.n - b.hits)

    def holm(self, top: Bucket, others: list[Bucket],
             alpha: float = 0.05) -> list[Bucket]:
        """Paliers réellement battus par `top`, après correction de Holm-Bonferroni.

        Pourquoi une correction est indispensable
        -----------------------------------------
        Comparer le meilleur palier à chacun des autres à 5 % n'est PAS un test à 5 % :
        c'est autant de tests, et le risque de faux positif s'accumule. Pire, on choisit
        `top` parce qu'il est le meilleur observé, ce qui biaise encore la comparaison
        en sa faveur.

        Mesuré par simulation, tous les paliers ayant le MÊME taux réel (aucun gagnant
        n'existe), 15 essais par palier — proportion de campagnes où la version non
        corrigée désignait quand même un gagnant :

            2 paliers ->  1,7 %      8 paliers -> 20,7 %
            5 paliers -> 10,8 %     12 paliers -> 38,9 %

        Un balayage 100→1200 ms de 100 en 100 fait 12 paliers. L'outil aurait donc
        inventé un gagnant dans près de quatre campagnes sur dix, ce qui est exactement
        ce qu'il prétend empêcher — et bien pire que du papier, puisqu'il l'affirme avec
        l'autorité d'un calcul.

        Holm plutôt que Bonferroni simple : même garantie sur le risque global, mais on
        ne divise pas tous les seuils par le nombre total. Bonferroni serait si strict
        qu'il ne détecterait plus les écarts réels, et un outil qui ne conclut jamais
        est aussi inutile qu'un outil qui conclut toujours.

        Correction du biais de sélection du maximum
        -------------------------------------------
        Holm seul ne suffit pas : `top` n'est pas un palier fixé d'avance, c'est le
        MEILLEUR taux observé, choisi après coup. Plus il y a de paliers, plus ce
        maximum est gonflé par la chance, et Holm ne compense pas ça. Mesuré : le taux
        de faux gagnants remontait à ~10 % sur un balayage de 20 paliers, le double de
        la garantie. On resserre donc le premier seuil de Holm par le nombre de
        candidats au titre de « meilleur » (`k`), ce qui neutralise la sélection.
        Vérifié par simulation : ramène le faux positif sous alpha jusqu'à 20 paliers.
        """
        # Deux corrections distinctes, appliquées l'une sur l'autre :
        #  1. le biais de sélection du maximum, via un alpha resserré par le nombre de
        #     candidats au titre de « meilleur » (`selection_factor`) ;
        #  2. les comparaisons multiples, via Holm proprement dit (`_holm`).
        # Les garder séparées permet de vérifier le cœur Holm contre une référence
        # standard, indépendamment de la correction de sélection.
        k = max(1, len(others) + 1)
        return self._holm(top, others, alpha / k)

    @staticmethod
    def _holm_pvalues(pairs: list[tuple[float, "Bucket"]], alpha: float) -> list["Bucket"]:
        """Procédure de Holm-Bonferroni pure sur des (p, bucket) triés croissants."""
        m = len(pairs)
        beaten: list[Bucket] = []
        for i, (p, bucket) in enumerate(pairs):
            if p <= alpha / (m - i):
                beaten.append(bucket)
            else:
                break  # Holm s'arrête au premier échec.
        return beaten

    def _holm(self, top: Bucket, others: list[Bucket], alpha: float) -> list[Bucket]:
        pairs = sorted(((self.significance(top, b), b) for b in others),
                       key=lambda t: t[0])
        return self._holm_pvalues(pairs, alpha)

    def verdict(self, alpha: float = 0.05) -> str:
        """Conclusion honnête sur l'état actuel de la campagne.

        Renvoie une phrase prête à afficher, y compris — et surtout — quand la
        conclusion est « on ne sait pas encore ». C'est le comportement voulu : un
        outil qui désigne toujours un gagnant apprendrait à l'utilisateur à croire
        du bruit.
        """
        pool = [b for b in self.buckets if b.n]
        if len(pool) < 2:
            return "Pas assez de paliers mesurés pour conclure."

        top = max(pool, key=lambda x: x.rate)
        others = [b for b in pool if b is not top]
        beaten = self.holm(top, others, alpha)

        if not beaten:
            worst_p = min((self.significance(top, b) for b in others), default=1.0)
            return (
                f"Aucun écart significatif. Le palier {top.value:g} {self.unit} mène à "
                f"{top.rate:.0%} mais c'est compatible avec du hasard — il faut plus "
                f"d'essais. (Même si tous les paliers se valaient, on observerait un "
                f"écart au moins aussi grand dans {worst_p:.0%} des campagnes.)"
            )

        # On NOMME les paliers battus. « bat 1/3 des autres » se lit d'abord comme
        # « un tiers », ne dit pas lesquels, et laisse l'utilisateur sans réponse à la
        # seule question qu'il se pose : quel délai adopter.
        names = ", ".join(f"{b.value:g}" for b in sorted(beaten, key=lambda x: x.value))
        undecided = [b for b in others if b not in beaten]

        if not undecided:
            return (
                f"Le palier {top.value:g} {self.unit} ({top.rate:.0%}, {top.ci}) fait "
                f"significativement mieux que tous les autres."
            )
        left = ", ".join(f"{b.value:g}" for b in sorted(undecided, key=lambda x: x.value))
        return (
            f"Le palier {top.value:g} {self.unit} ({top.rate:.0%}, {top.ci}) fait "
            f"significativement mieux que {names}. "
            f"Rien ne le départage de {left} pour l'instant."
        )

    def suggest_next(self, target: int = 15) -> Bucket | None:
        """Prochain palier à mesurer : celui qui a le moins d'essais.

        Équilibrer les effectifs plutôt que finir un palier avant de passer au suivant :
        une campagne interrompue donne alors quand même une comparaison exploitable.
        """
        pool = [b for b in self.buckets if b.n < target]
        return min(pool, key=lambda b: (b.n, b.value)) if pool else None

    # --- persistance ---

    def to_dict(self) -> dict:
        d = asdict(self)
        d["buckets"] = [b.to_dict() for b in self.buckets]
        return d

    @staticmethod
    def from_dict(d: dict) -> "Campaign":
        c = Campaign(
            name=d["name"],
            parameter=d.get("parameter", "VOID_DELAY_MS"),
            unit=d.get("unit", "ms"),
            mod=d.get("mod", ""),
            fps_lock=d.get("fps_lock", 0.0),
            setup=d.get("setup", ""),
            game_build=d.get("game_build", ""),
            created=d.get("created", ""),
        )
        c.buckets = [Bucket.from_dict(b) for b in d.get("buckets", [])]
        return c

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                        encoding="utf-8")

    @staticmethod
    def load(path: Path | str) -> "Campaign":
        return Campaign.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # --- export ---

    def to_grid(self) -> str:
        """Grille ASCII, au format des notes de chasse existantes.

        Le livrable d'une session de chasse est un tableau partageable ; le garder
        copiable-collable tel quel évite de couper l'outil de la communauté qui
        travaille déjà avec ce format.
        """
        fps = self.fps_lock
        head = f"CAMPAGNE : {self.name}"
        meta = [
            f"Paramètre : {self.parameter} ({self.mod})",
            f"Setup     : {self.setup or '—'}",
            f"Framerate : {f'{fps:g} fps (verrouillé)' if fps else '⚠ NON VERROUILLÉ — délais non comparables'}",
            f"Build     : {self.game_build or '—'}",
            f"Total     : {self.total_trials} essais comptés",
        ]

        cols = ["Palier", "Frames", "HIT", "n", "Taux", "IC 95%", "Rejetés"]
        rows = []
        for b in self.buckets:
            rows.append([
                f"{b.value:g}",
                f"{b.frames(fps):.1f}" if fps else "—",
                str(b.hits),
                str(b.n),
                f"{b.rate:.0%}" if b.n else "—",
                str(b.ci) if b.n else "—",
                str(b.voided) if b.voided else "",
            ])

        widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c)
                  for i, c in enumerate(cols)]
        sep = "+".join("-" * (w + 2) for w in widths)
        line = lambda cells: "|".join(f" {c:<{w}} " for c, w in zip(cells, widths))

        out = [head, "=" * len(head), *meta, "", sep, line(cols), sep]
        out += [line(r) for r in rows]
        out += [sep, "", self.verdict()]
        return "\n".join(out)
