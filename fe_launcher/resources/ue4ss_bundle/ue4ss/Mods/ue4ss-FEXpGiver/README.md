# FE XP Giver — points d'Ætherfact

Mod UE4SS **Lua** autonome pour Fading Echo (`UE_YGRO`). Tape `xp` dans la console
in-game : +1 point d'Ætherfact. À chaque fois.

## Installation
Copier le dossier dans `<jeu>/UE_YGRO/Binaries/Win64/ue4ss/Mods/FEXpGiver/`
(soit `enabled.txt` + `Scripts/main.lua`).

## Utilisation
Console in-game (F10). La sortie va aussi dans la console UE4SS, préfixée `[XpGiver]`.

| Commande | Effet |
|---|---|
| `xp` | +1 point d'Ætherfact |
| `xp <n>` | +n points (ex. `xp 5`) |
| `xp status` | affiche le solde, sans rien donner |

Chaque don affiche le solde avant/après : si le chiffre ne bouge pas, tu le vois.

## Ce qu'est un « point d'Ætherfact »

La statistique **`SkillPointBalance`**, ligne 3 de `DT_PerksStatTemplate`
(`/Game/Game/Perks/Test/DT_PerksStatTemplate`, `default=0 min=0 max=+Inf`).

Le nom « Ætherfact » n'apparaît nulle part dans le code : c'est un terme purement
UI. Le lien a été établi en croisant quatre sources des extracts :

- `WBP_PerkToolTip` affiche `Cost` + `Ætherfact point(s)` → c'est le prix des perks.
- **Chaque** `DA_Perk_*.json` porte une `StatisticCondition` sur `SkillPointBalance`
  → c'est le contrôle du coût à l'achat.
- `DA_IncreaseSkillPoints_XS_StatisticModifier` = `SkillPointBalance += 1.0`
  (`Operator=Addition`, `Operand=FlatValue 1.0`, `StatisticIndex=3`), référencé par
  `DA_LevelUpDescriptor` → c'est la récompense de level-up.
- `StatisticIndex: 3` du data asset correspond exactement à la ligne 3 de la table.

## Comment ça marche

`UStatisticHolderComponent` expose 6 fonctions BlueprintCallable (symboles `exec*`
confirmés dans le PDB). Signatures exactes, lues dans les symboles mangés :

```
?IncreaseStatisticBaseValue@UStatisticHolderComponent@@QEAAXVFString@@M@Z
?SetStatisticBaseValue@UStatisticHolderComponent@@QEAAXVFString@@M@Z
?GetStatisticValue@UStatisticHolderComponent@@QEBAMVFString@@@Z
```

soit `(FString StatisticName, float Value)`. Le mod appelle
`IncreaseStatisticBaseValue("SkillPointBalance", n)`.

### Piège : `StatisticName` est une `FString`, pas une `FName`

`GetStatisticValue` est **surchargée** en C++ (`FString` / `FName` /
`FStatisticIdentifier`), mais c'est la surcharge `FString` qui est exposée au
Blueprint. Passer un objet `FName` fait **crasher le jeu** : UE4SS écrit l'argument
comme une `StrProperty` (`push_strproperty` → `FString::SetCharArray`) et déréférence
n'importe quoi → `EXCEPTION_ACCESS_VIOLATION`. Il faut passer une chaîne Lua brute.

Le type `FGenericPropertyParams` des `NewProp_` dans le PDB **ne permet pas** de
trancher `FName` vs `FString` : il couvre les deux. Seul le symbole mangé le dit.

**Pourquoi pas `ApplyStatisticModifierSet(DA_IncreaseSkillPoints_XS)`**, qui est
pourtant le chemin du jeu ? Parce qu'un modifier set est une *couche* qu'on applique
et retire (`Apply`/`Unapply`). Rien ne garantit qu'appliquer deux fois le même
descripteur empile deux fois — or l'intérêt ici est de pouvoir retaper `xp` en
boucle. `IncreaseStatisticBaseValue` écrit la valeur de **base** : cumulatif par
construction, donc répétable.

## Comment le bon composant est trouvé

Plusieurs `StatisticHolderComponent` coexistent (un par template : santé, perks…),
et ils ne sont pas distinguables par lecture seule — `GetStatisticValue` renvoie `0`
aussi bien pour « stat à zéro » que pour « stat inconnue de ce template ».

- **Chemin principal** : `PH_XP_Manager_C` (un `ActorComponent`) expose une propriété
  `StatHolder`. C'est le composant qui gère la monnaie — il a `UpdateCurrency(CurrencyToAdd)`,
  `XPCurrency`, `OnCurrencyIncrease` — donc son holder est celui du template des perks.
- **Repli** : balayage de tous les `StatisticHolderComponent`, en écrivant puis en
  relisant. Le bon est celui dont la valeur bouge réellement ; les autres sont ignorés.

## Notes
- Aucune touche assignée (F1-F4 = FE Unlocker, F7 = FEInfiniteCore). Console uniquement.
- Pas de conflit de commande avec les autres mods FE : `xp` est libre.
- Le solde est borné à `min=0` par la table : tu ne peux pas descendre sous zéro.
- **Non testé en jeu** — écrit à partir des extracts et du PDB. Le `xp status` et
  l'affichage avant/après sont là pour que tu vérifies en une commande.
