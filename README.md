# Fading Echo Launcher

Outil pour speedrunners et glitch hunters de *Fading Echo* (UE5 / UE_YGRO, appid Steam
`2467880`). Gère les mods UE4SS, les paks, les skins et les sauvegardes — et fournit un
banc d'essai statistique pour les campagnes de chasse aux glitchs.

Écrit en Python + PySide6. Cible Windows ; le développement et les tests se font sous
Linux contre une installation simulée.

---

## Pourquoi cet outil existe

Trois constats, tirés de l'état réel du modding sur ce jeu :

**1. L'installation du jeu complet casse UE4SS par défaut.** Le dossier Steam s'appelle
`Project Ygrό` — le dernier caractère est un omicron tonos **grec** (U+03CC), pas un `ó`
latin. UE4SS convertit son propre chemin en texte multi-octets pour initialiser Lua ; en
page de codes Windows 850/1252, ce caractère n'a aucune correspondance et UE4SS meurt sur
`Fatal Error: No mapping for the Unicode character exists in the target multi-byte code
page`. La démo, dont le dossier est en ASCII pur, fonctionne avec exactement la même
installation d'UE4SS. Le launcher détecte ce cas et propose de le corriger.

**2. Les mods se marchent dessus en silence.** Sur les 20 mods du projet, la touche F7 est
revendiquée par trois mods et F8 par trois autres. Un appui déclenche toutes les actions à
la fois. Pendant une campagne de mesure, ça invalide les essais sans que rien ne le
signale.

**3. La chasse aux glitchs se fait au papier.** Les protocoles existants se terminent tous
sur une grille manuscrite « délai / HIT / essais ». Or à 15 essais par palier, 3 réussites
et 6 réussites ne sont **pas** distinguables : le test exact de Fisher donne p ≈ 0,43.
Conclure « le second palier est deux fois meilleur » revient à décrire du bruit. Le banc
d'essai affiche systématiquement un intervalle de confiance et refuse de désigner un
gagnant tant que l'écart n'est pas significatif.

---

## Ce que le launcher garantit

**Tout est réversible.** Chaque écriture est consignée dans un journal (`core/ledger.py`)
*avant* d'être appliquée, avec de quoi la défaire. Les fichiers écrasés sont sauvegardés
sur disque, donc une annulation survit à un crash ou à un redémarrage.

**La désinstallation ne touche qu'à ce que le launcher a fait.** Elle rejoue le journal à
l'envers, puis efface ses propres données. Les mods installés à la main, les paks, les
sauvegardes et le jeu ne sont jamais concernés — ils ne sont pas dans le journal.

**Il refuse plutôt que de deviner.** Le correctif du chemin non-ASCII renomme un dossier
Steam et édite un manifeste : il ne s'exécute que si Steam est prouvé fermé. Si l'état de
Steam est *inconnu* (sonde indisponible), c'est traité comme un refus, jamais comme un
feu vert.

**Aucune édition de sauvegarde.** Le format GVAS de ce jeu est lisible et réécrivable à
l'octet près, mais son cadrage inter-objets n'est pas rétro-conçu : modifier une chaîne ou
un tableau casse le fichier silencieusement. Le launcher ne fait donc que copier et
restaurer des fichiers entiers.

---

## Architecture

```
fe_launcher/
  core/            logique métier, sans dépendance à l'interface
    paths.py       découverte de l'installation, disposition d'UE4SS
    mods.py        inventaire, activation, détection des conflits
    luaconf.py     lecture/écriture des réglages en tête des mods Lua
    ledger.py      journal des mutations — tout passe par lui
    doctor.py      diagnostics et correctifs
    bench.py       campagnes de mesure, Wilson et Fisher
    saves.py       sauvegardes, slots hors synchro Steam
    paks.py        paks custom (triplets .pak/.ucas/.utoc)
    profiles.py    profils applicables et réversibles
    launch.py      lancement du jeu
    moddocs.py     notices des mods, mods à accès restreint
    settings.py    préférences
  ui/              interface PySide6
tools/
  make_fixture.py  fabrique une installation simulée pour les tests
  gvas.py          parseur du format de sauvegarde UE5
tests/             suite pytest
```

