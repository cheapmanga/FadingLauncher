# Portraits des personnages

Ce dossier reçoit les vignettes affichées dans la page **Skins**. Elles ne sont **pas**
versionnées : ce sont des ressources du jeu *Fading Echo* (© Fishing Cactus / Ygro), qui
ne peuvent pas être redistribuées ici. Le launcher fonctionne sans — il affiche alors une
pastille avec l'initiale du personnage à la place de chaque image manquante.

## Comment les obtenir

Depuis votre propre copie du jeu, avec [FModel](https://fmodel.app/) :

1. Ouvrez le jeu dans FModel.
2. Exportez en PNG le contenu de ces deux dossiers :
   - `UE_YGRO/Content/Game/UI/UI_VS/Avatars/`  (`T_RadioPic_*`, `HUD_Avatar_*`)
   - `UE_YGRO/Content/DataCollections/Enemies/Thumbnail/`  (`T_TN_*`)
3. Déposez les `.png` obtenus **dans ce dossier**.

Le launcher associe automatiquement chaque image au bon personnage d'après son nom
(`T_RadioPic_Kheleb.png` → Kheleb, `T_TN_CritterWater_Shard.png` → Critter…). Aucun
renommage n'est nécessaire.
