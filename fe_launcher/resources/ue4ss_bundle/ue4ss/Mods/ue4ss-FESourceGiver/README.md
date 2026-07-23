# FE Source Giver

Mod UE4SS (Lua) pour **Fading Echo** — incrémente le nombre de **sources branchées au Bastion** via une commande console.

## Installation

Copie le dossier `ue4ss-FESourceGiver` dans :

```
<jeu>\UE_YGRO\...\Binaries\Win64\ue4ss\Mods\FESourceGiver\
```

(garde la structure `Scripts/main.lua` + `enabled.txt`).

## Commandes (console in-game, ouverte avec **F10**)

| Commande            | Effet |
|---------------------|-------|
| `source`            | +1 source branchée |
| `source <n>`        | +n sources (ex. `source 3`) |
| `source set <n>`    | fixe le total à n (ex. `source set 12` → ouvre la fin) |
| `source status`     | affiche le total courant, sans rien changer |
| `source unlocked <n>` | +n sources *trouvées* (l'autre stat, jalons 1/3/6/9) |

## Ce que ça touche

Deux stats distinctes existent dans le jeu :

- **`ConnectedSources`** — sources *branchées* au Bastion. C'est ce que ce mod
  incrémente par défaut. Le Level Blueprint teste `ConnectedSources == 12` pour
  lancer le **FinalFight** (12 = 3 sources × 4 zones). Donc `source set 12`
  remplit la condition de la fin.
- **`UnlockedSources`** — sources *trouvées* dans les zones (jalons 1/3/6/9).
  Accessible via `source unlocked <n>`.

## Notes techniques

- API : `UStatisticHolderComponent` → `IncreaseStatisticBaseValue` /
  `SetStatisticBaseValue` / `GetStatisticValue`, signature `(FString, float)`.
- Le nom de stat est une **FString** (chaîne Lua brute) — passer un `FName`
  ferait crasher le jeu.
- `ConnectedSources` est une stat de l'entité *World* ; le bon holder est trouvé
  automatiquement par « écrire puis relire » (le seul dont la valeur bouge), puis
  mis en cache.
- Tout est en `pcall` : si une brique échoue, le jeu continue.

⚠️ Non testé en jeu (ce poste n'a ni le jeu ni de quoi le lancer). À valider :
`source status` d'abord (doit afficher un total cohérent), puis `source 1`.
Si `source` renvoie « aucun holder n'a accepté », sois bien **au Bastion** (là où
l'on branche les sources) au moment de la commande.
