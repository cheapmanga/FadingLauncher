# FE MoonJump — saut infini / vol à la BotW

Mod UE4SS **Lua** indépendant pour Fading Echo (`UE_YGRO`).

## Installation

Copier le dossier dans :

```
<jeu>/UE_YGRO/Binaries/Win64/ue4ss/Mods/FEMoonJump/
```

(soit `FEMoonJump/enabled.txt` + `FEMoonJump/Scripts/main.lua`)

## Deux modes, indépendants

| Touche | Mode | Effet |
|---|---|---|
| **F7** | MoonJump | Tant que **SAUT est maintenu**, la vitesse verticale est forcée vers le haut → montée continue. C'est le moonjump de BotW. |
| **F6** | MultiJump | `JumpMaxCount = 999` → on peut re-sauter en l'air indéfiniment, en gardant la physique de saut du jeu. |

Les deux peuvent être actifs en même temps.

## Console (F10)

```
moonjump              toggle
moonjump speed <n>    vitesse de montée, cm/s (défaut 700)
moonjump key <FKey>   touche surveillée (défaut SpaceBar)
moonjump status       état courant
multijump             toggle
```

## Comment ça marche

- **MoonJump** : boucle à ~60 Hz. Elle lit le maintien de touche avec
  `PlayerController:IsInputKeyDown({KeyName=FName("SpaceBar")})` (même méthode que le mod
  Keystrokes), et appelle `pawn:LaunchCharacter({X=0,Y=0,Z=speed}, false, true)`.
  `LaunchCharacter` est une UFUNCTION d'`ACharacter` (exposée BP) → appelable via UE4SS.
  `bXYOverride=false` garde le contrôle horizontal ; `bZOverride=true` écrase la vitesse
  verticale à chaque frame, donc la gravité ne s'accumule pas et la montée reste régulière.
- **MultiJump** : écrit la propriété `JumpMaxCount` du pawn. Elle est réappliquée toutes les
  2 s, car le pawn est recréé au respawn et au changement de zone. L'ancienne valeur est
  sauvegardée et restaurée à l'extinction.

Le mod n'appelle que des UFUNCTIONs gameplay et n'écrit aucune stat → il n'entre pas dans le
chemin de crash `UStatisticSubsystem` décrit au §5 de `FadingEcho_Modding_Reference.md`.

## À vérifier en jeu (non testé)

- **Manette** : passer `moonjump key Gamepad_FaceButton_Bottom` si tu joues au pad.
- Si la touche de saut a été remappée, `moonjump key <FKey>` accepte n'importe quel nom d'FKey Unreal.
- Si `LaunchCharacter` ne répond pas, c'est que le pawn n'hérite pas d'`ACharacter` comme supposé :
  le repli serait d'écrire directement `Velocity.Z` sur le `CharacterMovement`. Dis-le-moi, on
  ajustera.
- Monter très haut peut te faire sortir de la zone chargée : combiner avec `ue4ss-FEFreeRoam`
  (murs rouges + reroute off) et, en cas de chute mortelle, le toggle Void Cancel.