`core/` ne dépend jamais de `ui/`. Toute la logique est testable sans écran et sans le jeu.

---

## Installation

Sur le PC de jeu (Windows) :

```bat
python -m venv .venv
.venv\Scripts\pip install PySide6
.venv\Scripts\python -m fe_launcher.app
```

En développement (Linux, sans le jeu) :

```bash
python3 -m venv .venv
.venv/bin/pip install PySide6 pytest
.venv/bin/python tools/make_fixture.py /tmp/fe-fixture   # installation simulée
.venv/bin/python -m pytest tests/ -q
```

---

## Faits vérifiés encodés dans le code

Ces points ont été établis sur des logs UE4SS réels, le manifeste Steam et les fichiers du
jeu. Ils ne viennent pas de la documentation générale d'UE4SS, qui diverge sur plusieurs
d'entre eux.

| Fait | Conséquence dans le code |
|---|---|
| UE4SS démarre les mods en **deux passes** : `mods.txt` (ordonnée) puis `enabled.txt` (non ordonnée) | Désactiver = retirer `enabled.txt`. Mettre `Nom : 0` dans `mods.txt` **ne désactive pas** un mod qui a un `enabled.txt` — la seconde passe le rattrape |
| C'est la **présence** d'`enabled.txt` qui active, pas son contenu (tous font 0 octet) | Activation par création/renommage du marqueur |
| La disposition d'UE4SS **diffère** : `Win64\ue4ss\` (jeu complet) vs `Win64\` (démo) | On cherche `UE4SS-settings.ini` aux deux endroits, jamais de chemin en dur |
| L'exe lancé par Steam est un **shim** (`FadingEcho.exe`, ~180 Ko), pas l'exe moteur (~176 Mo) | Lancement par `steam://` par défaut ; les autres modes sont marqués non vérifiés |
| Aucun argument de ligne de commande n'est documenté ni testé sur ce jeu | Les arguments sont transmis mais toujours accompagnés d'un avertissement |
| Les mods n'ont **aucun** fichier de configuration : leurs réglages sont des `local NOM = valeur` en tête du `.lua` | L'interface réécrit ces lignes chirurgicalement, en préservant commentaires et alignement |
| Steam ne synchronise que **3 fichiers** `.sav`, motif non récursif | Les slots vont dans un sous-dossier, avec une autre extension |
| `ConnectedSources`, `UnlockedSources`, `SkillPointBalance` **n'existent pas** dans les sauvegardes | Ce sont des stats de runtime : elles passent par la console du jeu, pas par l'édition de save |
| Le glitch du Core infini est une course d'**une frame** sur une file différée | Les délais sont exprimés en frames autant qu'en ms, et le framerate est verrouillé pendant une campagne |

---

## Limites connues

- **3 mods C++ ne sont pas compilés** (`FECheatUtils`, `KeystrokesKBM`, `KeystrokesPad`) :
  aucune DLL présente. Le launcher les signale au lieu de laisser croire qu'ils marchent.
- **La plupart des mods Lua ne sont pas testés en jeu**, leurs auteurs le disent dans leurs
  propres notices. Le launcher ne peut pas garantir qu'un mod fonctionne, seulement qu'il
  est correctement installé et activé.
- **Le rôle du suffixe `_P`, le dossier `~mods` et `LogicMods`** ne sont pas vérifiés sur ce
  jeu. Ils sont traités comme des hypothèses et signalés comme telles dans le code.
- **Le mode développeur** masque `ue4ss-FEDevMenu` par défaut. Ce n'est pas un verrou : le
  dossier reste sur le disque et peut être activé à la main. C'est un choix de présentation.
