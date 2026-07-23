# FE Chest Hopper

Mod UE4SS Lua pour **Fading Echo** : téléportation de coffre en coffre depuis la console.

## Installation

Copier le dossier dans :

```
<jeu>/UE_YGRO/Binaries/Win64/ue4ss/Mods/FEChestHopper/
```

Structure attendue :

```
FEChestHopper/
├── enabled.txt        (vide)
└── Scripts/
    └── main.lua
```

## Utilisation

Ouvrir la console en jeu (**F10**), puis :

| Commande | Effet |
|---|---|
| `chest` | téléporte au coffre suivant — le 1er appel va au **plus proche** |
| `chest reset` | reconstruit la tournée depuis ta position actuelle |
| `chest prev` | revient au coffre précédent |
| `chest <n>` | saute directement au n-ième coffre de la tournée |
| `chest list` | liste les coffres chargés avec leur distance (en mètres) |
| `chest help` | rappel des commandes |

## Comment ça marche

Au premier `chest`, le mod collecte tous les coffres **chargés**, les trie par
distance au joueur, et fige cette liste. Chaque `chest` suivant avance d'un cran.
Arrivé au bout, il repart du début.

La tournée est reconstruite automatiquement si le nombre de coffres change
(streaming de niveau) ou si un coffre mémorisé devient invalide.

**Pourquoi un tri figé plutôt que recalculé à chaque saut ?** Parce qu'un tri
recalculé renverrait systématiquement au coffre d'où l'on vient (distance 0) :
on ferait des allers-retours entre deux coffres sans jamais couvrir la zone.

## Classes détectées

```
BP_Chest_Small_C   BP_Chest_Medium_C   BP_Chest_Big_C
BP_Chest_Special_LevelUp_C   BP_Chest_ALIENWARE_C
```

Relevées dans `/Game/Game/Placeable/InteractiveObjects/Chest/` de l'extract FModel.

## Limites connues

- **Seuls les coffres dont le sous-niveau est chargé sont atteignables.** Ceux
  d'une zone non encore streamée n'existent pas côté moteur : aucun mod ne peut
  les trouver. `chest list` montre l'état réel à l'instant T.
- **Le mod ne distingue pas un coffre ouvert d'un coffre fermé.** La classe
  expose bien un `ChestDeactivated`, mais c'est une référence d'objet, pas un
  booléen d'état fiable — filtrer là-dessus risquait de masquer des coffres
  valides. La tournée les inclut donc tous.
- Atterrissage à **+150 cm au-dessus** du coffre, pour ne pas se coincer dans sa
  collision. Ajustable via `Z_OFFSET` en haut de `main.lua`.

## Statut

**Non testé en jeu** — écrit à partir de l'extract et des idiomes déjà validés
dans les autres mods FE (`RegisterConsoleCommandGlobalHandler`,
`K2_SetActorLocation`, filtrage des `Default__`). Syntaxe Lua vérifiée avec `luac -p`.
