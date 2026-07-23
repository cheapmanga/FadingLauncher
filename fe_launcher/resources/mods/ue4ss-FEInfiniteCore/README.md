# FE Infinite Core — déclencheur déterministe

Mod UE4SS **Lua** indépendant pour Fading Echo (`UE_YGRO`). En une touche : te donne un
core **dans** One, puis provoque une **mort dans le vide** après un délai réglable < 1 s —
le setup visé pour reproduire l'*Infinite Core* de façon répétable.

## Installation
Copier le dossier dans `<jeu>/UE_YGRO/Binaries/Win64/ue4ss/Mods/FEInfiniteCore/`
(soit `enabled.txt` + `Scripts/main.lua`).

## Utilisation
| Entrée | Effet |
|---|---|
| **F7** | lance la séquence complète |
| `icore` | idem |
| `icore delay <ms>` | délai grab→void (défaut **500**, borné < 1000) |
| `icore type <t>` | core donné : `water` \| `waste` \| `fire` \| `glitch` (défaut water) |
| `icore status` | config courante |

## Ce qui change par rapport au `core` du FE Unlocker
- Le core est **spawné à ta position** (`SPAWN_IN_ME`), pas 120 u devant → `StartGrab`
  n'a pas de temps de vol, la prise est immédiate.
- **Le mod déclenche lui-même le void** via `TriggerInstantFallDeath()` sur
  `pawn.BP_DeathBehaviour` (exec natif confirmé au PDB). Plus besoin de courir vers un trou :
  le délai grab→void est **chiffré et reproductible**, ce qui est tout l'intérêt (le timing
  est le levier de constance du glitch).

## Pourquoi ça vise le glitch
StartGrab pose les 2 couches du core : (A) l'acteur physique lié à One, (B) la charge
élémentaire qui pilote l'UI + le prompt LB. La mort dans le vide force One en **humain** et
reset les jauges **mais saute `KillGrabbedCore`** → la couche B reste. Résultat visé :
**humain + core LB toujours affiché**.

## À régler / vérifier en jeu (NON testé)
- **`icore delay`** est le paramètre à balayer. Le modèle prédit que **plus court = plus de
  réussites** (état du core « pas encore stabilisé »). Essaie 500 → 300 → 150 → 50.
- Si `StartGrab` n'a pas le temps de poser la couche B avant le void, tu auras un MISS :
  remonte le délai. Si au contraire un délai long nettoie l'état, redescends. La fenêtre
  gagnante est entre les deux — c'est elle qu'on cherche.
- Si `TriggerInstantFallDeath` ne provoque pas la bonne mort (void), on a un repli via
  `BP_DeathBehaviour` (`SetPreventRevive`/`Revive(1)`), à voir selon le comportement observé.
- Combine avec l'overlay/observation à l'œil : au respawn, note **forme (humain/eau)** +
  **prompt LB présent** = HIT.

Voir `Rapport_InfiniteCoreGlitch.md` et `Tests_InfiniteCoreGlitch_EnJeu.md` pour le modèle complet.
