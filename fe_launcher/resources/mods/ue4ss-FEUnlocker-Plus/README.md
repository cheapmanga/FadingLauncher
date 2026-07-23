# FE Unlocker (Lua) — Fading Echo

Périmètre d'origine du **FE Unlocker** : les fonctions de base, rien de plus.
Pur Lua, drop-in (comme tes autres mods).

## Touches

| Touche | Effet | Type | Fiabilité |
|---|---|---|---|
| **F1** | Désactive les murs rouges (Alpha Blockers) | action | ✅ |
| **F2** | **Active** les escaliers rotatifs (les déploie) | action | ✅ même moteur que l'ascenseur (voir plus bas) |
| **F3** | Ascenseur le plus proche : **le fait réellement bouger** | action | ✅ corrigé (voir plus bas) |
| **F4** | Aide (liste des touches, dans la console UE4SS) | action | ✅ |

Le **déblocage des zones** (toutes les 7, automatiquement au chargement) et la
**ré-désactivation automatique des murs alpha** tournent en fond.

Toute la sortie va dans la **console UE4SS** (Ctrl+O). Chaque ligne commence par `[Unlocker]`.

## Console in-game (F10)

Tape ces commandes directement dans la console du jeu :

| Commande | Effet |
|---|---|
| `unlock list` | liste tous les ascenseurs chargés, **numérotés**, avec nom, course et distance |
| `unlock <n°>` | active l'ascenseur par son numéro dans la liste (ex. `unlock 4`) |
| `unlock <n°> tp` | l'active **et t'y téléporte** (tu apparais 2 m au-dessus de la plateforme) |
| `unlock zones` | débloque toutes les zones tout de suite (le mod le fait déjà seul au chargement) |
| `unlock door` | ouvre la porte la plus proche de toi |
| `core waste` / `core fire` / `core water` / `core glitch` | fait apparaître un core élémentaire et te le met en main |
| `core power` | fait apparaître un **PowerCore** (`BP_PortableItem_Power`) et te le met en main |
| `core <type> nograb` | le core apparaît **par terre sans être attrapé** (pour tester l'infinite core : spawn en forme de One sans l'absorber) |

Le plus simple : `unlock list`, puis `unlock <numéro>`. Le numéro est **figé** au moment
du `list`, donc il reste valable même si tu bouges ensuite (l'ordre par distance changerait
sinon). Si l'ascenseur a été déchargé entre-temps, la commande te dit de refaire `unlock list`.

Le nom complet marche toujours aussi (`unlock bastion-tour-1`) : slug exact d'abord, sinon
sous-chaîne du slug ou du label ; si plusieurs collent, la commande liste les candidats.
`tp` peut se mettre n'importe où.

> Techniquement : hook `RegisterConsoleCommandGlobalHandler("unlock", …)` de UE4SS,
> qui intercepte la commande dans la **console UE** du jeu. Si la boîte ouverte par F10
> chez toi n'est **pas** la console UE standard (widget custom), la commande ne sera pas
> captée — dis-le moi et on branchera autrement.

## Install
```
...\UE_YGRO\Binaries\Win64\ue4ss\Mods\FEUnlocker-Plus\
├── enabled.txt        (vide)
└── Scripts\
    └── main.lua
```
> Désactive ton ancien **FE Unlocker** pour éviter les doublons de raccourcis (F1-F4).

## Escaliers rotatifs (F2) — activation, pas suppression

`BP_RotatorStairs_C` est rangé sous `GameplayElements/MovingObject/` et **hérite de
`BP_MovingObject_C`** — exactement comme l'ascenseur. Son mesh `SM_TopStairRotator` est
attaché à `MoverRoot`, et le `MoverTimeline` le fait **pivoter**. « Activer » un escalier =
lancer le même moteur que l'ascenseur (`UpdateMoverState` + `PlayMover` / `ReverseMover`).

Seule différence de traitement : l'escalier **tourne sur place**, donc `MoverRoot` ne se
translate pas. Pour vérifier que ça a bougé, le mod échantillonne `SM_TopStairRotator`
(le mesh, décalé du pivot), pas `MoverRoot`.

