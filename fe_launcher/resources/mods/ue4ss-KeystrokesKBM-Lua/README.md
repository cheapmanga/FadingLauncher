# Keystrokes KB+M (Lua) — Fading Echo

Input display **clavier + souris** en **pur Lua** — aucune compilation.
Overlay dessiné sur le HUD du jeu (`AYgroHUD`), input lu via le PlayerController.

## Install
Copie le dossier dans les mods UE4SS (comme tes autres mods Lua) :
```
...\UE_YGRO\Binaries\Win64\ue4ss\Mods\KeystrokesKBM-Lua\
├── enabled.txt          (vide)
└── Scripts\
    └── main.lua
```
Puis vérifie qu'il est activé (`enabled.txt` présent, ou ligne `KeystrokesKBM-Lua : 1`
dans `Mods\mods.txt`).

## En jeu
- **F8** = afficher / masquer l'overlay.
- **F9** = auto-diagnostic → ouvre la console UE4SS (Ctrl+O), lis les lignes `[KeystrokesKBM]`.

## Si ça n'affiche rien
C'est du best-effort non testé en jeu. Lance **F9** et regarde la console :
- `PlayerController : INTROUVABLE` → l'input ne peut pas être lu (rare).
- `IsInputKeyDown('W') : NON` → la façon de passer l'FKey est à ajuster (envoie-moi le message d'erreur).
- `HUD hook déclenché 0 fois` → le HUD du jeu ne déclenche pas `ReceiveDrawHUD` → il faudra
  accrocher une autre fonction (envoie-moi le retour, je change la cible du hook).
- `Font Roboto : INTROUVABLE` → les pavés s'affichent mais sans texte (pas bloquant).

Envoie-moi la sortie F9 et je corrige.

## Personnaliser
- **Tes binds** : table `KEYS` en haut de `main.lua` (label + `fkey` = nom d'FKey Unreal).
- Position / taille / couleurs : constantes `ORIGIN_X/Y`, `CELL`, `BOX`, `C_*`.
