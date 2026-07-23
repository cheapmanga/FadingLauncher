# FE Form Forcer (Lua) — Fading Echo

Force la forme du personnage via la console in-game, avec option persistante.

## Commande (console F10)

| Commande | Effet |
|---|---|
| `form water` | passe en WaterForm |
| `form waste` | passe en WasteForm |
| `form steam` | passe en SteamForm |
| `form nitro` | passe en BurningWasteForm |
| `form glitch` | ⚠️ **bloqué par défaut** (crash connu) — voir plus bas ; `form glitch force` pour tenter |
| `form <x> persistent` | force la forme **et la maintient en boucle** (réappliquée tant qu'elle n'est pas active) |
| `form stop` | arrête la persistance |

`persistent` (ou `persist` / `loop`) peut se mettre après le nom de forme. Un `form <x>` simple
(sans `persistent`) annule une persistance en cours.

## Install
```
...\UE_YGRO\Binaries\Win64\ue4ss\Mods\FormForcer\
├── enabled.txt        (vide)
└── Scripts\
    └── main.lua
```
Sortie dans la console UE4SS (Ctrl+O) et in-game, préfixée `[form]`.

## Comment ça marche

- **Levier** : `BP_CoreYgroCharacter_C:ActivateFluidFormNS(NewFormClass)` — la seule fonction de
  forme réellement **appelable** dans cette build (confirmé par un dump runtime). Elle prend une
  **classe de forme**.
- **Classes** (`/Game/Game/Pawn/Playable/`) : `WaterForm_C`, `WasteForm_C`, `SteamForm_C`,
  `BP_Player_BurningWasteForm_C` (= "nitro"), `CorruptionForm_C` (= "glitch").
- **Sécurité** : on ne passe la classe au natif **que si elle est valide** (jamais de `nil`). Si la
  classe n'est pas chargée, la commande le dit → transforme-toi une fois dans cette forme pour la
  charger, puis réessaie.
- **Persistance** : une boucle (1 s) réapplique `ActivateFluidFormNS` tant que c'est actif.

> **Pourquoi pas `SwitchToForm(FName)` ?** Cette fonction existe dans le binaire (vue au
> désassemblage) mais **n'est pas appelable dans cette build** : l'appeler provoque un **crash**
> (access violation). Seul `ActivateFluidFormNS` fonctionne.

> **`ActivateFluidFormNS` change-t-il vraiment la forme, ou juste le VFX ?** Le suffixe « NS »
> (Niagara System) laisse penser qu'il pilote surtout l'effet visuel. À confirmer en jeu : si tu
> as l'apparence mais pas les capacités de la forme, on le saura.

## ⚠️ glitch (CorruptionForm) — crash connu

Forcer la CorruptionForm a **crashé le jeu** dans une session précédente (`ACCESS_VIOLATION` dans le
système de stats), et c'est **confirmé par un dev du jeu** : la jauge de corruption n'est pas
initialisée sur le personnage de la démo, donc activer la forme sollicite un descripteur de stat nul.
C'était via `ActivateFluidFormNS` ; `SwitchToForm` (la vraie transition) est *peut-être* plus sûr,
mais ce n'est **pas garanti**. Le mod bloque donc `form glitch` par défaut : tape `form glitch force`
(après avoir **sauvegardé**) pour tenter à tes risques. La persistance sur glitch est déconseillée.

## Limite connue

`SwitchToForm` respecte les règles du jeu (`CanTransition`) : selon l'état (forme humaine, absence
de la charge élémentaire requise…), une forme peut refuser de s'activer. Le mieux est de l'utiliser
quand tu es déjà transformé (comme demandé). Si une forme précise ne passe jamais, dis-le — on
regardera s'il faut poser la charge d'abord (voir le Core Giver dans FE Unlocker).
