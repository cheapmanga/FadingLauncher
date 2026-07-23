-- ============================================================================
--  FADING ECHO — SKINS  (v2)
--
--  Applique les skins cachés de One directement sur son mesh, sans passer par
--  le menu d'options (voir "POURQUOI PAS LE MENU" plus bas).
--
--  Commandes (console du jeu = touche ² , ou console UE4SS) :
--     skin              état + rappel des commandes
--     skin slots        liste les slots matériaux du joueur et leur contenu
--     skin one <0-4>    applique le jeu de matériaux Skin0..Skin4
--     skin reset        remet les matériaux d'origine
--     skin lock         réapplique en boucle (si le jeu écrase notre skin)
--     skin menu         tentative de branchement du spinner de Bob (voir plus bas)
--
--  Retours détaillés : FENÊTRE DE CONSOLE UE4SS.
--
--  ---------------------------------------------------------------------------
--  CE QUI EXISTE DANS LE JEU (build 1.0.27900)
--
--  Cinq jeux de matériaux complets, packagés, dont TROIS sans aucune entrée de
--  menu : /Game/Art/Character/Hero/Skin<N>/  avec, pour chaque N de 0 à 4 :
--      MI_MainCharaBody_Skin<N>       (corps)
--      MI_MainCharaHead_Skin<N>       (tête)
--      MI_MainCharaCape_cinematic_Skin<N>  (cape)
--  Le menu Customization n'expose que Default (Skin0) et "Hellgur One" (Skin1).
--
--  ---------------------------------------------------------------------------
--  POURQUOI PAS LE MENU (constaté, ne pas recommencer)
--
--  Options > Customization est piloté par des DataAssets :
--      DA_Skin_SubSection.OptionDescriptors = [ DA_Skin_One_Spinner ]
--  DA_Skin_Bob_Spinner existe, complet ("Marcel Bob", délégué SetSkin), mais
--  n'est référencé nulle part : asset orphelin, jamais raccordé par les devs.
--
--  L'AJOUT AU TArray FONCTIONNE (vérifié : 1 -> 2 entrées, relecture correcte),
--  MAIS L'AFFICHAGE NE CHANGE PAS : la liste est construite en C++ à la création
--  de l'écran d'options, et AUCUNE fonction de reconstruction n'est exposée
--  (UOptionMenuScreen n'a que 5 UFUNCTION, toutes de navigation ; UOptionSubsystem
--  n'expose que GetOption). Tenté après coup ET au démarrage : sans effet.
--  => On agit donc directement sur le mesh. 'skin menu' garde la tentative, pour
--     mémoire, mais elle ne change rien à l'UI.
--
--  ---------------------------------------------------------------------------
--  PIÈGES UE4SS DÉJÀ PAYÉS — NE PAS LES REFAIRE
--   1. `Ar` n'est valide QUE dans le corps SYNCHRONE du handler (sinon AV 0x8).
--   2. Une UFUNCTION n'est PAS une `function` Lua : ne jamais tester le type.
--   3. Jamais de chaîne Lua brute sur un paramètre FName/FText (AV 0x70).
--      => on utilise SetMaterial(index, mat), PAS SetMaterialByName(FName, mat).
-- ============================================================================

local UEHelpers = require("UEHelpers")

-- ============================================================================
--  APPLICATION AU DÉMARRAGE — piloté par le launcher (fe_launcher/core/skins.py)
--  Ces constantes sont réécrites par le launcher ; ne pas renommer les clés.
--  Le mod ne s'active QUE par console F10 en temps normal ; ce bloc permet
--  d'appliquer un skin dès le chargement, sans avoir à taper de commande.
-- ============================================================================
local BOOT_MESH    = "none"    -- alias de mesh à appliquer au démarrage, ou "none"
local BOOT_SKIN    = -1        -- skin de One à appliquer (0-4), ou -1 pour ne rien faire
local BOOT_OUTLINE = "keep"    -- "keep" | "off" | "on" : état de la silhouette au démarrage
local BOOT_HIDE_STICK  = false -- true = cacher le bâton (BP_Stick_C) au démarrage
local BOOT_HIDE_HAIR   = false -- true = cacher le bigoudi/cheveux (BP_Bigoudi_C) au démarrage
local BOOT_DELAY_MS = 4000     -- délai avant application (laisse le pawn se charger)

local SKIN_BASE = "/Game/Art/Character/Hero/Skin"
local PARTS = {                      -- motif de slot -> préfixe du matériau
    { key = "Body", asset = "MI_MainCharaBody_Skin" },
    { key = "Head", asset = "MI_MainCharaHead_Skin" },
    { key = "Cape", asset = "MI_MainCharaCape_cinematic_Skin" },
}

-- ⚠️ Les boucles de reapplication tournent toutes les 1,5 s : sans garde-fou
-- elles inondent la console et rendent impossible la lecture d'une commande
-- (constate 22/07). quietDepth > 0 = sortie supprimee. Les boucles s'executent
-- en mode silencieux et n'emettent qu'UNE ligne quand leur resultat CHANGE.
local quietDepth = 0
local function log(m)
    if quietDepth > 0 then return end
    print("[FESkins] " .. tostring(m) .. "\n")
end
local function loud(m) print("[FESkins] " .. tostring(m) .. "\n") end
local function quietly(fn)
    quietDepth = quietDepth + 1
    local ok, r = pcall(fn)
    quietDepth = quietDepth - 1
    if not ok then return nil end
    return r
end
local function say(Ar, m)            -- corps synchrone du handler UNIQUEMENT
    log(m)
    if Ar then pcall(function() Ar:Log("[FESkins] " .. tostring(m)) end) end
end

-- ---------------------------------------------------------------------------
--  Helpers
-- ---------------------------------------------------------------------------
-- ⚠️ `o:IsValid()` PLANTE si `o` n'est pas un UObject : "attempt to call a nil
-- value (method 'IsValid')". Cas réel (22/07) : itérer avec pairs() le TArray
-- renvoyé par K2_GetComponentsByClass sort des entrées non-objets.
-- TOUT test de validité passe par ici.
local function okObj(o)
    if not o then return false end
    local v = false
    pcall(function() v = o:IsValid() end)
    return v
end

local function isRealObject(o)
    if not okObj(o) then return false end
    local fn = ""
    pcall(function() fn = o:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function Name(o)
    if not okObj(o) then return "(nil)" end
    local n = "?"
    pcall(function() n = o:GetFullName() end)
    return n
end

local function ShortName(o)
    local n = Name(o)
    return string.match(n, "([^%.%s/]+)$") or n
end

local function GetPawn()
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do
            if isRealObject(c) then
                local pk
                pcall(function() pk = c.Pawn end)
                if isRealObject(pk) then return pk end
            end
        end
    end
    local list = FindAllOf("BP_CoreYgroCharacter_C")
    if list then
        for _, a in pairs(list) do if isRealObject(a) then return a end end
    end
    return nil
end

-- Le mesh du personnage est le SkeletalMeshComponent standard d'ACharacter
-- (CharacterMesh0, sur SK_Hero_facial).
local function GetMesh()
    local pawn = GetPawn()
    if not pawn then return nil, "joueur introuvable" end
    local m
    pcall(function() m = pawn.Mesh end)
    if okObj(m) then return m, nil end
    return nil, "composant Mesh introuvable sur le pawn"
end

-- ⚠️ Un asset dont le personnage n'est PAS présent dans la zone n'est pas chargé
-- en mémoire : StaticFindObject échoue tant que LoadAsset n'a pas abouti
-- (constaté 22/07 : SKEL_Agent / SKEL_Rusher / SKEL_Ranged / SK_Builder
-- introuvables alors que les chemins sont corrects).
-- On insiste donc : LoadAsset sous ses deux formes, puis plusieurs relectures.
local function Resolve(path)
    local short = string.match(path, "([^/]+)$")
    local full = path .. "." .. short
    local obj = StaticFindObject(full)
    if okObj(obj) then return obj end
    for _ = 1, 3 do
        pcall(function() LoadAsset(path) end)
        obj = StaticFindObject(full)
        if okObj(obj) then return obj end
        pcall(function() LoadAsset(full) end)
        obj = StaticFindObject(full)
        if okObj(obj) then return obj end
    end
    return nil
end

-- ---------------------------------------------------------------------------
--  Découverte des slots
--  On lit le matériau courant de chaque slot et on déduit sa nature (Body /
--  Head / Cape) depuis son nom. Plus fiable que de présumer un ordre d'index.
-- ---------------------------------------------------------------------------
local function ReadSlots()
    local mesh, err = GetMesh()
    if not mesh then return nil, err end
    local n = 0
    pcall(function() n = mesh:GetNumMaterials() end)
    if n == 0 then return nil, "aucun slot matériau (mesh pas encore initialisé ?)" end

    local slots = {}
    for i = 0, n - 1 do                       -- index moteur : 0-based
        local mat
        pcall(function() mat = mesh:GetMaterial(i) end)
        local nm = ShortName(mat)
        local part = nil
        for _, p in ipairs(PARTS) do
            if string.find(nm, p.key, 1, true) then part = p.key break end
        end
        slots[#slots + 1] = { index = i, mat = mat, name = nm, part = part }
    end
    return slots, nil
end

-- ---------------------------------------------------------------------------
--  Mémoire des matériaux d'origine (pour 'skin reset')
-- ---------------------------------------------------------------------------
local original = nil

local function RememberOriginal(slots)
    if original then return end
    original = {}
    for _, s in ipairs(slots) do original[s.index] = s.mat end
    log("matériaux d'origine mémorisés (" .. #slots .. " slots)")
end

-- ---------------------------------------------------------------------------
--  Application d'un skin
-- ---------------------------------------------------------------------------
local current = nil       -- index de skin appliqué, ou nil

local function ApplySkin(n)
    local mesh, err = GetMesh()
    if not mesh then return false, err end
    local slots, err2 = ReadSlots()
    if not slots then return false, err2 end
    RememberOriginal(slots)

    -- Résout les 3 matériaux du skin demandé.
    local mats = {}
    for _, p in ipairs(PARTS) do
        local path = SKIN_BASE .. n .. "/" .. p.asset .. n
        local m = Resolve(path)
        if m then mats[p.key] = m else log("  introuvable : " .. path) end
    end
    if not next(mats) then return false, "aucun matériau du Skin" .. n .. " n'a pu être chargé" end

    local applied, skipped = 0, 0
    for _, s in ipairs(slots) do
        local target = s.part and mats[s.part] or nil
        if target then
            if pcall(function() mesh:SetMaterial(s.index, target) end) then
                applied = applied + 1
            else
                log("  échec SetMaterial sur le slot " .. s.index)
            end
        else
            skipped = skipped + 1
        end
    end
    if applied == 0 then return false, "aucun slot n'a pu être associé (fais 'skin slots')" end
    current = n
    return true, applied .. " slot(s) appliqué(s), " .. skipped .. " ignoré(s)"
end

local function ResetSkin()
    if not original then return false, "aucun état d'origine mémorisé" end
    local mesh, err = GetMesh()
    if not mesh then return false, err end
    local n = 0
    for i, mat in pairs(original) do
        if mat and pcall(function() mesh:SetMaterial(i, mat) end) then n = n + 1 end
    end
    current = nil
    return true, n .. " slot(s) restauré(s)"
end

-- ============================================================================
--  BOB — le skin "Marcel Bob"
--
--  Le spinner DA_Skin_Bob_Spinner (orphelin, cf. en-tête) annonce un skin
--  "Marcel Bob". Les assets correspondants existent bien :
--      MI_BobSkin_Mustache / MM_Bob_Mustache   (matériaux)
--      SKEL_Bob_Mime                            (mesh dédié)
--  contre MI_BobSkin_body / SKEL_Bob pour la version par défaut.
--  => Marcel Bob = Bob en mime moustachu.
--
--  Par défaut on ne change QUE les matériaux (réversible, sans risque pour
--  l'animation). L'échange de mesh est derrière 'skin bob mime', explicite :
--  SKEL_Bob_Mime devrait partager SKEL_Bob_Skeleton, mais ce n'est pas vérifié.
-- ============================================================================
local BOB_BASE    = "/Game/Art/Character/Bob/"
local BOB_CLASSES = { "BP_Bob_Critter_C", "BP_Bob_Critter_Lava_C", "BP_Bob_Critter_Waste_C" }

local bobOriginalMats = nil     -- { [actorFullName] = { [slot] = mat } }
local bobOriginalMesh = nil     -- { [actorFullName] = skinnedAsset }
local bobMode         = nil     -- nil | "mime" | "standard" (pour le verrou)

-- ⚠️ DÉDUPLICATION OBLIGATOIRE : BP_Bob_Critter_Lava_C et _Waste_C HÉRITENT de
-- BP_Bob_Critter_C, donc FindAllOf sur la classe parente remonte aussi les
-- enfants. Sans ce filtre on traite le même acteur plusieurs fois (constaté en
-- jeu : "2 Bob trouvés" alors qu'il n'y en avait qu'un).
local function GetBobActors()
    local out, seen = {}, {}
    for _, cls in ipairs(BOB_CLASSES) do
        local ok, list = pcall(function() return FindAllOf(cls) end)
        if ok and list then
            for _, a in pairs(list) do
                if isRealObject(a) then
                    local k = Name(a)
                    if not seen[k] then seen[k] = true; out[#out + 1] = a end
                end
            end
        end
    end
    return out
end

local function GetBobMesh(actor)
    local m
    pcall(function() m = actor.Mesh end)
    if okObj(m) then return m end
    -- Repli : premier SkeletalMeshComponent trouvé sur l'acteur.
    pcall(function()
        local comps = actor:K2_GetComponentsByClass(StaticFindObject("/Script/Engine.SkeletalMeshComponent"))
        if comps then pcall(function() for _, c in pairs(comps) do if okObj(c) then m = c break end end end) end
    end)
    return okObj(m) and m or nil
end

-- ⚠️ LEÇON DU TEST EN JEU (22/07) : la structure des slots de Bob est
--      [0] MI_GlassSimple_EyeBob            -> yeux
--      [1] MI_BobSkin_body / MI_CharacterEnemy_Critter_<élément>  -> CORPS
--      [2] MM_Bob_Mustache                  -> MOUSTACHE (section de mesh dédiée)
-- MI_BobSkin_Mustache est donc le matériau DE LA MOUSTACHE, pas un skin de corps.
-- L'appliquer au corps ne donne rien de cohérent (testé, résultat aberrant).
-- « Marcel Bob » = le MESH SKEL_Bob_Mime, pas un échange de matériau.
--
--   mode "mime"     -> échange le mesh vers SKEL_Bob_Mime (le vrai Marcel Bob)
--   mode "standard" -> repose le corps sur MI_BobSkin_body (normalise une
--                      variante élémentaire vers le Bob de base)
-- keepMats = true -> après l'échange de mesh, on REPOSE les matériaux qui étaient
-- en place avant (les MID paramétrés par le jeu), au lieu de purger les overrides.
-- Hypothèse testée : MI_BobSkin_body brut rend NOIR parce que ses paramètres sont
-- injectés à l'exécution par le jeu ; les MID d'origine, eux, sont complets.
-- Le squelette est partagé (SKEL_Bob_Skeleton), donc l'échange est légitime.
local function ApplyBobSkin(mode, alsoMesh, keepMats)
    local actors = GetBobActors()
    if #actors == 0 then return false, "aucun Bob trouvé (il n'est pas chargé dans cette zone ?)" end

    local mat = (mode == "standard") and Resolve(BOB_BASE .. "MI_BobSkin_body") or nil
    local mesh = alsoMesh and Resolve(BOB_BASE .. "SKEL_Bob_Mime") or nil
    if alsoMesh and not mesh then log("  SKEL_Bob_Mime introuvable") end
    if not mat and not mesh then return false, "rien à appliquer (ni matériau ni mesh résolu)" end

    bobOriginalMats = bobOriginalMats or {}
    bobOriginalMesh = bobOriginalMesh or {}

    local touched, slots = 0, 0
    for _, a in ipairs(actors) do
        local comp = GetBobMesh(a)
        if comp then
            local key = Name(a)
            local n = 0
            pcall(function() n = comp:GetNumMaterials() end)

            if not bobOriginalMats[key] then       -- mémorise avant de toucher
                bobOriginalMats[key] = {}
                for i = 0, n - 1 do
                    local cur
                    pcall(function() cur = comp:GetMaterial(i) end)
                    bobOriginalMats[key][i] = cur
                end
                pcall(function() bobOriginalMesh[key] = comp:GetSkinnedAsset() end)
            end

            -- ⚠️ Les matériaux en place sont des MID_ créés à l'exécution par le
            -- jeu (variable DynamicMaterials du pawn) : leurs noms sont
            -- "MID_<materiau>_<numero>", PAS le nom de l'asset. Chercher
            -- "BobSkin" ne matchait donc rien (constaté en jeu).
            -- Règle retenue : on remplace tout SAUF les yeux et la moustache,
            -- qui sont des sections de mesh distinctes à conserver.
            -- Matériaux : uniquement en mode "standard", et uniquement sur le
            -- CORPS (ni les yeux, ni la moustache, qui sont des sections dédiées).
            if mat then
                for i = 0, n - 1 do
                    local cur
                    pcall(function() cur = comp:GetMaterial(i) end)
                    local nm = ShortName(cur)
                    local isEye  = string.find(nm, "Eye", 1, true) ~= nil
                    local isTash = string.find(nm, "Mustache", 1, true) ~= nil
                    if not isEye and not isTash then
                        if pcall(function() comp:SetMaterial(i, mat) end) then
                            slots = slots + 1
                            log("    slot " .. i .. " : " .. nm .. " -> " .. ShortName(mat))
                        end
                    end
                end
            end

            if mesh then
                local before = "?"
                pcall(function() before = ShortName(comp:GetSkinnedAsset()) end)
                local called = pcall(function() comp:SetSkinnedAssetAndUpdate(mesh, true) end)
                -- ⚠️ RELECTURE OBLIGATOIRE : SetSkinnedAssetAndUpdate ne lève PAS
                -- d'erreur si le mesh est refusé (squelette incompatible, etc.).
                -- Un appel "réussi" ne prouve donc rien — seule la relecture le fait.
                local after = "?"
                pcall(function() after = ShortName(comp:GetSkinnedAsset()) end)
                log("    mesh : " .. before .. " -> " .. after
                    .. (called and "" or "  (appel refusé)"))
                if after == before then
                    log("    !! le mesh N'A PAS CHANGÉ côté données : squelette incompatible,")
                    log("       ou le jeu le réimpose. Essaie 'skin lock'.")
                else
                    -- ⚠️ Après un échange de mesh, les OVERRIDES de matériaux posés
                    -- sur les anciens index RESTENT en place. Comme la nouvelle
                    -- géométrie n'a pas la même découpe en sections, des slots se
                    -- retrouvent avec un matériau inadapté ou vide -> rendu NOIR
                    -- (constaté en jeu le 22/07 sur la crinière).
                    -- Correctif : reposer les matériaux que le mesh déclare lui-même.
                    -- Lire USkeletalMesh:GetMaterials() ne donne rien d'exploitable
                    -- ici (tableau de structs FSkeletalMaterial : l'indexation
                    -- échoue depuis Lua, testé -> 0 récupéré).
                    -- On PURGE donc les overrides : sans override, le composant
                    -- retombe sur les matériaux que le mesh porte nativement.
                    local cleared, nn = 0, 0
                    pcall(function() nn = comp:GetNumMaterials() end)
                    if keepMats and bobOriginalMats[key] then
                        -- On repose les MID d'origine sur la nouvelle géométrie.
                        for i = 0, nn - 1 do
                            local om = bobOriginalMats[key][i]
                            if om and pcall(function() comp:SetMaterial(i, om) end) then
                                cleared = cleared + 1
                            end
                        end
                        log("    matériaux d'origine reposés : " .. cleared .. "/" .. nn)
                    else
                        for i = 0, nn - 1 do
                            if pcall(function() comp:SetMaterial(i, nil) end) then cleared = cleared + 1 end
                        end
                        log("    overrides purgés : " .. cleared .. "/" .. nn)
                    end
                    for i = 0, nn - 1 do
                        local cur
                        pcall(function() cur = comp:GetMaterial(i) end)
                        log("      [" .. i .. "] " .. ShortName(cur))
                    end
                end
            end
            touched = touched + 1
        end
    end
    if slots == 0 and not mesh then
        return false, touched .. " Bob trouvé(s) mais rien n'a été appliqué"
    end
    bobMode = mode
    return true, touched .. " Bob" .. (slots > 0 and (", " .. slots .. " slot(s)") or "") .. (mesh and " + mesh mime" or "")
end

-- ⚠️ La mémoire d'origine disparaît si l'état Lua du mod est rechargé (recopie
-- de main.lua en cours de partie). On sait cependant reposer le mesh de base
-- sans elle : SKEL_Bob est un asset, on le résout directement.
local function ResetBob()
    local fallbackMesh = Resolve(BOB_BASE .. "SKEL_Bob")
    if not bobOriginalMats then
        if not fallbackMesh then return false, "ni mémoire d'origine ni SKEL_Bob résolu" end
        local k = 0
        for _, a in ipairs(GetBobActors()) do
            local comp = GetBobMesh(a)
            if comp then
                pcall(function() comp:SetSkinnedAssetAndUpdate(fallbackMesh, true) end)
                local nn = 0
                pcall(function() nn = comp:GetNumMaterials() end)
                for i = 0, nn - 1 do pcall(function() comp:SetMaterial(i, nil) end) end
                k = k + 1
            end
        end
        bobMode = nil
        return true, k .. " Bob remis sur SKEL_Bob (repli, sans mémoire d'origine)"
    end
    local n = 0
    for _, a in ipairs(GetBobActors()) do
        local comp = GetBobMesh(a)
        local key = Name(a)
        if comp and bobOriginalMats[key] then
            for i, mat in pairs(bobOriginalMats[key]) do
                if mat and pcall(function() comp:SetMaterial(i, mat) end) then n = n + 1 end
            end
            local om = bobOriginalMesh and bobOriginalMesh[key]
            if om then pcall(function() comp:SetSkinnedAssetAndUpdate(om, true) end) end
        end
    end
    bobMode = nil
    return true, n .. " slot(s) restauré(s) sur Bob"
end

-- ============================================================================
--  REMPLACER LE MODÈLE DE ONE par n'importe quel mesh DÉJÀ DANS LE JEU
--
--  Même technique que pour Bob : SetSkinnedAssetAndUpdate + relecture + purge
--  des overrides. Fonctionne parce que les assets sont déjà cuits et chargés.
--
--  ⚠️ LIMITE DE SQUELETTE : One utilise SKEL_Hero_facial_Skeleton. Un mesh bâti
--  sur un AUTRE squelette (Bob, Rahne, ennemis…) sera rendu, mais l'animation
--  ne suivra pas : Unreal remappe les os PAR NOM, donc si les noms diffèrent le
--  modèle reste figé, en T-pose ou déformé. Seul SK_Hero_facial_optimization
--  partage le squelette de One (et lui ressemble donc trait pour trait).
--  Autrement dit : c'est à essayer, pas garanti. 'skin mesh reset' rétablit.
-- ============================================================================
local MESHES = {
    { "bob",       "/Game/Art/Character/Bob/SKEL_Bob",                          "Bob" },
    { "mime",      "/Game/Art/Character/Bob/SKEL_Bob_Mime",                     "Marcel Bob" },
    { "rahne",     "/Game/Art/Character/Rahne/SK_Rahne_facial",                 "Rahne" },
    { "agent",     "/Game/Art/Character/Agent/SKEL_Agent",                      "Agent" },
    { "critter",   "/Game/Art/Character/Critter/SKEL_Critter",                  "Critter" },
    { "builder",   "/Game/Art/Character/Builder/SK_Builder",                    "Builder" },
    { "kheleb",    "/Game/Art/Character/Kheleb/SKEL_Kheleb",                    "Kheleb" },
    { "ranged",    "/Game/Art/Character/Ranged/SKEL_Ranged",                    "Ranged" },
    { "rusher",    "/Game/Art/Character/Rusher/SKEL_Rusher",                    "Rusher" },
    -- ⚠️ SK_BungeeMan ne fait que 12 Ko : ce N'EST PAS le mesh (l'appliquer a mis
    -- le personnage à nil, donc invisible). Le vrai est SKM_BungeeMan (696 Ko).
    { "bungee",    "/Game/Art/Character/BungeeMan/SKM_BungeeMan",               "BungeeMan" },
    { "wonder",    "/Game/Art/Character/LastWonder/SKEL_LastWonder_Step01",     "Last Wonder" },
    { "wonder2",   "/Game/Art/Character/LastWonder/SKEL_LastWonder_Step02",     "Last Wonder (2)" },
    { "wonder4",   "/Game/Art/Character/LastWonder/SKEL_LastWonder_Step04",     "Last Wonder (4)" },
    { "wonder5",   "/Game/Art/Character/LastWonder/SKEL_LastWonder_Step05",     "Last Wonder (5)" },
    { "disappear", "/Game/Art/Character/Disappear/SKEL_Disappear",              "Disappear" },
    { "cine",      "/Game/Art/Character/Builder/SK_BuilderCINEMATIC",           "Builder (cinématique)" },
    { "mannequin", "/Game/SoStylized/Demo/Pawn/Mannequin/Character/Mesh/SK_Mannequin", "Mannequin Unreal" },
    { "hat",       "/Game/Art/Character/Rahne/SK_Rahne_hat",                    "Chapeau de Rahne (gag)" },
    -- ⚠️ ASSET EXTERNE : n'existe QUE si le pak custom est monté dans Content/Paks/.
    -- Resolve() echouera proprement tant que ce n'est pas le cas.
    -- Chemin releve via "Copier la reference" dans l'editeur UE 5.6 :
    --   /Script/Engine.SkeletalMesh'/Game/Test_Alien-Animal-Blender_2_81.Test_Alien-Animal-Blender_2_81'
    -- Attention au melange tirets/underscores : Test_Alien-Animal-Blender_2_81
    { "alien",     "/Game/Test_Alien-Animal-Blender_2_81",                      "Alien Animal (pak custom)" },
    { "one",       "/Game/Art/Character/Hero/Hero_Facial_Final/SK_Hero_facial", "One (d'origine)" },
    { "hero",      "/Game/Art/Character/Hero/Hero_Facial_Final/SK_Hero_facial", "One (alias)" },
}

local oneOriginalMesh = nil

-- ⚠️ DÉCLARATIONS ANTICIPÉES : SwapOneMesh (plus bas) appelle ces fonctions, mais
-- elles sont DÉFINIES APRÈS lui. Sans ces lignes, Lua les compile comme des
-- globales et elles valent nil à l'exécution
-- ("attempt to call a nil value (global 'HideStrayComponents')", constaté le 22/07).
local ListPawnMeshComponents, ClassOf, HideStrayComponents, UnhideStrayComponents
local HideAttachedActors, UnhideAttachedActors
local HideActorsByClass, ListNearbyActors, KNOWN_ATTACHMENTS
-- Tables d'etat : declarees ICI car SwapOneMesh (plus bas) les utilise,
-- alors que leur section d'origine vient apres lui.
local hidden, hiddenActors = {}, {}
local HandleOverlay
-- Module OUTLINE (silhouette noire) : declare ICI car HandleOverlay et la
-- boucle d'entretien les appellent avant leur definition (piege g).
local GetOverlayComp, CollectOverlaySMC, ReadState, DumpState
local KillOutline, RestoreOutline, DiagOutline
local outlineLocked = false
local meshSwapTarget = nil     -- mesh actuellement forcé, nil si aucun

-- Retrouve une entrée par son alias (colonne 1), puis par son libellé.
local function FindEntry(list, key)
    key = string.lower(key or "")
    if key == "" then return nil end
    for _, e in ipairs(list) do
        if string.lower(e[1]) == key then return e end
    end
    for _, e in ipairs(list) do
        if string.lower(e[3] or "") == key then return e end
    end
    return nil
end

local function SwapOneMesh(entry)
    local mesh, err = GetMesh()
    if not mesh then return false, err end
    local target = Resolve(entry[2])
    if not target then return false, "mesh introuvable : " .. entry[2] end

    if not oneOriginalMesh then
        pcall(function() oneOriginalMesh = mesh:GetSkinnedAsset() end)
        log("mesh d'origine de One mémorisé : " .. ShortName(oneOriginalMesh))
    end

    local before = "?"
    pcall(function() before = ShortName(mesh:GetSkinnedAsset()) end)
    pcall(function() mesh:SetSkinnedAssetAndUpdate(target, true) end)
    local after = "?"
    pcall(function() after = ShortName(mesh:GetSkinnedAsset()) end)
    log("  mesh : " .. before .. " -> " .. after)
    if after == before then
        return false, "le mesh n'a PAS changé (refusé par le moteur)"
    end

    -- Purge des overrides, sinon les matériaux de One restent collés sur la
    -- nouvelle géométrie et certaines sections rendent noir (cf. Bob).
    local nn = 0
    pcall(function() nn = mesh:GetNumMaterials() end)
    for i = 0, nn - 1 do pcall(function() mesh:SetMaterial(i, nil) end) end
    log("  overrides purgés : " .. nn)
    for i = 0, nn - 1 do
        local cur
        pcall(function() cur = mesh:GetMaterial(i) end)
        log("    [" .. i .. "] " .. ShortName(cur))
    end

    -- Cheveux, bâton… : composants du pawn ET acteurs attachés (les cheveux sont
    -- un ChildActor, invisible pour K2_GetComponentsByClass).
    -- ⚠️ LE « ONE NOIR » QUI SUIT LE JOUEUR : le pawn porte un
    -- BP_OverlayMeshComponent (cf. UOverlayMeshComponent dans le binaire) qui rend
    -- une COPIE du personnage. Il reste sur SK_Hero_facial après l'échange, d'où
    -- un double sombre collé au joueur (constaté 22/07).
    -- On lui applique le MÊME mesh, et à défaut on le masque.
    HandleOverlay(target)

    local h = HideStrayComponents(mesh)
    local a = HideAttachedActors() + HideActorsByClass(KNOWN_ATTACHMENTS, true)
    meshSwapTarget = target        -- active l'entretien permanent (voir la boucle)
    return true, entry[3] .. " appliqué (" .. nn .. " slots, "
                 .. h .. " composant(s) + " .. a .. " acteur(s) masqué(s))"
end

-- ---------------------------------------------------------------------------
--  Composants annexes de One (cheveux, bâton…)
--
--  Ce sont des composants DISTINCTS du mesh principal, attachés à des os du
--  squelette de One. Après un échange de modèle, ces os n'existent plus sur la
--  nouvelle géométrie : les composants retombent à l'origine du pawn et restent
--  visibles AUX PIEDS du joueur (constaté en jeu le 22/07 avec Rahne).
--  On les masque donc, et 'skin mesh reset' les réaffiche.
-- ---------------------------------------------------------------------------
-- (hidden : declaree plus haut)

-- ⚠️ Interroger SkeletalMeshComponent + StaticMeshComponent NE SUFFIT PAS :
-- les cheveux d'UE5 sont un GroomComponent, et d'autres accessoires peuvent
-- utiliser encore d'autres classes (constaté le 22/07 : cheveux et bâton de One
-- restaient visibles alors que rien n'était masqué).
-- UPrimitiveComponent est la classe mère de TOUT ce qui se rend à l'écran.
ListPawnMeshComponents = function()
    local pawn = GetPawn()
    if not pawn then return {} end
    local out, seen = {}, {}
    local cls = StaticFindObject("/Script/Engine.PrimitiveComponent")
    if not cls then return out end
    local comps
    pcall(function() comps = pawn:K2_GetComponentsByClass(cls) end)
    if not comps then return out end

    local function add(c)
        if okObj(c) then
            local k = Name(c)
            if not seen[k] then seen[k] = true; out[#out + 1] = c end
        end
    end

    -- Voie 1 : API TArray (le retour est un TArray, pas une table Lua).
    local n = 0
    pcall(function() n = comps:GetArrayNum() end)
    if n and n > 0 then
        for i = 1, n do
            local c
            pcall(function() c = comps[i] end)
            add(c)
        end
    else
        -- Voie 2 : repli, au cas où UE4SS rendrait une table classique.
        pcall(function()
            for _, c in pairs(comps) do add(c) end
        end)
    end
    return out
end

-- Nom de classe d'un composant, pour le diagnostic.
ClassOf = function(o)
    local n = "?"
    pcall(function() n = o:GetClass():GetFName():ToString() end)
    if n == "?" then pcall(function() n = o:GetClass():GetFullName() end) end
    return n
end

-- ---------------------------------------------------------------------------
--  ACTEURS ATTACHÉS (cheveux, bâton…)
--
--  ⚠️ Les cheveux de One ne sont PAS un composant du pawn : c'est un
--  ChildActorComponent (`BP_Bigoudi`, cf. Art/Character/Hair/Bigoudi/), donc un
--  ACTEUR À PART. K2_GetComponentsByClass ne rend que les composants DU PAWN et
--  ne le voit jamais — d'où « 0 composant masqué » alors que les cheveux
--  restaient à l'écran (22/07).
--  Le jeu fait la même chose lors du passage en forme eau : tout disparaît.
--  On passe donc par GetAttachedActors + SetActorHiddenInGame.
--  (GetChildActor n'est PAS exposé ; SetActorHiddenInGame et GetAttachedActors le sont.)
-- ---------------------------------------------------------------------------
-- (hiddenActors : declaree plus haut)

-- ⚠️ Ni K2_GetComponentsByClass ni GetAttachedActors ne remontent les cheveux
-- (constaté 22/07 : 0 composant, 0 acteur). BP_Bigoudi est un ChildActor VFX
-- (Art/VFX/Bigoudi/, Niagara NS_Bigoudi) : on le cherche donc par sa CLASSE,
-- ce qui ne dépend d'aucune énumération.
-- Identifiés en jeu (22/07) via 'skin mesh near' :
--   BP_Bigoudi_C = les cheveux (ChildActor VFX)   ✅ masquage confirmé
--   BP_Stick_C   = le bâton de One
KNOWN_ATTACHMENTS = { "BP_Bigoudi_C", "BP_Stick_C" }

HideActorsByClass = function(classes, hide)
    local n = 0
    for _, cls in ipairs(classes) do
        local list
        pcall(function() list = FindAllOf(cls) end)
        if list then
            for _, a in pairs(list) do
                if isRealObject(a) then
                    if pcall(function() a:SetActorHiddenInGame(hide) end) then
                        n = n + 1
                        if hide then hiddenActors[#hiddenActors + 1] = a end
                        log("    " .. (hide and "masqué" or "réaffiché") .. " : " .. ShortName(a))
                    end
                end
            end
        end
    end
    return n
end

-- Découverte : acteurs très proches du joueur (le bâton en fait partie).
ListNearbyActors = function(radius)
    local pawn = GetPawn()
    if not pawn then return {} end
    local ploc
    pcall(function() ploc = pawn:K2_GetActorLocation() end)
    if not ploc then return {} end
    local out = {}
    local all
    pcall(function() all = FindAllOf("Actor") end)
    if not all then return out end
    for _, a in pairs(all) do
        if isRealObject(a) and Name(a) ~= Name(pawn) then
            local l
            pcall(function() l = a:K2_GetActorLocation() end)
            if l then
                local dx, dy, dz = l.X - ploc.X, l.Y - ploc.Y, l.Z - ploc.Z
                local d = math.sqrt(dx * dx + dy * dy + dz * dz)
                if d < radius then out[#out + 1] = { actor = a, dist = d } end
            end
        end
    end
    table.sort(out, function(x, y) return x.dist < y.dist end)
    return out
end

-- ---------------------------------------------------------------------------
--  L'OUTLINE / LA SILHOUETTE NOIRE DE ONE
--
--  MÉCANISME RÉEL (établi statiquement le 22/07, cf. .utoc + PDB + decomp) :
--  le contour n'est PAS un overlay material et PAS le custom depth. C'est une
--  COQUE INVERSÉE : au BeginPlay, BP_OverlayMeshComponent DUPLIQUE le mesh du
--  personnage en créant des USkeletalMeshComponent supplémentaires
--  (GenerateSkeletalMeshes), auxquels il applique un MID issu de
--  MM_OutlineOverlay (TwoSided + Masked + Unlit + Thickness… = extrusion de
--  normales, couleur 0x101010, d'où le noir).
--
--  POURQUOI L'ANCIEN CODE ÉCHOUAIT (deux causes, la 2e est la vraie) :
--   1. UOverlayMeshComponent dérive de UActorComponent, PAS de USceneComponent :
--      il n'a NI GetChildrenComponents NI SetHiddenInGame. Les pcall
--      « réussissaient » sans rien faire (piège h : un appel sans erreur ne
--      prouve rien).
--   2. SURTOUT : les doubles sont attachés au composant "Mesh" du personnage
--      (K2_AttachToComponent). Ce sont des FRÈRES du composant manager, jamais
--      ses enfants. Descendre son arbre ne pouvait rien trouver.
--
--  ON AGIT DONC SUR LES SkeletalMeshComponent EUX-MÊMES, collectés par l'UNION
--  de trois sources (aucune n'est garantie peuplée à l'exécution) :
--      ov.SkeletalsOverlay                       (variable Blueprint)
--      ov.OutlineOverlay.SkeletalMeshComponents  (UOverlayMesh natif)
--      ov.StatusOverlay.SkeletalMeshComponents   (UOverlayMesh natif)
--
--  ⚠️ Le bytecode Blueprint n'est pas lisible (FModel ne l'exporte pas) : on ne
--  sait pas lequel de ces tableaux est réellement rempli. Les logs de
--  CollectOverlaySMC trancheront au premier essai en jeu.
-- ---------------------------------------------------------------------------

-- État SAUVEGARDÉ AVANT toute écriture, pour 'skin outline on'.
-- outlineSaved.comps = { { smc, vis, hid, cd } }   outlineSaved.ov = { … }
local outlineSaved = nil

GetOverlayComp = function()
    local pawn = GetPawn()
    if not pawn then return nil end
    local ov
    pcall(function() ov = pawn.BP_OverlayMeshComponent end)
    if okObj(ov) then return ov end
    -- Repli : balayage par nom de classe. Dédup sur GetFullName (piège e :
    -- FindAllOf / les énumérations remontent aussi les sous-classes).
    local seen = {}
    for _, c in ipairs(ListPawnMeshComponents()) do
        if okObj(c) then
            local fn = Name(c)
            if not seen[fn] then
                seen[fn] = true
                local sig = (ClassOf(c) or "") .. " " .. ShortName(c)
                if string.find(sig, "OverlayMeshComponent", 1, true) then return c end
            end
        end
    end
    return nil
end

-- Union des trois sources, dédupliquée sur GetFullName.
CollectOverlaySMC = function(ov)
    local out, seen = {}, {}
    local function push(o, src)
        if not okObj(o) then return end
        local fn = Name(o)
        if seen[fn] then return end
        seen[fn] = true
        out[#out + 1] = o
        log("      + " .. src .. " : " .. ShortName(o) .. " [" .. (ClassOf(o) or "?") .. "]")
    end
    -- Les TArray d'UE4SS se lisent GetArrayNum()+[i] ; repli pairs() si besoin.
    local function eatArray(arr, src)
        if arr == nil then log("      (" .. src .. " : nil)") return end
        local cnt = 0
        pcall(function() cnt = arr:GetArrayNum() end)
        if cnt and cnt > 0 then
            for i = 1, cnt do
                local e
                pcall(function() e = arr[i] end)
                push(e, src)
            end
        else
            pcall(function() for _, e in pairs(arr) do push(e, src) end end)
        end
    end

    local a
    pcall(function() a = ov.SkeletalsOverlay end)
    eatArray(a, "SkeletalsOverlay")

    for _, slot in ipairs({ "OutlineOverlay", "StatusOverlay" }) do
        local om
        pcall(function() om = ov[slot] end)
        if okObj(om) then
            local arr
            pcall(function() arr = om.SkeletalMeshComponents end)
            eatArray(arr, slot .. ".SkeletalMeshComponents")
        else
            log("      (" .. slot .. " : nil/invalide)")
        end
    end
    return out
end

-- Relecture d'un composant. Selon la version d'UE4SS la visibilité est exposée
-- en bVisible ou seulement via IsVisible() : on tente les deux. Un "?" dans le
-- log signifie « la relecture n'a rien prouvé », PAS « l'écriture a réussi ».
ReadState = function(smc)
    local vis, hid, cd, ass = "?", "?", "?", "?"
    pcall(function() vis = tostring(smc.bVisible) end)
    if vis == "?" or vis == "nil" then pcall(function() vis = tostring(smc:IsVisible()) end) end
    pcall(function() hid = tostring(smc.bHiddenInGame) end)
    pcall(function() cd = tostring(smc.bRenderCustomDepth) end)
    pcall(function() ass = ShortName(smc:GetSkinnedAsset()) end)
    return vis, hid, cd, ass
end

-- Journalise l'état de la liste et RENVOIE le nombre encore visibles.
-- C'est cette valeur qui décide si on descend d'un cran dans la cascade.
DumpState = function(list, tag)
    local alive = 0
    for _, smc in ipairs(list) do
        if okObj(smc) then
            local v, h, cd, a = ReadState(smc)
            local ko = (v ~= "false" and h ~= "true")
            if ko then alive = alive + 1 end
            log("      [" .. tag .. "] " .. ShortName(smc)
                .. "  bVisible=" .. v .. "  bHiddenInGame=" .. h
                .. "  customDepth=" .. cd .. "  asset=" .. a
                .. (ko and "   << TOUJOURS VISIBLE" or ""))
        end
    end
    log("      [" .. tag .. "] encore visibles : " .. alive .. " / " .. #list)
    return alive
end

-- Sauvegarde l'état d'origine UNE SEULE FOIS, avant la première écriture.
local function SaveOutlineState(ov, smcs)
    if outlineSaved then return end
    outlineSaved = { comps = {}, ov = {} }
    for _, smc in ipairs(smcs) do
        local v, h, cd = ReadState(smc)
        outlineSaved.comps[#outlineSaved.comps + 1] =
            { smc = smc, vis = v, hid = h, cd = cd }
    end
    pcall(function() outlineSaved.ov.mdd = ov["Max Draw Distance"] end)
    pcall(function() outlineSaved.ov.tick = ov.bTickEnabled end)
    pcall(function() outlineSaved.ov.one = ov.OwnerIsOne end)
    pcall(function() outlineSaved.ov.outMat = ov.OutlineMaterial end)
    pcall(function() outlineSaved.ov.staMat = ov.StatusMaterial end)
    log("  [outline] état d'origine mémorisé (" .. #outlineSaved.comps .. " composant(s))")
end

-- ---------------------------------------------------------------------------
--  DIAGNOSTIC — ne modifie RIEN
-- ---------------------------------------------------------------------------
DiagOutline = function()
    log("  [outline/diag] ---------------------------------------------")
    local pawn = GetPawn()
    if not pawn then log("  [outline/diag] joueur introuvable") return 0 end
    local ov = GetOverlayComp()
    if not okObj(ov) then
        log("  [outline/diag] BP_OverlayMeshComponent INTROUVABLE sur le pawn")
    else
        log("  [outline/diag] composant = " .. ShortName(ov) .. " [" .. (ClassOf(ov) or "?") .. "]")
        for _, k in ipairs({ "OwnerIsOne", "bTickEnabled" }) do
            local v = "?"
            pcall(function() v = tostring(ov[k]) end)
            log("      ov." .. k .. " = " .. v)
        end
        local mdd = "?"
        pcall(function() mdd = tostring(ov["Max Draw Distance"]) end)
        log("      ov['Max Draw Distance'] = " .. mdd)
        for _, k in ipairs({ "OutlineMaterial", "StatusMaterial" }) do
            local m
            pcall(function() m = ov[k] end)
            log("      ov." .. k .. " = " .. ShortName(m))
        end
    end

    local smcs = {}
    if okObj(ov) then smcs = CollectOverlaySMC(ov) end
    log("  [outline/diag] " .. #smcs .. " SkeletalMeshComponent d'overlay")
    DumpState(smcs, "diag")

    -- Matériaux portés par les doubles : ce sont des MID_ créés à l'exécution,
    -- leur nom n'est PAS celui de l'asset MI_OutlineOne (piège f).
    for _, smc in ipairs(smcs) do
        local n = 0
        pcall(function() n = smc:GetNumMaterials() end)
        for i = 0, n - 1 do
            local m
            pcall(function() m = smc:GetMaterial(i) end)
            log("      mat " .. ShortName(smc) .. "[" .. i .. "] = " .. ShortName(m))
        end
    end

    -- Le mesh principal : custom depth = système de ciblage, PAS la silhouette.
    local mesh = GetMesh()
    if okObj(mesh) then
        local v, h, cd, a = ReadState(mesh)
        log("  [outline/diag] Mesh principal " .. ShortName(mesh)
            .. " asset=" .. a .. " bVisible=" .. v .. " caché=" .. h .. " customDepth=" .. cd)
        local ovm
        pcall(function() ovm = mesh:GetOverlayMaterial() end)
        log("      GetOverlayMaterial() = " .. ShortName(ovm) .. "  (écarté : ce n'est pas le mécanisme)")
    end

    -- Tout autre SkeletalMeshComponent du pawn : candidats « doubles ».
    local mainFN = okObj(mesh) and Name(mesh) or "?"
    local seen = {}
    for _, c in ipairs(ListPawnMeshComponents()) do
        if okObj(c) then
            local fn = Name(c)
            if not seen[fn] and fn ~= mainFN
               and string.find(ClassOf(c) or "", "SkeletalMeshComponent", 1, true) then
                seen[fn] = true
                local v, h, cd, a = ReadState(c)
                log("      autre SMC : " .. ShortName(c) .. " asset=" .. a
                    .. " bVisible=" .. v .. " caché=" .. h .. " customDepth=" .. cd)
            end
        end
    end
    log("  [outline/diag] ---------------------------------------------")
    return #smcs
end

-- ---------------------------------------------------------------------------
--  SUPPRESSION — cascade E1 -> E6, chaque étape conditionnée par la RELECTURE
--  de la précédente (piège h). hard=true active l'étape 6, IRRÉVERSIBLE
--  jusqu'au rechargement du niveau.
-- ---------------------------------------------------------------------------
KillOutline = function(hard)
    local ov = GetOverlayComp()
    if not okObj(ov) then log("  [outline] BP_OverlayMeshComponent INTROUVABLE") return 0 end
    log("  [outline] composant = " .. ShortName(ov) .. " [" .. (ClassOf(ov) or "?") .. "]")

    local smcs = CollectOverlaySMC(ov)
    log("  [outline] " .. #smcs .. " SkeletalMeshComponent d'overlay collecté(s)")
    SaveOutlineState(ov, smcs)
    DumpState(smcs, "AVANT")

    -- ÉTAPE 1 — chemin officiel du jeu. UFUNCTION BlueprintCallable, un seul
    -- paramètre BoolProperty : aucun risque FName/FText (piège c).
    local ok1 = pcall(function() ov:SetOverlayHidden(true) end)
    log("  [outline] E1 SetOverlayHidden(true) appel=" .. tostring(ok1))
    if #smcs > 0 and DumpState(smcs, "E1") == 0 then
        log("  [outline] réglé dès l'étape 1")
        return #smcs
    end

    -- ÉTAPE 2 — action directe sur chaque double. Réplique littérale de
    -- UOverlayMesh::Deactivate (decomp : boucle SetVisibility sur le tableau).
    -- On CONTINUE même si ça prend : TagsChanged / UpdateOverlayByDistance
    -- peuvent réafficher.
    for _, smc in ipairs(smcs) do
        pcall(function() smc:SetVisibility(false, true) end)
        pcall(function() smc:SetHiddenInGame(true, true) end)
        pcall(function() smc:SetRenderCustomDepth(false) end)
    end
    log("  [outline] E2 SetVisibility/SetHiddenInGame sur " .. #smcs .. " composant(s)")
    if #smcs > 0 then DumpState(smcs, "E2") end

    -- ÉTAPE 3 — cull par distance. ⚠️ le nom de la variable Blueprint CONTIENT
    -- DES ESPACES : la notation crochets est OBLIGATOIRE.
    pcall(function() ov:SetMaxDrawDistance(1.0) end)
    pcall(function() ov["Max Draw Distance"] = 1.0 end)
    local mdd = "?"
    pcall(function() mdd = tostring(ov["Max Draw Distance"]) end)
    log("  [outline] E3 'Max Draw Distance' relu = " .. mdd)

    -- ÉTAPE 4 — bloquer la RÉGÉNÉRATION (tick -> UpdateOverlayByDistance).
    -- ⚠️ On n'appelle JAMAIS GenerateSkeletalMeshes (paramètre FName, et ça
    -- recréerait les doubles) ni UpdateOverlayParameters avec une string brute.
    pcall(function() ov:SetComponentTickEnabled(false) end)
    pcall(function() ov.OwnerIsOne = false end)
    local tick, one = "?", "?"
    pcall(function() tick = tostring(ov.bTickEnabled) end)
    pcall(function() one = tostring(ov.OwnerIsOne) end)
    log("  [outline] E4 bTickEnabled=" .. tick .. "  OwnerIsOne=" .. one)

    -- ÉTAPE 5 — filet de sécurité : tout SkeletalMeshComponent du pawn qui n'est
    -- PAS le Mesh principal et qui est encore visible. C'est l'étape décisive si
    -- les trois tableaux sont vides.
    local pawn, mainMesh = GetPawn(), nil
    if pawn then pcall(function() mainMesh = pawn.Mesh end) end
    local mainFN = okObj(mainMesh) and Name(mainMesh) or "?"
    local extra, seen = 0, {}
    for _, c in ipairs(ListPawnMeshComponents()) do
        if okObj(c) then
            local fn = Name(c)
            if not seen[fn] and fn ~= mainFN
               and string.find(ClassOf(c) or "", "SkeletalMeshComponent", 1, true) then
                seen[fn] = true
                local v, h, cd, a = ReadState(c)
                if v ~= "false" and h ~= "true" then
                    log("      [E5] rescapé " .. ShortName(c) .. " asset=" .. a)
                    if not outlineSaved.extra then outlineSaved.extra = {} end
                    outlineSaved.extra[#outlineSaved.extra + 1] =
                        { smc = c, vis = v, hid = h, cd = cd }
                    pcall(function() c:SetVisibility(false, true) end)
                    pcall(function() c:SetHiddenInGame(true, true) end)
                    local v2, h2 = ReadState(c)
                    log("      [E5] -> bVisible=" .. v2 .. "  bHiddenInGame=" .. h2)
                    extra = extra + 1
                end
            end
        end
    end
    log("  [outline] E5 " .. extra .. " composant(s) supplémentaire(s) traité(s)")

    -- ÉTAPE 6 — NUCLÉAIRE, uniquement sur 'skin outline hard'. Vide la géométrie
    -- des doubles, détruit les composants, puis neutralise la graine matériau
    -- pour que RegenerateMID ne recrée rien d'opaque. IRRÉVERSIBLE.
    if hard then
        for _, smc in ipairs(smcs) do
            pcall(function() smc:SetSkinnedAssetAndUpdate(nil, true) end)
            local _, _, _, a = ReadState(smc)
            log("      [E6] " .. ShortName(smc) .. " asset après vidage = " .. a)
        end
        for _, smc in ipairs(smcs) do
            local nm = ShortName(smc)
            pcall(function() smc:DestroyComponent(nil) end)
            local still = "?"
            pcall(function() still = tostring(okObj(smc)) end)
            log("      [E6] DestroyComponent " .. nm .. " -> encore valide=" .. still)
        end
        pcall(function() ov.OutlineMaterial = nil end)
        pcall(function() ov.StatusMaterial = nil end)
        local om, sm = "?", "?"
        pcall(function() om = ShortName(ov.OutlineMaterial) end)
        pcall(function() sm = ShortName(ov.StatusMaterial) end)
        log("      [E6] OutlineMaterial relu = " .. om .. "  StatusMaterial relu = " .. sm)
    end

    return #smcs
end

-- ---------------------------------------------------------------------------
--  RESTAURATION — remet l'état mémorisé AVANT la première suppression.
--  Sans effet sur ce que l'étape 6 a détruit (prévenir l'utilisateur).
-- ---------------------------------------------------------------------------
RestoreOutline = function()
    if not outlineSaved then return false, "rien à restaurer (outline jamais supprimé)" end
    local ov = GetOverlayComp()
    local n = 0

    local function put(rec)
        local smc = rec.smc
        if not okObj(smc) then
            log("      [restore] composant détruit, non restaurable : " .. tostring(rec.hid))
            return
        end
        pcall(function() smc:SetVisibility(rec.vis ~= "false", true) end)
        pcall(function() smc:SetHiddenInGame(rec.hid == "true", true) end)
        pcall(function() smc:SetRenderCustomDepth(rec.cd == "true") end)
        local v, h = ReadState(smc)
        log("      [restore] " .. ShortName(smc) .. " -> bVisible=" .. v .. " caché=" .. h)
        n = n + 1
    end

    for _, rec in ipairs(outlineSaved.comps) do put(rec) end
    for _, rec in ipairs(outlineSaved.extra or {}) do put(rec) end

    if okObj(ov) then
        pcall(function() ov:SetOverlayHidden(false) end)
        if outlineSaved.ov.mdd ~= nil then
            pcall(function() ov:SetMaxDrawDistance(outlineSaved.ov.mdd) end)
            pcall(function() ov["Max Draw Distance"] = outlineSaved.ov.mdd end)
        end
        pcall(function() ov:SetComponentTickEnabled(outlineSaved.ov.tick ~= false) end)
        if outlineSaved.ov.one ~= nil then pcall(function() ov.OwnerIsOne = outlineSaved.ov.one end) end
        if outlineSaved.ov.outMat ~= nil then pcall(function() ov.OutlineMaterial = outlineSaved.ov.outMat end) end
        if outlineSaved.ov.staMat ~= nil then pcall(function() ov.StatusMaterial = outlineSaved.ov.staMat end) end
        local mdd, tick, one = "?", "?", "?"
        pcall(function() mdd = tostring(ov["Max Draw Distance"]) end)
        pcall(function() tick = tostring(ov.bTickEnabled) end)
        pcall(function() one = tostring(ov.OwnerIsOne) end)
        log("      [restore] ov : MaxDrawDistance=" .. mdd .. " tick=" .. tick .. " OwnerIsOne=" .. one)
    end
    return true, n .. " composant(s) restauré(s)"
end

-- Compatibilité : l'échange de mesh et la boucle d'entretien appellent encore
-- HandleOverlay. Aligner les doubles sur le nouveau mesh ne marchait pas
-- (ils sont créés une fois au BeginPlay depuis SK_Hero_facial) : on supprime.
HandleOverlay = function(_target)
    return KillOutline(false)
end

HideAttachedActors = function()
    local pawn = GetPawn()
    if not pawn then return 0 end
    local list
    -- Selon les builds, UE4SS rend la sortie soit en retour, soit via l'out param.
    pcall(function() list = pawn:GetAttachedActors(nil, true, true) end)
    if not list then pcall(function() list = pawn:GetAttachedActors() end) end
    if not list then return 0 end

    local n, cnt = 0, 0
    pcall(function() cnt = list:GetArrayNum() end)
    local function tryHide(a)
        if not okObj(a) then return end
        if Name(a) == Name(pawn) then return end
        if pcall(function() a:SetActorHiddenInGame(true) end) then
            hiddenActors[#hiddenActors + 1] = a
            n = n + 1
            log("    acteur masqué : " .. ShortName(a))
        end
    end
    if cnt and cnt > 0 then
        for i = 1, cnt do
            local a
            pcall(function() a = list[i] end)
            tryHide(a)
        end
    else
        pcall(function() for _, a in pairs(list) do tryHide(a) end end)
    end
    return n
end

UnhideAttachedActors = function()
    local n = 0
    for _, a in ipairs(hiddenActors) do
        if okObj(a) and pcall(function() a:SetActorHiddenInGame(false) end) then n = n + 1 end
    end
    hiddenActors = {}
    return n
end

HideStrayComponents = function(mainMesh)
    local n = 0
    for _, c in ipairs(ListPawnMeshComponents()) do
        if Name(c) ~= Name(mainMesh) then
            local visible = true
            -- bHiddenInGame est une PROPRIÉTÉ (accès par point), pas une méthode.
            pcall(function() visible = not c.bHiddenInGame end)
            if visible then
                if pcall(function() c:SetHiddenInGame(true, true) end) then
                    hidden[#hidden + 1] = c
                    n = n + 1
                    log("    masqué : " .. ShortName(c) .. "  [" .. ClassOf(c) .. "]")
                else
                    log("    ÉCHEC masquage : " .. ShortName(c) .. "  [" .. ClassOf(c) .. "]")
                end
            end
        end
    end
    return n
end

UnhideStrayComponents = function()
    local n = 0
    for _, c in ipairs(hidden) do
        if okObj(c) and pcall(function() c:SetHiddenInGame(false, true) end) then
            n = n + 1
        end
    end
    hidden = {}
    return n
end

local function ResetOneMesh()
    local mesh, err = GetMesh()
    if not mesh then return false, err end
    local target = oneOriginalMesh
                or Resolve("/Game/Art/Character/Hero/Hero_Facial_Final/SK_Hero_facial")
    if not target then return false, "mesh d'origine introuvable" end
    pcall(function() mesh:SetSkinnedAssetAndUpdate(target, true) end)
    local nn = 0
    pcall(function() nn = mesh:GetNumMaterials() end)
    for i = 0, nn - 1 do pcall(function() mesh:SetMaterial(i, nil) end) end
    meshSwapTarget = nil        -- coupe l'entretien permanent
    HideActorsByClass(KNOWN_ATTACHMENTS, false)
    local u = UnhideStrayComponents()
    local ua = UnhideAttachedActors()
    return true, "One remis sur " .. ShortName(target)
                 .. " (" .. u .. " composant(s) + " .. ua .. " acteur(s) réaffiché(s))"
end

-- ---------------------------------------------------------------------------
--  Verrou : le pawn a une variable DynamicMaterials et le jeu peut réappliquer
--  ses propres matériaux (changement de forme, respawn…). Cette boucle remet
--  le skin choisi. AUCUN Ar ici.
-- ---------------------------------------------------------------------------
local locked = false

-- ⚠️ Masquer UNE FOIS ne tient pas : BP_Bigoudi est un ChildActor que le jeu
-- RECRÉE (respawn, changement de forme, streaming), et l'overlay se réaligne
-- sur le mesh d'origine. D'où un résultat qui « marche une fois sur deux »
-- (constaté 22/07). On réapplique donc tant qu'un échange est actif.
local lastAttachSig = nil
LoopAsync(1500, function()
    if meshSwapTarget then
        pcall(function()
            ExecuteInGameThread(function()
                local n = quietly(function()
                    local a = HideActorsByClass(KNOWN_ATTACHMENTS, true) or 0
                    local o = HandleOverlay(meshSwapTarget) or 0
                    return a .. "/" .. o
                end)
                if n and n ~= lastAttachSig then
                    lastAttachSig = n
                    loud("entretien du swap : " .. n .. " (acteurs/overlay)")
                end
            end)
        end)
    end
    return false
end)

-- Verrou d'outline : si le jeu réimpose la silhouette (changement de forme,
-- respawn, TagsChanged…), on relance la cascade. AUCUN `Ar` ici (piège a).
local lastOutlineSig = nil
LoopAsync(1500, function()
    if outlineLocked then
        pcall(function()
            ExecuteInGameThread(function()
                local r = quietly(function() return KillOutline(false) end)
                local sig = tostring(r)
                if sig ~= lastOutlineSig then
                    lastOutlineSig = sig
                    loud("verrou outline : etat -> " .. sig)
                end
            end)
        end)
    end
    return false
end)

LoopAsync(2000, function()
    if locked then
        pcall(function()
            ExecuteInGameThread(function()
                quietly(function()
                    if current then ApplySkin(current) end
                    -- Bob aussi : si le jeu reimpose son mesh/materiau, on le remet.
                    if bobMode then ApplyBobSkin(bobMode, bobMode == "mime") end
                end)
            end)
        end)
    end
    return false
end)

-- ---------------------------------------------------------------------------
--  Tentative "menu" conservée pour mémoire (sans effet sur l'affichage)
-- ---------------------------------------------------------------------------
local BASE_OPT = "/Game/Game/Option/DataAssets/Gameplay/Skin/"

local function AttachBobSpinner()
    local sub = Resolve(BASE_OPT .. "DA_Skin_SubSection")
    local bob = Resolve(BASE_OPT .. "DA_Skin_Bob_Spinner")
    if not (sub and bob) then return false, "DataAssets introuvables" end
    local arr
    pcall(function() arr = sub.OptionDescriptors end)
    if not arr then return false, "OptionDescriptors illisible" end
    local n = 0
    pcall(function() n = arr:GetArrayNum() end)
    for i = 1, n do
        local v
        pcall(function() v = arr[i] end)
        if v and Name(v) == Name(bob) then return true, "déjà branché (" .. n .. " entrées)" end
    end
    if not pcall(function() arr[n + 1] = bob end) then return false, "écriture refusée" end
    local after = 0
    pcall(function() after = arr:GetArrayNum() end)
    return after > n, "tableau " .. n .. " -> " .. after .. " (sans effet sur l'UI, voir en-tête)"
end

-- ---------------------------------------------------------------------------
--  Commande console
-- ---------------------------------------------------------------------------
RegisterConsoleCommandGlobalHandler("skin", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local key = (p[1] and string.lower(p[1])) or ""

    if key == "slots" then
        local slots, err = ReadSlots()
        if not slots then say(Ar, "ERREUR : " .. tostring(err)); return true end
        say(Ar, #slots .. " slot(s) matériau sur le joueur :")
        for _, s in ipairs(slots) do
            say(Ar, string.format("   [%d] %-40s -> %s", s.index, s.name, s.part or "(non associé)"))
        end
        say(Ar, "skin courant : " .. (current and ("Skin" .. current) or "origine"))
        return true
    end

    if key == "reset" then
        say(Ar, "restauration des matériaux d'origine…")
        locked = false
        ExecuteInGameThread(function()          -- pas de Ar ici
            local ok, msg = ResetSkin()
            log("reset -> " .. tostring(msg))
        end)
        return true
    end

    if key == "lock" then
        locked = not locked
        say(Ar, locked and "verrou ACTIF : le skin sera réappliqué toutes les 2 s."
                       or  "verrou levé.")
        return true
    end

    if key == "menu" then
        say(Ar, "tentative de branchement du spinner de Bob…")
        say(Ar, "(rappel : la liste du menu est figée à sa création, l'UI ne bougera pas)")
        ExecuteInGameThread(function()          -- pas de Ar ici
            local ok, msg = AttachBobSpinner()
            log("menu -> " .. tostring(msg))
        end)
        return true
    end

    if key == "mesh" then
        local sub = (p[2] and string.lower(p[2])) or ""
        if sub == "" or sub == "list" then
            say(Ar, "modèles disponibles (déjà dans le jeu) — usage : skin mesh <alias>")
            for _, m in ipairs(MESHES) do
                say(Ar, string.format("   %-9s %s", m[1], m[3]))
            end
            say(Ar, "skin mesh reset  -> remet One")
            say(Ar, "⚠️ squelette différent = modèle figé ou déformé. C'est attendu.")
            return true
        end
        if sub == "near" then
            local r = tonumber(p[3]) or 300
            local near = ListNearbyActors(r)
            say(Ar, #near .. " acteur(s) à moins de " .. r .. " unités :")
            for i = 1, math.min(#near, 25) do
                say(Ar, string.format("   %6.0f  %s", near[i].dist, ShortName(near[i].actor)))
            end
            return true
        end
        if sub == "hide" then
            local cls = p[3]
            if not cls then say(Ar, "usage : skin mesh hide <NomDeClasse_C>"); return true end
            say(Ar, "masquage de tous les " .. cls .. "…")
            ExecuteInGameThread(function()          -- pas de Ar ici
                log("masqués : " .. HideActorsByClass({ cls }, true))
            end)
            return true
        end
        if sub == "comps" then
            local comps = ListPawnMeshComponents()
            say(Ar, #comps .. " composant(s) mesh sur le joueur :")
            for _, c in ipairs(comps) do
                local hid = "?"
                pcall(function() hid = tostring(c.bHiddenInGame) end)
                say(Ar, string.format("   %-34s [%s] caché=%s", ShortName(c), ClassOf(c), hid))
            end
            return true
        end
        if sub == "show" then
            say(Ar, "réaffichage des composants masqués…")
            ExecuteInGameThread(function()          -- pas de Ar ici
                log("réaffichés : " .. UnhideStrayComponents())
            end)
            return true
        end
        if sub == "reset" or sub == "off" then
            say(Ar, "restauration du modèle de One…")
            ExecuteInGameThread(function()          -- pas de Ar ici
                local ok, msg = ResetOneMesh()
                log("mesh reset -> " .. tostring(msg))
            end)
            return true
        end
        local entry = FindEntry(MESHES, sub)
        if not entry then say(Ar, "inconnu : '" .. sub .. "' — tape 'skin mesh list'"); return true end
        say(Ar, "remplacement du modèle de One par " .. entry[3] .. "…")
        ExecuteInGameThread(function()              -- pas de Ar ici
            local ok, msg = SwapOneMesh(entry)
            log("skin mesh " .. sub .. " -> " .. (ok and msg or ("ÉCHEC : " .. tostring(msg))))
        end)
        return true
    end

    if key == "bob" then
        local sub = (p[2] and string.lower(p[2])) or ""
        if sub == "off" or sub == "reset" then
            say(Ar, "restauration de Bob…")
            ExecuteInGameThread(function()          -- pas de Ar ici
                local ok, msg = ResetBob()
                log("bob off -> " .. tostring(msg))
            end)
            return true
        end
        if sub == "slots" then
            local actors = GetBobActors()
            say(Ar, #actors .. " Bob trouvé(s)")
            for _, a in ipairs(actors) do
                local comp = GetBobMesh(a)
                if comp then
                    local n = 0
                    pcall(function() n = comp:GetNumMaterials() end)
                    say(Ar, "  " .. ShortName(a) .. " : " .. n .. " slot(s)")
                    for i = 0, n - 1 do
                        local cur
                        pcall(function() cur = comp:GetMaterial(i) end)
                        say(Ar, string.format("     [%d] %s", i, ShortName(cur)))
                    end
                end
            end
            return true
        end
        -- 'skin bob'          -> mime (c'est ÇA, Marcel Bob : le mesh)
        -- 'skin bob standard' -> repose le corps sur MI_BobSkin_body
        if sub == "standard" or sub == "body" then
            say(Ar, "corps de Bob -> MI_BobSkin_body…")
            ExecuteInGameThread(function()          -- pas de Ar ici
                local ok, msg = ApplyBobSkin("standard", false)
                log("skin bob standard -> " .. (ok and msg or ("ÉCHEC : " .. tostring(msg))))
            end)
            return true
        end
        -- 'skin bob keep' : mesh mime + matériaux d'origine (MID paramétrés par
        -- le jeu) au lieu des matériaux bruts du mesh, qui rendent noir.
        local keep = (sub == "keep" or sub == "mid")
        say(Ar, "Marcel Bob : échange du mesh vers SKEL_Bob_Mime"
                .. (keep and " (+ matériaux d'origine conservés)" or "") .. "…")
        ExecuteInGameThread(function()              -- pas de Ar ici
            local ok, msg = ApplyBobSkin("mime", true, keep)
            log("skin bob -> " .. (ok and msg or ("ÉCHEC : " .. tostring(msg))))
        end)
        return true
    end

    if key == "outline" then
        local sub = (p[2] and string.lower(p[2])) or ""

        if sub == "diag" then
            say(Ar, "diagnostic de l'outline — rien ne sera modifié.")
            say(Ar, "détail complet dans la FENÊTRE DE CONSOLE UE4SS.")
            ExecuteInGameThread(function()          -- pas de Ar ici
                local n = DiagOutline()
                log("outline diag -> " .. tostring(n) .. " composant(s) d'overlay")
            end)
            return true
        end

        if sub == "on" then
            say(Ar, "restauration de l'outline…")
            outlineLocked = false
            ExecuteInGameThread(function()          -- pas de Ar ici
                local ok, msg = RestoreOutline()
                log("outline on -> " .. tostring(msg))
            end)
            return true
        end

        if sub == "lock" then
            outlineLocked = not outlineLocked
            say(Ar, outlineLocked and "verrou outline ACTIF : suppression relancée toutes les 1,5 s."
                                  or  "verrou outline levé.")
            if outlineLocked then
                ExecuteInGameThread(function()      -- pas de Ar ici
                    log("outline lock -> " .. tostring(KillOutline(false)) .. " composant(s)")
                end)
            end
            return true
        end

        if sub == "" or sub == "off" or sub == "hard" then
            local hard = (sub == "hard")
            say(Ar, hard and "suppression NUCLÉAIRE de l'outline (irréversible jusqu'au rechargement du niveau)…"
                          or  "suppression de l'outline (cascade E1→E5)…")
            say(Ar, "détail complet dans la FENÊTRE DE CONSOLE UE4SS.")
            ExecuteInGameThread(function()          -- pas de Ar ici
                local n = KillOutline(hard)
                log("outline " .. (hard and "hard" or "off") .. " -> "
                    .. tostring(n) .. " composant(s) d'overlay traité(s)")
            end)
            return true
        end

        say(Ar, "usage : skin outline off | on | diag | lock | hard")
        return true
    end

    if key == "one" then
        local n = tonumber(p[2])
        if not n or n < 0 or n > 4 then
            say(Ar, "usage : skin one <0-4>   (0 = défaut, 1 = Hellgur, 2-4 = cachés)")
            return true
        end
        n = math.floor(n)
        say(Ar, "application du Skin" .. n .. "…")
        ExecuteInGameThread(function()          -- pas de Ar ici
            local ok, msg = ApplySkin(n)
            log("skin one " .. n .. " -> " .. (ok and msg or ("ÉCHEC : " .. tostring(msg))))
        end)
        return true
    end

    say(Ar, "ONE : skin one <0-4> | skin slots")
    say(Ar, "BOB : skin bob (mesh mime) | skin bob keep (mime + matériaux d'origine)")
    say(Ar, "      skin bob standard | skin bob off | skin bob slots")
    say(Ar, "OUTLINE : skin outline off (supprime la silhouette noire) | skin outline on")
    say(Ar, "          skin outline diag (n'écrit rien) | skin outline lock | skin outline hard")
    say(Ar, "AUTRES : skin reset | skin lock | skin menu")
    say(Ar, "Skin0 = défaut, Skin1 = Hellgur One, Skin2/3/4 = jamais exposés dans le menu")
    say(Ar, "Bob : 'Marcel Bob' = MI_BobSkin_Mustache (+ mesh SKEL_Bob_Mime avec 'mime')")
    say(Ar, "skin courant : " .. (current and ("Skin" .. current) or "origine")
            .. " | verrou : " .. tostring(locked))
    return true
end)

log("Chargé (v2). 'skin slots' pour découvrir, 'skin one 2' pour un skin caché.")

-- ============================================================================
--  Application au démarrage (voir le bloc BOOT_* en tête).
--  On attend BOOT_DELAY_MS que le pawn du joueur soit prêt, puis on applique
--  ce que le launcher a demandé. En mode silencieux pour ne pas polluer la
--  console. Chaque étape est protégée : une erreur n'empêche pas les suivantes.
-- ============================================================================
if BOOT_MESH ~= "none" or BOOT_SKIN >= 0 or BOOT_OUTLINE ~= "keep"
   or BOOT_HIDE_STICK or BOOT_HIDE_HAIR then
    -- Pas d'ExecuteWithDelay ici (le mod n'en dépend pas) : on arme une LoopAsync
    -- qui s'exécute une seule fois après BOOT_DELAY_MS, le temps que le pawn charge.
    local booted = false
    LoopAsync(BOOT_DELAY_MS, function()
        if booted then return true end   -- true = arrête la boucle
        booted = true
        ExecuteInGameThread(function()
            quietly(function()
                if BOOT_SKIN >= 0 then ApplySkin(BOOT_SKIN) end
                if BOOT_MESH ~= "none" then
                    local entry = FindEntry(MESHES, BOOT_MESH)
                    if entry then SwapOneMesh(entry) end
                end
                -- Outline : KillOutline(false) retire la silhouette, RestoreOutline la remet.
                if BOOT_OUTLINE == "off" then KillOutline(false)
                elseif BOOT_OUTLINE == "on" then RestoreOutline() end
                if BOOT_HIDE_STICK then HideActorsByClass({ "BP_Stick_C" }, true) end
                if BOOT_HIDE_HAIR  then HideActorsByClass({ "BP_Bigoudi_C" }, true) end
            end)
            loud("application au démarrage terminée (pilotée par le launcher)")
        end)
        return true
    end)
end