F2 active **tous** les escaliers rotatifs actuellement chargés (comme l'ancien F2 les
désactivait tous d'un coup).

> **Correctif « ils bougent puis reviennent »** : l'escalier pivote *sur place*, donc son
> `MoverRoot` change de **rotation** mais garde la même **position**. La détection de mouvement,
> qui ne regardait que la position, croyait que rien n'avait bougé et **relançait le timeline en
> sens inverse** → l'escalier revenait à l'origine. La détection compare désormais aussi la
> rotation (seuil 1°), donc le premier déploiement est reconnu et l'escalier reste en place.

## Cores — `core <élément>`

`core waste | fire | water | glitch` fait apparaître le core correspondant devant toi et te le
met en main. Les cores sont des acteurs `BP_PortableItem_<X>Ball` (dérivent de `BP_PortableItem_C`) ;
on les **spawn** (`GameplayStatics.BeginDeferredActorSpawnFromClass` + `FinishSpawningActor`, transform
via `KismetMathLibrary.MakeTransform`) puis on appelle `player:StartGrab(ball)`. Le grab déclenche
tout seul la charge élémentaire du jeu (UI + prompt LB + pouvoir).

Correspondance : `fire → Lava`, `glitch → Corruption` (les 4 éléments réels sont Water, Waste, Lava,
Corruption). Si la classe d'un core n'est pas encore chargée en mémoire, la commande le dit :
approche-toi une fois d'un core de cet élément puis réessaie.

## Portes — `unlock door`

Ouvre la porte la plus proche de toi. Toutes les portes (`BP_SimpleMovingDoor_C`,
`BP_GameplayDoor_C`, `BP_GameplayDoorBastion_C`, `BP_GameplayDoor_PERKS_C`) dérivent de
`BP_MovingObject_C` — même moteur que les ascenseurs.

Le mod cherche la porte la plus proche et joue son timeline avec **`PlayMover`** — puis c'est
tout : appel **synchrone**, aucune vérification différée.

> **Pas de re-lecture après coup.** Beaucoup de portes sont des portes de **transition** :
> les ouvrir déclenche un changement de zone qui **détruit l'acteur porte**. Relire sa position
> quelques centaines de ms plus tard (pour confirmer le mouvement) = lecture de **mémoire libérée**
> → CRASH (et `IsValid()` ne protège pas d'un objet fraîchement détruit). On se contente donc de
> `PlayMover` et on ne retouche plus la porte.

> **Ne pas appeler les fonctions « pratiques » de porte.** `Unlock(nom, instant)`,
> `MoveForward(instant)`, `MoveReverse(instant)` existent bien et ont la bonne signature, **mais
> ce sont des BlueprintEvents qui, appelés à froid hors de leur contexte, déréférencent un
> composant nul → CRASH natif** (access violation, non rattrapable par `pcall`). Idem pour
> `UpdateMoverState`, que les portes redéfinissent. On s'en tient donc à `PlayMover`/`ReverseMover`,
> la fonction de base `BP_MovingObject` non redéfinie, qui bouge le battant sans risque.

## Déblocage des zones (automatique)

`DemoAllowedLevels` (sur `BP_LevelLoader_C`) est la liste des zones autorisées par la démo :
des data-assets `DA_Levels_C`. Par défaut la démo n'en autorise que **4** (MainMenu, Tutorial,
Bastion, Volcano). Le jeu compte **7 zones** (enum `E_LevelZone` : Bastion=0, BigTree=1,
Volcano=2, Quarry=3, Wonder=4, Tutorial=5, MainMenu=8 ; 7=None ignoré).

Le mod remplit `DemoAllowedLevels` en deux passes :
1. **Récolte** (sûre, lecture seule) : les `DA_Levels_C` déjà chargés, filtrés par liste blanche
   des 7 noms réels (`FindAllOf`).
2. **Complément** : s'il en manque encore (une zone verrouillée n'est pas forcément chargée), on
   résout les zones absentes via `LevelLoader:GetLevelZoneAsset(E_LevelZone)`. Cette passe ne tourne
   **que tant que les 7 n'y sont pas** — elle s'arrête d'elle-même dès que c'est complet.

**Anti-téléport du premier chargement.** Au tout premier chargement, le jeu contrôle « zone
verrouillée → téléport vers `LockedLevelFallbackDestination` ». Pour réduire la fenêtre avant ce
contrôle, le peuplement tente d'abord des **essais rapides** (toutes les 300 ms pendant ~6 s), puis
une boucle lente de secours (3 s). Un hook `LoadZone` reste en filet, et `unlock zones` force à la main.

