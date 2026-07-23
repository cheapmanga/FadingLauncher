# FEPerf — 10 presets de performance pour Fading Echo

Mod UE4SS Lua. **Plus le numéro de preset est élevé, plus tu as de FPS** (et plus c'est moche).
Le preset 0 remet les défauts moteur.

## Installation

Copier le dossier dans `…/UE_YGRO/Binaries/Win64/ue4ss/Mods/` sous le nom **`FEPerf`**,
puis ajouter `FEPerf : 1` dans `Mods/mods.txt` (le `enabled.txt` présent suffit sur les
builds UE4SS récents).

## Utilisation

Console du jeu (touche `²` en AZERTY) :

| Commande | Effet |
|---|---|
| `fps <0-10>` | applique un preset |
| `fps status` | preset courant |
| `fps list` | la liste des 10 |
| `fps stat` | bascule l'overlay `stat unit` (ms Frame/Game/Draw/GPU) — **pour mesurer le gain** |
| `fps off` | = `fps 0` |

Raccourcis (**pavé numérique** — les F1-F10 sont déjà pris par FEUnlocker-Plus, FEMoonJump,
FEInfiniteCore et les Keystrokes) :

- `+` → preset suivant (plus de FPS)
- `-` → preset précédent (plus beau)
- `*` → statut

Le détail de chaque application part dans la **fenêtre console UE4SS**, pas dans celle du jeu
(voir « piège `Ar` » plus bas).

## Les 10 presets

| # | Nom | Ce qui saute |
|---|---|---|
| 0 | Défauts moteur | — |
| 1 | Vanilla+ | cap FPS + VSync off, flou de mouvement, profondeur de champ. **Aucune perte visuelle réelle.** |
| 2 | Élevé | post-process allégé : reflets écran, bloom, tonemapper, flares |
| 3 | Élevé- | ombres / GI / reflets / effets en qualité 2 |
| 4 | Moyen | tous les groupes de scalabilité en 2, rendu à 90 % |
| 5 | Moyen- | brouillard volumétrique et reflets écran coupés, rendu à 85 %, végétation −20 % |
| 6 | Bas | **gros palier : Lumen désactivé** (GI + reflets dynamiques), tout en qualité 1, rendu à 80 % |
| 7 | Bas- | **ombres dynamiques coupées**, distance d'affichage −35 %, végétation −55 % |
| 8 | Très bas | scalabilité 0 partout, TSR → FXAA, rendu à 66 %, LOD biaisés |
| 9 | Patate | plus d'anti-aliasing, rendu à 58 %, textures basse résolution, bloom/tonemapper off |
| 10 | Patate ultime | rendu à 50 %, LOD au minimum, végétation supprimée, brouillard off |

Les deux paliers qui rapportent le plus sur ce jeu sont **6** (Lumen) et **8** (résolution
interne à 66 % + scalabilité 0). Entre 1 et 5 les gains sont modestes.

## Comment ça marche

Chaque preset est **auto-suffisant** : le mod rejoue d'abord la liste `RESET` (défauts
moteur) puis applique ses propres deltas. Passer de 8 à 3 ne laisse donc rien traîner du 8.
Les commandes partent via `UKismetSystemLibrary::ExecuteConsoleCommand`, avec les helpers
`GetWorld` / `GetPC` / `KSL` déjà validés en jeu dans `ue4ss-FEDevMenu` (21/07/2026).

## Limites — à lire

- **Certaines cvars sont `ECVF_Cheat` et sont ignorées en build Shipping.** Une commande
  refusée ne remonte aucune erreur : le mod ne peut pas savoir laquelle a pris. C'est sans
  danger, ça ne fait juste rien. Le compteur « X en échec » ne compte que les échecs d'appel
  Lua, pas les refus moteur.
- **Le preset 0 restaure les défauts *moteur*, pas forcément ceux du jeu.** Retour 100 %
  propre = repasser par le menu graphique du jeu, ou relancer.
- **Non testé en jeu.** La syntaxe Lua est vérifiée (`luac -p`) et les helpers console sont
  repris d'un mod validé, mais aucun preset n'a été mesuré manette en main. Utilise
  `fps stat` pour vérifier le gain réel avant de conclure.
- Le menu graphique du jeu peut réécrire les `sg.*` : si tu y touches, réapplique le preset.
- **Ne touche à rien du gameplay** — que du rendu. Aucun risque pour les saves.

## ⚠️ Piège `Ar` (repris de FEDevMenu, a déjà crashé un mod)

Le `FOutputDevice` `Ar` d'un handler de commande n'est valide que dans le corps **synchrone**.
Dans `ExecuteInGameThread` / `LoopAsync` c'est un pointeur mort → `EXCEPTION_ACCESS_VIOLATION`
en lecture à `0x8`, et **`pcall` ne protège pas** (violation native, pas erreur Lua).
D'où : tout le code différé du mod n'utilise que `print()`.
