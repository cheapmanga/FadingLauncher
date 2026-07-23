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

## Tout est fourni

Le launcher embarque de quoi partir de zéro, sans chercher un seul fichier :

- **UE4SS + correctif du chemin grec** en un bouton — UE4SS est EMBARQUÉ (le build
  qui fonctionne sur ce jeu, réglages OpenGL compris), rien à fournir ni télécharger.
- **17 mods** prêts à installer, avec leur dépendance UEHelpers.
- **15 sauvegardes** à différents points de progression, chargeables en un clic.
- **Prévisualisation des skins** avec les portraits du jeu.
- **Éditeur de sauvegarde** graphique (booléens et compteurs), le code brut derrière un
  bandeau « Avancé ».

Tout ce que le launcher installe passe par son journal : réversible, et la désinstallation
ne défait que ça.

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

**Édition de sauvegarde limitée à ce qui est sûr.** Le format GVAS de ce jeu se réécrit à
l'octet près, mais son cadrage inter-objets n'est pas rétro-conçu : modifier une chaîne ou
un tableau casserait le fichier silencieusement. L'éditeur n'expose donc QUE les champs à
largeur fixe — booléens et compteurs — dont l'aller-retour est garanti exact. Tout le
reste est lu mais jamais proposé à l'écriture.

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

### Windows — la plus simple

1. Téléchargez le projet : bouton vert **Code → Download ZIP**, puis extrayez-le.
2. Double-cliquez sur **`install.bat`**.

Il vérifie que tout est présent et installe ce qui manque (Python, l'environnement, la
dépendance graphique), puis crée un raccourci **Fading Echo Launcher** sur le Bureau. On
peut le relancer à tout moment : il ne refait que ce qui n'est pas déjà en place.

Pour lancer ensuite : le raccourci du Bureau, ou **`lancer.bat`**.

**Mettre à jour** (après un correctif) : double-cliquez sur **`update.bat`** — il télécharge la dernière version du code et remplace les fichiers, en gardant votre environnement. Bien plus rapide que de tout retélécharger.

### Windows — en faire un vrai .exe autonome (optionnel)

Après `install.bat`, double-cliquez sur **`build_exe.bat`**. Il produit
`dist\FadingEchoLauncher.exe` : un fichier unique qui ne nécessite plus rien pour tourner
et que vous pouvez copier où vous voulez.

### En développement (Linux, sans le jeu)

```bash
python3 -m venv .venv
.venv/bin/pip install PySide6 pytest
.venv/bin/python tools/make_fixture.py /tmp/fe-fixture   # installation simulée
.venv/bin/python -m pytest tests/ -q
.venv/bin/python run.py                                  # lance l'interface
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

- **Un mod C++ activé mais non compilé** (marqueur présent, aucune DLL) est signalé comme
  tel, au lieu de laisser croire qu'il fonctionne.
- **La plupart des mods Lua ne sont pas testés en jeu**, leurs auteurs le disent dans leurs
  propres notices. Le launcher ne peut pas garantir qu'un mod fonctionne, seulement qu'il
  est correctement installé et activé.
- **Le rôle du suffixe `_P`, le dossier `~mods` et `LogicMods`** ne sont pas vérifiés sur ce
  jeu. Ils sont traités comme des hypothèses et signalés comme telles dans le code.
