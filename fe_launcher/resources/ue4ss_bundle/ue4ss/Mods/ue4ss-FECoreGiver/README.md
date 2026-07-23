# FE Core Giver — Fading Echo

Mod UE4SS **Lua** autonome pour Fading Echo (`UE_YGRO`). Il ne fait qu'**une** chose :
te donner un core élémentaire à la demande.

C'est le bloc `CORE GIVER` du **FE Unlocker**, extrait tel quel, sans les ascenseurs,
les zones, les murs alpha ni les portes.

## Installation
Copier le dossier dans `<jeu>/UE_YGRO/Binaries/Win64/ue4ss/Mods/FECoreGiver/`
(soit `enabled.txt` + `Scripts/main.lua`).

## Utilisation
Tout passe par la **console in-game** (F10). La sortie va aussi dans la console UE4SS,
préfixée `[CoreGiver]`.

| Commande | Effet |
|---|---|
| `core water` | spawne un core Water et te le met dans les mains |
| `core waste` | idem, Waste |
| `core fire` | idem, Lava |
| `core glitch` | idem, Corruption |
| `core power` | idem, PowerCore |
| `core <élément> nograb` | le pose devant toi **sans** l'attraper |
| `core list` | liste les éléments disponibles |

## Comment ça marche
Le core est spawné 120 u devant toi, 40 u au-dessus, via
`BeginDeferredActorSpawnFromClass` + `FinishSpawningActor`, puis passé à `StartGrab`
sur ton pawn. C'est le **grab** qui déclenche la charge élémentaire du jeu (UI + LB +
pouvoir) — on ne force aucune variable à la main.

`nograb` saute le `StartGrab` : le core reste posé. Utile pour tester l'*Infinite Core*
en forme de One (spawner un core sans l'absorber).

## Notes
- **Conflit avec FE Unlocker** : les deux mods enregistrent la commande console `core`.
  N'active qu'un seul des deux, sinon le second à charger écrase le handler du premier.
- Les noms d'éléments du jeu ne sont pas ceux de l'UI : `fire` → `LavaBall`,
  `glitch` → `CorruptionBall`.
- Si la classe du ball n'est pas encore chargée en mémoire, le mod le dit et te demande
  de t'approcher une fois d'un core de ce type (ça charge la classe), puis de réessayer.
  Il ne force pas le chargement de l'asset.
- Le pawn est résolu en 3 essais (PlayerController.Pawn → UEHelpers → instance non-CDO
  de `BP_CoreYgroCharacter_C`), et les CDO sont exclus partout.
