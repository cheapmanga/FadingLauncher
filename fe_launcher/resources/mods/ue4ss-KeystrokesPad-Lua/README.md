# Keystrokes Pad (Lua) — Fading Echo

Input display **manette** en **pur Lua** — aucune compilation.
Overlay dessiné sur le HUD (`AYgroHUD`). Boutons via `IsInputKeyDown`, gâchettes via
`GetInputAnalogKeyState`, sticks via `GetInputAnalogStickState` (analogique = best-effort).

## Install
```
...\UE_YGRO\Binaries\Win64\ue4ss\Mods\KeystrokesPad-Lua\
├── enabled.txt          (vide)
└── Scripts\
    └── main.lua
```
Activer via `enabled.txt` ou `Mods\mods.txt` (`KeystrokesPad-Lua : 1`).

## En jeu
- **F8** = afficher / masquer.
- **F9** = auto-diagnostic (console UE4SS, lignes `[KeystrokesPad]`).

## Si des éléments manquent
Best-effort non testé. Lance **F9** :
- boutons KO → nom d'FKey manette à corriger (ex. `Gamepad_Special_Right` selon la version UE).
- gâchettes/sticks à 0 → `GetInputAnalog*` peut renvoyer autrement dans cette build ;
  envoie-moi les lignes du diagnostic, j'ajuste les enums/retours.
- `HUD hook = 0` → cible de hook à changer.

⚠️ Manette **DirectInput pure** (certaines PS/génériques) peut ne pas remonter comme
`Gamepad_*` dans Unreal → wrapper XInput (DS4Windows) recommandé.

## Personnaliser
Tables `BUTTONS` / `TRIGGERS` en haut de `main.lua` ; enum sticks `STICK_LEFT/RIGHT`.
