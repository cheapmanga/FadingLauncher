# UE4SS embarqué — source et attribution

Ce dossier contient une copie d'**UE4SS** (le dossier `ue4ss/` et le proxy `dwmapi.dll`),
le programme qui permet à Unreal Engine de charger des mods. UE4SS est un projet tiers,
distribué sous sa propre licence (voir `ue4ss/LICENSE`).

**Build utilisé** — la nightly *experimental* qui fonctionne sur ce jeu (fork UE 5.6.1) :

    https://github.com/UE4SS-RE/RE-UE4SS/releases/download/experimental-latest/zDEV-UE4SS_v3.0.1-1012-gc838a8ac.zip

Projet UE4SS : https://github.com/UE4SS-RE/RE-UE4SS

## Pourquoi une copie embarquée plutôt qu'un téléchargement

Le build standard de la release stable **ne démarre pas** sur ce jeu : il lui manque les
templates de disposition mémoire (`MemberVarLayoutTemplates`, `VTableLayoutTemplates`) et
les réglages adaptés (`GraphicsAPI = opengl`, `RenderMode = ExternalThread`, nécessaires à
ce moteur en DirectX 12). Cette copie est l'install de référence, réglages compris, dans
la structure exacte qui fonctionne : `dwmapi.dll` dans `Win64\`, tout le reste dans
`Win64\ue4ss\`.

Les fichiers de débogage lourds et inutiles au fonctionnement (`.pdb`, dumps générés,
logs) ont été retirés pour alléger.
