# FE Free Roam (Lua) — Fading Echo

Mod séparé pour explorer librement : enlève les murs rouges, la « reroute » démo, et les
triggers/volumes que tu veux.

## En fond (automatique)

- **Murs rouges** : désactive en continu les `BP_PlayerBlockerForAlpha_C` (collision + visibilité),
  y compris ceux qui (re)spawnent.
- **Reroute off** : le LevelLoader te renvoie au Bastion (+ TP) si tu charges une zone absente de
  `DemoAllowedLevels`. Le mod ajoute la zone en cours de chargement à cette liste **en pré-hook de
  `LoadZone`**, donc *avant* le test → jamais « hors liste », pour **n'importe quelle** zone (pas
  seulement les 7 zones normales).

## Commandes (console F10)

| Commande | Effet |
|---|---|
| `trigger` | désactive le **trigger/volume le plus proche** de toi |
| `trigger all` | désactive **tous** les triggers/volumes chargés |
| `trigger death` | désactive tous les **volumes de mort/void** (`BP_CustomDeathVolume`) |
| `walls` | force la désactivation des murs rouges tout de suite |

`trigger` (le plus proche) est le mode fin : il ne touche qu'un volume à la fois, sans casser les
autres déclencheurs de scène. `trigger all` est plus radical (peut neutraliser des events scriptés).

Classes ciblées par `trigger` : `TriggerVolume` (générique) + `BP_CustomDeathVolume`,
`BP_SaveRestrictionVolume`, `BP_DifficultyZoneTrigger`, `BP_CameraVolume`,
`BP_AudioCharacterOnTriggerBox`, `BP_RadioTrigger`, `BP_WaterTrigger`, `BP_ZoneLoader`.

## Install
```
...\UE_YGRO\Binaries\Win64\ue4ss\Mods\FEFreeRoam\
├── enabled.txt        (vide)
└── Scripts\
    └── main.lua
```

## Notes

- Le « plus proche » est calculé par **centre** du volume. Si un gros volume t'entoure, son centre
  peut être loin et `trigger` pourrait choisir un plus petit à côté — dans ce cas retape, ou utilise
  `trigger all` / `trigger death`. On pourra affiner (détection du volume qui te contient) si besoin.
- Recoupe FE Unlocker : celui-ci débloque déjà les 7 zones normales et désactive les murs rouges
  (F1). Ce mod-ci généralise le reroute à **toute** zone. Les faire tourner ensemble est sans risque
  (les ajouts à `DemoAllowedLevels` sont dédupliqués).