> **Réserve honnête** : si le contrôle se déclenche *avant* que le LevelLoader / les assets de zone
> n'existent, même les essais rapides peuvent arriver trop tard et le TP du tout premier chargement
> peut persister. Le téléport est câblé en dur dans le blueprint (cible `LockedLevelFallbackDestination`) :
> le neutraliser proprement demanderait d'identifier la fonction exacte au runtime. À voir si ça reste
> gênant.

## Le bug de l'ascenseur (état OK, visuel OK, aucun mouvement)

Relevé sur l'export du jeu, `BP_Elevator_C` hérite de `BP_MovingObject_C`. Deux mécanismes
**distincts** y cohabitent :

| | Fonction | Effet |
|---|---|---|
| État | `UpdateMoverState(E_MoverState)` | écrit la variable `MoverState` + broadcast `OnMoverStateUpdated` |
| Mouvement | `MoverTimeline` via `PlayMover()` / `ForceElevatorToMove(Direction)` | déplace réellement `MoverRoot` |

L'ancien F3 n'appelait que `UpdateMoverState(2)`. Or `2 = E_MoveToEnd` : le jeu enregistre
l'ascenseur comme activé et l'activateur repasse au bleu (`ElevatorUnlockedColor = 00CCFF`),
mais **personne ne lance jamais le timeline**. D'où le symptôme exact observé.

Les autres champs qu'il forçait (`bIsActive`, `bIsMoving`, `bTriggered`, `bPlayerOnTop`…)
**n'existent pas** sur la classe — les vrais noms sont `ElevatorActivated`, `bUnlocked`,
`bElevatorCalled`. Ces `pcall` échouaient en silence.

**Correctif :** l'état continue de passer par l'API du jeu (`UpdateMoverState`), donc l'ascenseur
reste « activé » et bleu, et **aucune variable d'état n'est écrite à la main**. On lance le mouvement
qui manquait via `PlayMover()` / `ReverseMover()` (le timeline). Le sens est déduit de `MoverState`
(lecture seule) — voir les pièges plus bas.

> **On n'utilise PAS `ForceElevatorToMove`** : sur `BP_Elevator`, cette fonction appelle
> `ForcePlayerOnElevator` (`GetPlayerPawn` + `AttachToComponent` + `TeleportTo`), qui **téléporte le
> joueur sur la plateforme** — même pour un ascenseur distant activé à la console (`unlock <n°>` sans
> `tp`). `PlayMover` / `ReverseMover` déplacent la plateforme sans toucher au joueur. Le TP n'a lieu
> que si tu demandes explicitement `tp`.

Le mod **vérifie** ensuite que ça a bougé : il échantillonne la position de `MoverRoot` avant/après
(700 ms) et te le dit dans la console. `MoverRoot` et pas l'acteur, parce que c'est le composant
que le timeline déplace — le root de l'Actor, lui, ne bouge pas. S'il ne bouge pas, il retente
**une fois** dans l'autre sens.

### E_MoverState (valeurs réelles)
`0` WaitingStart · `1` WaitingEnd · `2` MoveToEnd · `3` MoveToStart · `4` CustomMove · `5` Interupted

## Deux pièges relevés dans les données des niveaux

**`bStartFromEnd = true`** sur une bonne partie des instances (dont `bastion-center`).
`InitializeMoverTransform` place alors la plateforme d'emblée en position **FIN**. Lui demander de
jouer le timeline « en avant » (vers FIN) ne produit donc **aucun mouvement** : elle y est déjà.
Le mod lit `MoverState` et part dans le sens qui a du sens (`ReverseMover` / `Backward` si l'état
est `E_MoverWaitingEnd`). Si ça ne bouge toujours pas, il **retente une fois en sens inverse**,
puis te le dit.

**`bUnlocked = false`** sur la plupart des instances placées (le défaut de la classe est `true`).
Le mod te prévient dans la console quand c'est le cas : un ascenseur verrouillé peut refuser de partir.

> La table `ELEVATOR_DB` (51 ascenseurs extraits des `.umap` : `bStartFromEnd`, course, altitude)
> reste utilisée en interne par F3 pour choisir le bon sens de trajet et étiqueter l'ascenseur
> dans la console.

## Prochaines améliorations

Tu voulais repartir du périmètre d'origine avant d'y ajouter tes propres idées — dis-moi
lesquelles et on les greffe une par une.
