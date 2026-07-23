# FE Dev Toolkit

Mod UE4SS Lua pour **Fading Echo**. Rassemble tout ce qui a été trouvé de « fait
pour les devs » et masqué au joueur.

## Installation

Copier dans `<jeu>/UE_YGRO/Binaries/Win64/ue4ss/Mods/FEDevMenu/` :

```
FEDevMenu/
├── enabled.txt        (vide)
└── Scripts/
    └── main.lua
```

Console du jeu : touche **`²`** (AZERTY). Les retours détaillés vont dans la
**fenêtre de console UE4SS**.

## Les 4 commandes

| Commande | Effet |
|---|---|
| `devmenu` | menu pause dev : DEBUG / LOAD / CHECKPOINT |
| `devmenu extra` | + LOAD LEVEL / SAVE / RESTART / LAST CHECKPOINT |
| `devmenu off` / `status` | désactiver / diagnostiquer |
| `cheat list` | les 23 fonctions du CheatManager |
| `cheat <alias> [arg]` | en appeler une |
| `cam` | caméra libre du moteur (bascule) |
| `cam spawn` / `despawn` | spectateur du jeu (16 touches manette) |
| `devmap list` / `devmap <alias>` | charger une map de dev |

### Ordre conseillé au premier lancement

1. ouvrir le menu pause une fois (Échap), refermer
2. `devmenu`
3. rouvrir le menu pause → DEBUG / LOAD / CHECKPOINT

Le widget n'existe qu'après sa première ouverture ; la boucle du mod le rattrape
dans la seconde.

## Les cheats (23)

`abilities` `health` `mana` `aether` `xp` `kill` `glitchtp` `combat` `perf`
`debugcam` `spellaim` `viewrot` `squad` `squadreset` `squadget` `enemyint`
`playerint` `hud` `waterform` `dialogue <n>` `checkpoint <nom>` `optimize`
`call <nom>`

Les alias existent parce que trois noms réels contiennent une **espace**
(`Toggle HUD`, `Unlock Water Form`, `Change Dialogue Style`) et que deux
comportent une **faute de frappe d'origine** (`ToggleInifiniteMana`,
`CharaterOptimization`). Ce sont les noms du jeu : les corriger ferait échouer
l'appel.

## Les caméras (deux systèmes distincts)

- **`cam`** → `ToggleDebugCamera`, la caméra libre du **moteur**, exposée par le
  CheatManager. Vol libre, sélection d'acteurs.
- **`cam spawn`** → `AYgroGameMode::SpawnDebugCamera`, le **spectateur du jeu**
  (`BP_YgroSpectatorPawn`). 16 entrées manette déjà mappées : sticks = vol et
  visée, RT/LT = monter/descendre, LB/RB = FOV, A = profondeur de champ,
  D-Pad = mise au point et ouverture, **X = ralenti, B = accéléré**, L3/R3 =
  vitesses.

## Les maps de dev

Seules ces cinq-là sont **réellement packagées** (vérifié dans l'index `.utoc`) :

| Alias | Map | Contenu |
|---|---|---|
| `tree` | `YGRO_TreeOnly_P` | Big Tree isolé, « micro LD, no visual pass » |
| `grid` | `GridSandBox` | bac à sable grille + mares de fluides |
| `debug` | `YGRO_DEBUG` | map de debug |
| `struct` | `TestingStructures` | structures de test (PreProd) |
| `light` | `LD_LightingProto` | prototype d'éclairage |
| `game` | `YGRO_P` | retour au jeu |

⚠️ **Charger une map quitte la partie en cours.** Sauvegarde avant.

**Ne cherche pas `NewGym` ni `ArenaDifficultyTests`** (les deux entrées de LOAD
LEVEL) : elles sont absentes du pak, d'où le retour au menu principal. Idem pour
`QuarryOnly` / `VolcanoOnly` / `WonderOnly` / `BastionOnly`, qui ne sont que
référencés par les configs de grille. `YGRO_TreeOnly_P` est le seul survivant.

## Le mécanisme du menu

Les boutons `Button_Debug`, `Button_Load`, `Button_Checkpoint` ont leur
`Visibility` pilotée par un binding `EBindingKind::Function`, réévalué à chaque
frame. Bytecode Kismet désassemblé, structure identique pour les trois :

```
si (Build Config == 1)  ->  Collapsed        [FIN : les cheats ne sont pas testés]
sinon                   ->  Visible SI IsValid(PlayerController->CheatManager)
```

**Double verrou** : `Build Config` (`ByteProperty`, enum `E_BuildConfig` où
`0 = Debug`, `1 = Shipping`) puis le CheatManager. La build publique vaut `1`,
ce qui masque les boutons avant tout test de cheat — d'où l'inefficacité d'un
`EnableCheats` seul en console.

Les quatre boutons de `devmenu extra` n'ont **aucun binding** : ils sont masqués
par du code impératif au `Construct`, et il suffit de forcer leur visibilité.

## État de validation

**Validé en jeu** (21/07/2026, build 1.0.27900) :
- `devmenu` — les boutons apparaissent
- `EnableCheats` — `Fly` répond « you feel much lighter »
- écriture d'une propriété au nom contenant une espace : `w["Build Config"] = 0`

**Non testé** : `cheat` (les 23), `cam`, `devmap`. Tout est protégé par `pcall`
et rapporte son échec, mais un appel peut avoir un effet inattendu. Le catalogue
des cheats vient de l'extract de la démo (30/06) ; la build 27900 peut différer.

**Prudence** : `checkpoint`, `squad`, `optimize`, `perf` touchent à l'état du
monde. `devmap` quitte la partie.

## Historique

- **v5** — correction du crash de `devmap` : `UGameplayStatics::OpenLevel` prend un
  **FName** en 2e paramètre ; lui passer une chaîne Lua provoque un
  `EXCEPTION_ACCESS_VIOLATION` en lecture `0x70`
  (`LuaType::push_nameproperty`). `devmap` passe désormais par la commande
  console `open`, qui ne manipule que des chaînes. Même risque identifié sur
  `cheat checkpoint` (paramètre **FText**) : verrouillé derrière un `force`
  explicite tant qu'il n'est pas vérifié.
- **v4** — `cam` (deux systèmes de caméra) et `devmap` (5 maps de dev).
- **v3** — les 23 fonctions du CheatManager en commandes `cheat`.
- **v2** — correction du crash : le `Ar` (FOutputDevice) d'un handler n'est
  valide que dans le corps **synchrone**. L'utiliser dans
  `ExecuteInGameThread`/`LoopAsync` provoque un `EXCEPTION_ACCESS_VIOLATION` en
  lecture `0x8`. `pcall` ne protège pas : violation native, pas erreur Lua.
- **v1** — menu dev seul, crashait au premier appel de commande.
