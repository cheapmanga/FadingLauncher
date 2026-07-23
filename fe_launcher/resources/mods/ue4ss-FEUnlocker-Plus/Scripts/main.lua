-- ============================================================================
--  FADING ECHO — FE UNLOCKER  (périmètre d'origine)
--
--   F1  : Désactive les murs rouges (Alpha Blockers)          [action]
--   F2  : ACTIVE les escaliers rotatifs (les déploie)          [action]
--   F3  : Ascenseur le plus proche — le fait réellement bouger  [action]
--   F4  : Aide (liste des touches)                             [action]
--
--  Console in-game (F10) :
--   unlock list        liste les ascenseurs chargés (numérotés)
--   unlock <n°>        active l'ascenseur n° de la liste (ex. unlock 4)
--   unlock <n°> tp     l'active et t'y téléporte
--   unlock zones       débloque toutes les zones (fait aussi tout seul au load)
--   unlock door        ouvre la porte la plus proche
--   core <élément>     donne un core : waste | fire | water | glitch
--   (<n°> ou le slug/nom complet fonctionnent tous les deux)
--
--  En fond : déblocage automatique des 7 zones (DemoAllowedLevels) dès le
--  chargement, et ré-désactivation des murs alpha qui (re)spawnent.
--
--  Tout est en pcall : si une brique échoue, le reste continue.
-- ============================================================================

local UEHelpers = require("UEHelpers")

local function log(m) print("[Unlocker] " .. tostring(m) .. "\n") end

-- ---------------------------------------------------------------------------
--  Helpers joueur
-- ---------------------------------------------------------------------------
-- vrai acteur = pas un Class Default Object (le CDO est à l'origine 0,0,0).
local function isRealActor(a)
    if not (a and a:IsValid()) then return false end
    local fn = ""; pcall(function() fn = a:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function GetPawn()
    -- 1) pawn possédé par le PlayerController (le plus fiable)
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do
            if c and c:IsValid() then
                local pk = c.Pawn
                if isRealActor(pk) then return pk end
            end
        end
    end
    -- 2) helper UE4SS
    local ok, p = pcall(UEHelpers.GetPlayerPawn)
    if ok and isRealActor(p) then return p end
    -- 3) dernier recours : une instance NON-CDO du perso
    local list = FindAllOf("BP_CoreYgroCharacter_C")
    if list then
        for _, a in pairs(list) do
            if isRealActor(a) then return a end
        end
    end
    return nil
end

-- ============================================================================
--  UNLOCK ALL ZONES
--
--  DemoAllowedLevels (sur BP_LevelLoader_C) = liste de data-assets DA_Levels_C.
--  Par défaut la démo n'autorise que 4 zones. On ajoute les 7 zones réelles, en
--  deux passes :
--    1) RÉCOLTE (sûre) : les DA_Levels_C déjà chargés (FindAllOf), liste blanche.
--    2) COMPLÉMENT : s'il en manque encore, on résout les zones absentes via
--       GetLevelZoneAsset(E_LevelZone). Cette 2e passe ne tourne QUE tant que les
--       7 n'y sont pas -> elle s'arrête d'elle-même (pas d'appels en boucle).
--
--  E_LevelZone : Bastion=0, BigTree=1, Volcano=2, Quarry=3, Wonder=4,
--                Tutorial=5, None=7 (ignoré), MainMenu=8.
-- ============================================================================
local WANT_ZONES = {   -- les 7 data-assets réels (on ignore Sandbox / Proto / OLD)
    Levels_Zone_Bastion  = true, Levels_Zone_BigTree  = true,
    Levels_Zone_Volcano  = true, Levels_Zone_Quarry   = true,
    Levels_Zone_Wonder   = true, Levels_Zone_Tutorial = true,
    Levels_Zone_MainMenu = true,
}
local ZONE_ENUMS = { 0, 1, 2, 3, 4, 5, 8 }
local ZONES_TOTAL = 7
local zonesDone = false

local function UnlockAllZonesNow()
    local loader = FindFirstOf("BP_LevelLoader_C")
    if not (loader and loader:IsValid()) then return nil end
    local arr = loader.DemoAllowedLevels
    if not arr then return nil end

    local present, count = {}, 0
    for i = 1, #arr do
        local o = arr[i]
        if o and o:IsValid() then present[o:GetFullName()] = true; count = count + 1 end
    end

    local added = 0
    local function tryAdd(asset)
        if asset and asset:IsValid() then
            local fn = asset:GetFullName()
            if not present[fn] and not string.find(fn, "Default__", 1, true) then
                table.insert(arr, asset); present[fn] = true; added = added + 1
            end
        end
    end

    -- Passe 1 : récolte des DA_Levels_C déjà chargés (liste blanche)
    local ok, list = pcall(function() return FindAllOf("DA_Levels_C") end)
    if ok and list then
        for _, da in pairs(list) do
            if da and da:IsValid() then
                local nok, nm = pcall(function() return da:GetName() end)
                if nok and WANT_ZONES[nm] then tryAdd(da) end
            end
        end
    end

    -- Passe 2 : complément seulement s'il en manque (résout les zones non chargées)
    if count + added < ZONES_TOTAL then
        for _, z in ipairs(ZONE_ENUMS) do
            local asset
            pcall(function() asset = loader:GetLevelZoneAsset(z) end)
            tryAdd(asset)
        end
    end

    if added > 0 then log(string.format("Zones : +%d (%d/%d dans DemoAllowedLevels).", added, count + added, ZONES_TOTAL)) end
    if count + added >= ZONES_TOTAL then zonesDone = true end
    return added
end

-- Filet : quand une zone se charge, LoadZone l'ajoute (lecture + insertion, sûr).
RegisterHook("/Game/Game/Placeable/LevelLoader/BP_LevelLoader.BP_LevelLoader_C:LoadZone",
function(Context, WorldType, LevelsAsset)
    if not LevelsAsset or not LevelsAsset:get() then return end
    local zoneObj = LevelsAsset:get()
    local ok, loader = pcall(function() return Context:get() end)
    if not ok or not loader then return end
    local arr = loader.DemoAllowedLevels
    if not arr then return end
    for i = 1, #arr do if arr[i] == zoneObj then return end end
    table.insert(arr, zoneObj)
end)

-- Démarrage : essais RAPIDES (300 ms) pour réduire la fenêtre avant le 1er contrôle
-- de zone, puis boucle lente de secours. Les deux cessent tout travail une fois fini.
UnlockAllZonesNow()
local fastTries = 0
LoopAsync(300, function()
    fastTries = fastTries + 1
    if not zonesDone then pcall(UnlockAllZonesNow) end
    return zonesDone or fastTries >= 20      -- s'arrête quand fini, ou après ~6 s
end)
LoopAsync(3000, function()
    if not zonesDone then pcall(UnlockAllZonesNow) end
    return false
end)
log("Unlock zones actif (récolte + complément, essais rapides au démarrage).")

-- ============================================================================
--  Utilitaires bloqueurs
-- ============================================================================
local function DisableBlockerSafely(blocker)
    if not blocker then return end
    pcall(function()
        if blocker.BoxCol then blocker.BoxCol:SetCollisionEnabled(0) end
        if blocker.BoxTrigger then blocker.BoxTrigger:SetCollisionEnabled(0) end
        if blocker.Cube then blocker.Cube:SetVisibility(false, true) end
        blocker:SetActorEnableCollision(false)
        blocker:SetActorHiddenInGame(true)
    end)
end

-- Boucle de fond : re-désactive les bloqueurs alpha qui (re)spawnent
LoopAsync(5000, function()
    local ok, blockers = pcall(function() return FindAllOf("BP_PlayerBlockerForAlpha_C") end)
    if ok and blockers then
        for _, b in pairs(blockers) do if b then DisableBlockerSafely(b) end end
    end
    return false
end)

-- ============================================================================
--  TRIGGERS DE TÉLÉPORT à neutraliser (réintégré depuis FE Unlocker v1)
--  Le Volcano piège le joueur via un TriggerVolume qui le téléporte. On le
--  repère par nom complet (map + nom d'instance) et on coupe collision +
--  overlap + visibilité. Scan de fond car il (re)spawne au chargement de zone.
-- ============================================================================
local TELEPORT_TRIGGERS = {
    { map = "YGRO_Volcano_GlobalGameplay", name = "TriggerVolume_1" },
}

local function DisableTeleportTriggers()
    local ok, actors = pcall(function() return FindAllOf("TriggerVolume") end)
    if not (ok and actors) then return end
    for _, actor in pairs(actors) do
        if actor and actor:IsValid() then
            local vok, fn = pcall(function() return actor:GetFullName() end)
            if vok and fn then
                for _, t in ipairs(TELEPORT_TRIGGERS) do
                    if string.find(fn, t.map, 1, true) and string.find(fn, t.name, 1, true) then
                        pcall(function()
                            actor:SetActorEnableCollision(false)
                            actor:SetGenerateOverlapEvents(false)
                            actor:SetActorHiddenInGame(true)
                        end)
                    end
                end
            end
        end
    end
end

LoopAsync(5000, function()
    pcall(DisableTeleportTriggers)
    return false
end)
log("Triggers de téléport (Volcano) neutralisés en fond.")

-- ============================================================================
--  F1 : murs rouges (Alpha Blockers)
-- ============================================================================
RegisterKeyBind(Key.F1, function()
    local ok, blockers = pcall(function() return FindAllOf("BP_PlayerBlockerForAlpha_C") end)
    local n = 0
    if ok and blockers then
        for _, b in pairs(blockers) do if b then DisableBlockerSafely(b); n = n + 1 end end
    end
    log("F1 : " .. n .. " mur(s) alpha désactivé(s).")
end)

-- F2 (escaliers rotatifs) est défini plus bas : il réutilise le moteur de
-- mouvement des ascenseurs, car BP_RotatorStairs_C hérite de BP_MovingObject_C.

-- ############################################################################
--  MOTEUR ASCENSEURS (support de F3)
--
--  API réelle, relevée sur l'export du jeu (BP_Elevator / BP_MovingObject) :
--
--   BP_MovingObject_C  (classe parente)
--     MoverState : E_MoverState        <- LA variable d'état
--     UpdateMoverState(MoverState)     <- écrit l'état + broadcast OnMoverStateUpdated
--     MoverTimeline : TimelineComponent<- LE mouvement
--     PlayMover() / ReverseMover()     <- joue le timeline
--     MoverRoot : SceneComponent       <- le composant réellement déplacé
--
--   BP_Elevator_C
--     ForceElevatorToMove(Direction)  bUnlocked  ElevatorActivated
--     /!\ ForceElevatorToMove appelle ForcePlayerOnElevator (TeleportTo) : à ÉVITER.
--
--  >>> POURQUOI L'ANCIEN F3 NE BOUGEAIT PAS <<<
--  Il appelait UpdateMoverState(2). Or 2 = E_MoveToEnd : ça écrit l'état
--  "je vais vers le haut" et ça diffuse le delegate -> le jeu compte l'ascenseur
--  comme activé, et l'activateur repasse au bleu (ElevatorUnlockedColor 00CCFF).
--  Mais l'état et le timeline sont DEUX mécanismes distincts : personne n'a jamais
--  lancé MoverTimeline. D'où : état OK, visuel OK, zéro mouvement.
--  (Les autres champs forcés — bIsActive, bIsMoving, bTriggered... — n'existent
--   même pas sur la classe ; ces pcall échouaient silencieusement.)
--
--  CORRECTIF : on garde l'appel d'état (UpdateMoverState) à l'identique, et on
--  lance le mouvement via PlayMover / ReverseMover (le timeline). On n'utilise
--  PAS ForceElevatorToMove, qui téléporterait le joueur sur la plateforme.
-- ############################################################################

local ETimelineDirection = { Forward = 0, Backward = 1 }
local E_MoverState = {
    WaitingStart = 0,   -- E_MoverWaitingStart
    WaitingEnd   = 1,   -- E_MoverWaitingEnd
    MoveToEnd    = 2,   -- E_MoveToEnd      <- celui qu'utilisait déjà F3
    MoveToStart  = 3,   -- E_MoveToStart
    CustomMove   = 4,   -- E_CustomMove
    Interupted   = 5,   -- E_Interupted
}

-- Accès défensif : indexer un membre inconnu sur un UObject peut lever.
local function HasMember(obj, name)
    local ok, v = pcall(function() return obj[name] end)
    return ok and v ~= nil
end

local function CompLocation(obj, compName)
    local loc
    pcall(function()
        if HasMember(obj, compName) and obj[compName]:IsValid() then
            loc = obj[compName]:K2_GetComponentLocation()
        end
    end)
    return loc
end

-- Le timeline déplace MoverRoot (ascenseur : translation) ou fait pivoter
-- SM_TopStairRotator (escalier rotatif : rotation autour de MoverRoot). On mesure
-- donc là où le mouvement est réellement visible. `preferred` force un composant
-- en priorité : l'escalier tourne SUR PLACE, donc MoverRoot ne se translate pas —
-- il faut échantillonner SM_TopStairRotator, décalé du pivot.
local function ProbeLocation(obj, preferred)
    local loc
    if preferred then loc = CompLocation(obj, preferred) end
    if not loc then loc = CompLocation(obj, "MoverRoot") end
    if not loc then loc = CompLocation(obj, "SM_GPShortcutPlatform") end
    if not loc then loc = CompLocation(obj, "SM_TopStairRotator") end
    if not loc then pcall(function() loc = obj:K2_GetActorLocation() end) end
    return loc
end

local function Dist3(a, b)
    if not (a and b) then return nil end
    local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return math.sqrt(dx*dx + dy*dy + dz*dz)
end

local function CompRotation(obj, compName)
    local rot
    pcall(function()
        if HasMember(obj, compName) and obj[compName]:IsValid() then
            rot = obj[compName]:K2_GetComponentRotation()
        end
    end)
    return rot
end

-- Signature de mouvement = position ET rotation du composant mobile.
-- Indispensable pour l'escalier rotatif : il pivote SUR PLACE, donc seule sa
-- rotation change (la position, non). Une détection par position seule croirait
-- qu'il n'a pas bougé et le relancerait en sens inverse -> il "reviendrait" à
-- l'origine. On mesure donc aussi la rotation.
local function ProbeMotion(obj, preferred)
    local comp = preferred or "MoverRoot"
    local loc = CompLocation(obj, comp) or CompLocation(obj, "MoverRoot")
             or CompLocation(obj, "SM_TopStairRotator") or CompLocation(obj, "SM_GPShortcutPlatform")
    local rot = CompRotation(obj, comp) or CompRotation(obj, "MoverRoot")
             or CompRotation(obj, "SM_TopStairRotator")
    if not loc then pcall(function() loc = obj:K2_GetActorLocation() end) end
    return { loc = loc, rot = rot }
end

local function RotDelta(a, b)
    if not (a and b) then return 0 end
    local function d(x, y)
        local dd = math.abs((x or 0) - (y or 0)) % 360
        if dd > 180 then dd = 360 - dd end
        return dd
    end
    return d(a.Pitch, b.Pitch) + d(a.Yaw, b.Yaw) + d(a.Roll, b.Roll)
end

-- A-t-il bougé ? (position > 2 cm OU rotation > 1°) + un libellé lisible.
local function DescribeMotion(before, after)
    local locD = Dist3(before.loc, after.loc) or 0
    local rotD = RotDelta(before.rot, after.rot)
    local moved = (locD > 2.0) or (rotD > 1.0)
    local how
    if locD > 2.0 and rotD > 1.0 then how = string.format("%.0f cm + %.0f°", locD, rotD)
    elseif rotD > 1.0            then how = string.format("%.0f° de rotation", rotD)
    else                              how = string.format("%.0f cm", locD) end
    return moved, how
end

-- Lit l'état courant (lecture seule).
local function ReadMoverState(elev)
    local s
    pcall(function() s = elev.MoverState end)
    s = tonumber(s)
    return s
end

-- Choisit le SENS du trajet à partir de l'état réel de l'ascenseur.
--
--  Piège majeur relevé sur les .umap : beaucoup d'instances ont bStartFromEnd = true.
--  InitializeMoverTransform les place alors d'emblée à la position FIN. Jouer le timeline
--  "en avant" (vers FIN) sur une plateforme déjà à FIN ne produit AUCUN mouvement.
--  Il faut ReverseMover / Backward pour la ramener vers DÉBUT.
--  D'où : on lit MoverState, et on part dans le sens qui a du sens.
local function PickDirection(elev, dbEntry)
    local st = ReadMoverState(elev)
    if st == E_MoverState.WaitingEnd then
        return ETimelineDirection.Backward, E_MoverState.MoveToStart, "ReverseMover", "vers DÉBUT"
    elseif st == E_MoverState.WaitingStart then
        return ETimelineDirection.Forward,  E_MoverState.MoveToEnd,   "PlayMover",    "vers FIN"
    end
    -- état illisible : on se rabat sur bStartFromEnd relevé dans les données du jeu
    if dbEntry and dbEntry.startEnd then
        return ETimelineDirection.Backward, E_MoverState.MoveToStart, "ReverseMover", "vers DÉBUT (d'après bStartFromEnd)"
    end
    return ETimelineDirection.Forward, E_MoverState.MoveToEnd, "PlayMover", "vers FIN (par défaut)"
end

-- Lance le trajet dans un sens donné. Renvoie le nom de l'appel utilisé.
local function Drive(elev, dir, targetState, fallbackFn)
    -- ÉTAT : on passe par l'API du jeu (UpdateMoverState), avec la valeur qui
    -- correspond au trajet demandé. Aucune variable n'est écrite à la main.
    pcall(function() elev:UpdateMoverState(targetState) end)

    -- MOUVEMENT : on joue le timeline directement via PlayMover / ReverseMover
    -- (hérités de BP_MovingObject). fallbackFn = "PlayMover" (vers FIN) ou
    -- "ReverseMover" (vers DÉBUT), choisi par PickDirection pour coller au sens.
    --
    -- >>> On N'utilise PAS ForceElevatorToMove : sur BP_Elevator il appelle
    --     ForcePlayerOnElevator (GetPlayerPawn + AttachToComponent + TeleportTo),
    --     ce qui TÉLÉPORTE le joueur sur la plateforme — même pour un ascenseur
    --     distant activé à la console. On veut juste bouger la plateforme. <<<
    if HasMember(elev, fallbackFn) then
        if pcall(function() elev[fallbackFn](elev) end) then return fallbackFn .. "()" end
    end
    -- filet : l'autre sens de lecture du timeline, si le nom attendu manquait
    local other = (fallbackFn == "PlayMover") and "ReverseMover" or "PlayMover"
    if HasMember(elev, other) then
        if pcall(function() elev[other](elev) end) then return other .. "()" end
    end
    return nil
end

-- Déclenche le mouvement, puis VÉRIFIE qu'il a bien eu lieu.
-- Si rien n'a bougé, retente une fois dans l'autre sens (l'orientation du timeline
-- dépend de bStartFromEnd, qu'on ne peut pas toujours lire de façon fiable).
local function StartElevatorMotion(elev, opts)
    opts = opts or {}
    local db = opts.db
    local pc = opts.probeComp        -- composant à échantillonner (nil = MoverRoot)
    local before = ProbeMotion(elev, pc)

    local unlocked = true
    pcall(function() unlocked = elev.bUnlocked end)
    if unlocked == false then
        log("  note : bUnlocked = false (verrouillé côté jeu). Il peut refuser de partir.")
    end

    local dir, target, fb, human = PickDirection(elev, db)
    local used = Drive(elev, dir, target, fb)
    if not used then
        log("  /!\\ aucune fonction de mouvement trouvée sur cet acteur.")
        return nil
    end
    log("  trajet " .. human .. " — appel : " .. used)

    ExecuteWithDelay(700, function()
        ExecuteInGameThread(function()
            if not (elev and elev:IsValid()) then return end
            local moved, how = DescribeMotion(before, ProbeMotion(elev, pc))
            if moved then
                log("  -> mouvement confirmé : " .. how .. ".")
                return
            end
            -- Rien détecté (ni translation ni rotation) : sans doute déjà en butée
            -- dans ce sens. On retente UNE fois dans l'autre sens.
            log("  -> immobile : nouvel essai en sens inverse.")
            local rdir    = (dir == ETimelineDirection.Forward) and ETimelineDirection.Backward or ETimelineDirection.Forward
            local rtarget = (target == E_MoverState.MoveToEnd) and E_MoverState.MoveToStart or E_MoverState.MoveToEnd
            local rfb     = (fb == "PlayMover") and "ReverseMover" or "PlayMover"
            local before2 = ProbeMotion(elev, pc)
            local used2   = Drive(elev, rdir, rtarget, rfb)
            if not used2 then return end
            log("  appel inverse : " .. used2)
            ExecuteWithDelay(700, function()
                ExecuteInGameThread(function()
                    if not (elev and elev:IsValid()) then return end
                    local m2, how2 = DescribeMotion(before2, ProbeMotion(elev, pc))
                    if m2 then log("  -> mouvement confirmé au 2e essai : " .. how2 .. ".")
                    else       log("  -> toujours immobile. Vérifie bUnlocked / obstacle (bStopOnObstacle).") end
                end)
            end)
        end)
    end)
    return used
end

-- Recense les ascenseurs présents (classes réelles, CDO exclus).
local function CollectElevators()
    local found, seen = {}, {}
    for _, cls in ipairs({ "BP_Elevator_C", "BP_Elevator_BastionCenter_C" }) do
        local ok, list = pcall(function() return FindAllOf(cls) end)
        if ok and list then
            for _, a in pairs(list) do
                if a and a:IsValid() then
                    local nok, fn = pcall(function() return a:GetFullName() end)
                    -- exclut les Class Default Objects, qui ne sont pas dans le monde
                    if nok and fn and not string.find(fn, "Default__", 1, true) and not seen[fn] then
                        seen[fn] = true
                        table.insert(found, a)
                    end
                end
            end
        end
    end
    return found
end

-- ---------------------------------------------------------------------------
--  Nomenclature : un nom lisible dérivé de données réelles de l'acteur
--   full name = "BP_Elevator_C /Game/.../YGRO_Volcano_Sh0_EndArena.<...>:PersistentLevel.BP_Elevator_C_12"
--   -> zone = Volcano, sous-niveau = Sh0_EndArena, course = EndTransform.Z
-- ---------------------------------------------------------------------------
-- AUTO-GÉNÉRÉ depuis les .umap du jeu (TEST LLM.zip / UASSET extract from FE).
-- Clé = "<niveau>|<nom d'objet>" : exactement ce que donne GetFullName() à l'exécution.
-- course = longueur du trajet (m) ; alt = altitude de l'acteur (m) ;
-- startEnd = bStartFromEnd (la plateforme démarre en position FIN) ; unlocked = bUnlocked.
local ELEVATOR_DB = {
  ["YGRO_Bastion_Sh0_Gameplay|BP_Elevator_C_0"] = { slug="bastion-portal-fallback", label="Bastion — ascenseur du premier portail (secours)", course=11.8, alt=-83, startEnd=true, unlocked=false },
  ["YGRO_Bastion_Sh0_Gameplay|BP_Elevator_C_2"] = { slug="bastion-center", label="Bastion — ascenseur CENTRAL (hub, 12 slots de perk)", course=63.8, alt=-29, startEnd=true, unlocked=false },
  ["YGRO_Bastion_Sh0_Gameplay|StaticMeshActor_3"] = { slug="bastion-center-sol", label="Bastion — disque au sol de l'ascenseur central", course=15.3, alt=40, startEnd=false, unlocked=false },
  ["YGRO_Bastion_Sh0_Geo|BP_Elevator_C_0"] = { slug="bastion-sh0-e0", label="Bastion · éclat 0 — BP_Elevator", course=12.6, alt=-45, startEnd=false, unlocked=false },
  ["YGRO_Bastion_Sh0_Geo|BP_Elevator_C_1"] = { slug="bastion-tour-3", label="Bastion — tour 3", course=95.2, alt=50, startEnd=true, unlocked=false },
  ["YGRO_Bastion_Sh0_Geo|BP_Elevator_C_2"] = { slug="bastion-tour-2", label="Bastion — tour 2", course=82.9, alt=50, startEnd=true, unlocked=false },
  ["YGRO_Bastion_Sh0_Geo|BP_Elevator_C_3"] = { slug="bastion-tour-4", label="Bastion — tour 4", course=95.4, alt=50, startEnd=true, unlocked=false },
  ["YGRO_Bastion_Sh0_Geo|BP_Elevator_C_4"] = { slug="bastion-tour-1", label="Bastion — tour 1", course=82.9, alt=50, startEnd=true, unlocked=false },
  ["YGRO_Bastion_Sh0_Geo|BP_Elevator_C_6"] = { slug="bastion-sh0-e2", label="Bastion · éclat 0 — BP_Elevator2", course=20.1, alt=-78, startEnd=true, unlocked=true },
  ["YGRO_Quarry_Sh0_Gameplay|BP_Elevator_C_0"] = { slug="quarry-sh0-e12", label="Carrière · éclat 0 — BP_Elevator12", course=11.6, alt=80, startEnd=true, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_00|BP_Elevator_C_0"] = { slug="quarry-sh0-e3", label="Carrière · éclat 0 — BP_Elevator3", course=20.2, alt=-21, startEnd=true, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_00|BP_Elevator_C_2"] = { slug="quarry-sh0-e7", label="Carrière · éclat 0 — BP_Elevator7", course=23.8, alt=-40, startEnd=true, unlocked=true },
  ["YGRO_Quarry_Sh0_Geo_01|BP_Elevator_C_0"] = { slug="quarry-sh0-e0", label="Carrière · éclat 0 — BP_Elevator", course=76.7, alt=-26, startEnd=false, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_01|BP_Elevator_C_1"] = { slug="quarry-sh0-e2", label="Carrière · éclat 0 — BP_Elevator2", course=41.5, alt=15, startEnd=false, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_01|BP_Elevator_C_4"] = { slug="quarry-sh0-e8", label="Carrière · éclat 0 — BP_Elevator8", course=21.2, alt=39, startEnd=true, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_01|BP_Elevator_C_5"] = { slug="quarry-sh0-e9", label="Carrière · éclat 0 — BP_Elevator9", course=23.8, alt=44, startEnd=true, unlocked=true },
  ["YGRO_Quarry_Sh0_Geo_01|BP_Elevator_C_6"] = { slug="quarry-sh0-e4", label="Carrière · éclat 0 — BP_Elevator4", course=9.4, alt=50, startEnd=true, unlocked=true },
  ["YGRO_Quarry_Sh0_Geo_01|BP_Elevator_C_8"] = { slug="quarry-sh0-e10", label="Carrière · éclat 0 — BP_Elevator10", course=9.9, alt=56, startEnd=true, unlocked=true },
  ["YGRO_Quarry_Sh0_Geo_02|BP_Elevator_C_1"] = { slug="quarry-sh0-e5", label="Carrière · éclat 0 — BP_Elevator5", course=28.5, alt=126, startEnd=true, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_02|BP_Elevator_C_2"] = { slug="quarry-sh0-e6", label="Carrière · éclat 0 — BP_Elevator6", course=47.0, alt=84, startEnd=false, unlocked=false },
  ["YGRO_Quarry_Sh0_Geo_Transition|BP_Elevator_C_1"] = { slug="transition-carriere", label="Transition — vers la Carrière (chargement)", course=24.7, alt=-21, startEnd=false, unlocked=true },
  ["YGRO_Quarry_Sh2_Geo_00|BP_Elevator_C_1"] = { slug="quarry-sh2-e0", label="Carrière · éclat 2 — BP_Elevator", course=17.9, alt=-7, startEnd=false, unlocked=false },
  ["YGRO_Transition_Bastion-Wonder|BP_HorizontalMover_C_0"] = { slug="transition-bastion-wonder", label="Transition — Bastion <-> Wonder (mover horizontal)", course=23.0, alt=-20, startEnd=false, unlocked=true },
  ["YGRO_Tree_Sh0_Gameplay|BP_Elevator_C_0"] = { slug="tree-sh0-e0", label="Grand Arbre · éclat 0 — BP_Elevator", course=30.8, alt=-11, startEnd=false, unlocked=false },
  ["YGRO_Tree_Sh0_Gameplay|BP_Elevator_C_1"] = { slug="tree-sh0-e3", label="Grand Arbre · éclat 0 — BP_Elevator3", course=26.3, alt=51, startEnd=false, unlocked=false },
  ["YGRO_Tree_Sh0_Gameplay|BP_Elevator_C_3"] = { slug="tree-sh0-e2", label="Grand Arbre · éclat 0 — BP_Elevator2", course=30.8, alt=0, startEnd=false, unlocked=false },
  ["YGRO_Tree_Sh0_Geo_00|BP_Elevator_C_0"] = { slug="tree-sh0-e7", label="Grand Arbre · éclat 0 — BP_Elevator7", course=21.2, alt=11, startEnd=false, unlocked=true },
  ["YGRO_Tree_Sh0_Geo_00|BP_Elevator_C_1"] = { slug="tree-sh0-e5", label="Grand Arbre · éclat 0 — BP_Elevator5", course=19.4, alt=48, startEnd=false, unlocked=false },
  ["YGRO_Tree_Sh0_Geo_00|BP_Elevator_C_3"] = { slug="tree-sh0-e8", label="Grand Arbre · éclat 0 — BP_Elevator8", course=21.8, alt=41, startEnd=true, unlocked=false },
  ["YGRO_Tree_Sh0_Geo_00|BP_Elevator_C_4"] = { slug="tree-sh0-e9", label="Grand Arbre · éclat 0 — BP_Elevator9", course=66.7, alt=84, startEnd=false, unlocked=false },
  ["YGRO_Tree_Sh0_Geo_01|BP_Elevator_C_1"] = { slug="tree-sh0-e4", label="Grand Arbre · éclat 0 — BP_Elevator4", course=20.5, alt=24, startEnd=true, unlocked=false },
  ["YGRO_Tree_Sh1_Gameplay|BP_Elevator_C_0"] = { slug="tree-sh1-e0", label="Grand Arbre · éclat 1 — BP_Elevator", course=40.3, alt=47, startEnd=false, unlocked=false },
  ["YGRO_Tree_Sh2_Gameplay|BP_Elevator_C_1"] = { slug="tree-sh2-e0", label="Grand Arbre · éclat 2 — BP_Elevator", course=19.0, alt=7, startEnd=true, unlocked=false },
  ["YGRO_Tree_Transition_Tree_Bastion|BP_Elevator_C_1"] = { slug="transition-arbre-bastion", label="Transition — Grand Arbre <-> Bastion", course=26.2, alt=-10, startEnd=true, unlocked=true },
  ["YGRO_Tutorial_Sh0_Geo|BP_Elevator_C_2"] = { slug="tutorial-sh0-e0", label="Tutoriel · éclat 0 — BP_Elevator", course=18.6, alt=25, startEnd=true, unlocked=true },
  ["YGRO_Volcano_Sh0_Geo_00|BP_Elevator_C_2"] = { slug="volcano-sh0-e6", label="Volcano · éclat 0 — BP_Elevator6", course=68.2, alt=103, startEnd=true, unlocked=false },
  ["YGRO_Volcano_Sh0_Geo_00|BP_Elevator_C_4"] = { slug="volcano-sh0-e2", label="Volcano · éclat 0 — BP_Elevator2", course=30.8, alt=134, startEnd=true, unlocked=true },
  ["YGRO_Volcano_Sh0_Geo_01|BP_Elevator_C_1"] = { slug="volcano-sh0-e4", label="Volcano · éclat 0 — BP_Elevator4", course=30.5, alt=196, startEnd=false, unlocked=false },
  ["YGRO_Volcano_Sh0_Geo_01|BP_Elevator_C_3"] = { slug="volcano-sh0-e7", label="Volcano · éclat 0 — BP_Elevator7", course=121.9, alt=289, startEnd=false, unlocked=false },
  ["YGRO_Volcano_Sh0_Geo_02|BP_Elevator_C_2"] = { slug="volcano-sh0-e8", label="Volcano · éclat 0 — BP_Elevator8", course=37.6, alt=243, startEnd=true, unlocked=false },
  ["YGRO_Volcano_Sh0_Geo_03|BP_Elevator_C_0"] = { slug="volcano-sh0-e5", label="Volcano · éclat 0 — BP_Elevator5", course=42.3, alt=273, startEnd=false, unlocked=false },
  ["YGRO_Volcano_Sh0_Geo_03|BP_Elevator_C_2"] = { slug="volcano-sh0-e0", label="Volcano · éclat 0 — BP_Elevator", course=25.1, alt=293, startEnd=true, unlocked=false },
  ["YGRO_Volcano_Sh2_Geo_00|BP_Elevator_C_1"] = { slug="volcano-sh2-e0", label="Volcano · éclat 2 — BP_Elevator", course=20.9, alt=203, startEnd=true, unlocked=false },
  ["YGRO_Volcano_Sh2_Geo_00|BP_Elevator_C_2"] = { slug="volcano-sh2-e2", label="Volcano · éclat 2 — BP_Elevator2", course=21.4, alt=256, startEnd=true, unlocked=false },
  ["YGRO_Volcano_Sh2_Geo_00|BP_Elevator_C_3"] = { slug="volcano-sh2-e3", label="Volcano · éclat 2 — BP_Elevator3", course=17.5, alt=204, startEnd=false, unlocked=false },
  ["YGRO_Wonder_Sh0_Geo_00|BP_Elevator_C_3"] = { slug="wonder-sh0-e10", label="Wonder · éclat 0 — BP_Elevator10", course=82.9, alt=50, startEnd=false, unlocked=false },
  ["YGRO_Wonder_Sh0_Geo_00|BP_Elevator_C_4"] = { slug="wonder-sh0-e0", label="Wonder · éclat 0 — BP_Elevator", course=21.9, alt=128, startEnd=true, unlocked=false },
  ["YGRO_Wonder_Sh0_Geo_00|BP_Elevator_C_6"] = { slug="wonder-sh0-e5", label="Wonder · éclat 0 — BP_Elevator5", course=63.5, alt=204, startEnd=true, unlocked=true },
  ["YGRO_Wonder_Sh1_Geo_00|BP_Elevator_C_1"] = { slug="wonder-sh1-e0", label="Wonder · éclat 1 — BP_Elevator", course=15.4, alt=205, startEnd=false, unlocked=true },
  ["YGRO_Wonder_Sh2_Geo_00|BP_Elevator_C_1"] = { slug="wonder-sh2-e0", label="Wonder · éclat 2 — BP_Elevator", course=16.8, alt=42, startEnd=true, unlocked=false },
  ["YGRO_Wonder_Sh2_Geo_00|BP_Elevator_C_2"] = { slug="wonder-sh2-e2", label="Wonder · éclat 2 — BP_Elevator2", course=24.0, alt=211, startEnd=false, unlocked=true },
}

-- Zones, pour l'étiquette de repli quand un ascenseur n'est pas dans la base
-- (niveau ajouté par un patch, ou ascenseur spawné dynamiquement).
local ZONES = {
    { key = "Bastion",  label = "Bastion"      },
    { key = "Volcano",  label = "Volcano"      },
    { key = "Quarry",   label = "Carrière"     },
    { key = "Tree",     label = "Grand Arbre"  },
    { key = "Wonder",   label = "Wonder"       },
    { key = "Tutorial", label = "Tutoriel"     },
}

-- full name = "BP_Elevator_C /Game/.../YGRO_Bastion_Sh0_Gameplay.<...>:PersistentLevel.BP_Elevator_C_2"
--             -> classe, niveau, nom d'objet
local function ParseFullName(fn)
    local class, path = string.match(fn, "^(%S+)%s+(.*)$")
    path = path or ""
    local level = string.match(path, "([^/%.]+)%.[^/]*:PersistentLevel")
               or string.match(path, "([^/%.]+)%.[^/]*$") or "?"
    local inst  = string.match(path, "([^%.]+)$") or "?"
    return class or "?", level, inst
end

local function ZoneOf(level)
    for _, z in ipairs(ZONES) do
        if string.find(level, z.key, 1, true) then return z.label end
    end
    return "Zone inconnue"
end

local function Slugify(s)
    s = string.lower(s)
    s = string.gsub(s, "[^%w]+", "-")
    s = string.gsub(s, "^%-+", ""); s = string.gsub(s, "%-+$", "")
    return s
end

-- Identité d'un ascenseur : base du jeu si connu, sinon repli descriptif.
local function IdentifyElevator(class, level, inst)
    local e = ELEVATOR_DB[level .. "|" .. inst]
    if e then return e.slug, e.label, e.course, e.alt, e, true end
    local slug = Slugify(level .. "-" .. inst)
    return slug, ZoneOf(level) .. " · " .. level .. " / " .. inst, nil, nil, nil, false
end

local function FmtCourse(e)
    return e.course and string.format("course %.1f m", e.course) or "course ?"
end
local function FmtDist(e)
    return e.dist and string.format("à %.0f m", e.dist / 100) or ""
end

-- Construit la liste triée + nommée. Retourne { {actor, slug, label, course, dist, ...}, ... }
local function BuildElevatorList()
    local pawn = GetPawn()
    local ppos = pawn and pawn:K2_GetActorLocation() or nil
    local out, usedSlugs = {}, {}

    for _, a in ipairs(CollectElevators()) do
        local fn = a:GetFullName()
        local class, level, inst = ParseFullName(fn)
        local slug, label, course, alt, db, known = IdentifyElevator(class, level, inst)

        -- course : celle de la base si connue, sinon lue sur l'acteur
        if not course then
            local dz
            pcall(function() dz = a.EndTransform.Translation.Z end)
            course = dz and math.abs(dz) / 100.0 or nil
        end

        local dist = ppos and Dist3(ppos, ProbeLocation(a)) or nil

        -- unicité (deux ascenseurs inconnus pourraient produire le même slug)
        local base, n = slug, 2
        while usedSlugs[slug] do slug = base .. "-" .. n; n = n + 1 end
        usedSlugs[slug] = true

        table.insert(out, {
            actor = a, slug = slug, label = label, course = course, alt = alt,
            dist = dist, level = level, class = class, inst = inst,
            db = db, known = known,
        })
    end

    table.sort(out, function(x, y)
        if x.dist and y.dist then return x.dist < y.dist end
        return x.slug < y.slug
    end)
    return out
end

-- ============================================================================
--  F3 : ascenseur le plus proche — le fait réellement bouger
-- ============================================================================
local function NearestElevator()
    local list = BuildElevatorList()
    for _, e in ipairs(list) do
        -- on garde l'exclusion d'origine du gros ascenseur central
        if e.class ~= "BP_Elevator_BastionCenter_C" then return e end
    end
    return list[1]
end

RegisterKeyBind(Key.F3, function()
    ExecuteInGameThread(function()
        local e = NearestElevator()
        if not e then log("F3 : aucun ascenseur trouvé."); return end
        log(string.format("F3 : %s [%s] — %s %s", e.label, e.slug, FmtCourse(e), FmtDist(e)))
        local used = StartElevatorMotion(e.actor, { db = e.db })
        if used then log("  appel de mouvement : " .. used) end
    end)
end)

-- ============================================================================
--  F2 : escaliers rotatifs — les ACTIVER (les déployer), au lieu de les cacher
--
--  BP_RotatorStairs_C hérite de BP_MovingObject_C : même moteur que l'ascenseur.
--  Le mesh SM_TopStairRotator est attaché à MoverRoot ; le MoverTimeline le fait
--  pivoter. On déclenche donc le mouvement exactement comme un ascenseur, mais on
--  échantillonne SM_TopStairRotator (MoverRoot tourne sur place : sa position ne
--  change pas, alors que le mesh décalé du pivot, si).
-- ============================================================================
local function CollectStairs()
    local found, seen = {}, {}
    local ok, list = pcall(function() return FindAllOf("BP_RotatorStairs_C") end)
    if ok and list then
        for _, a in pairs(list) do
            if a and a:IsValid() then
                local nok, fn = pcall(function() return a:GetFullName() end)
                if nok and fn and not string.find(fn, "Default__", 1, true) and not seen[fn] then
                    seen[fn] = true
                    table.insert(found, a)
                end
            end
        end
    end
    return found
end

RegisterKeyBind(Key.F2, function()
    ExecuteInGameThread(function()
        local stairs = CollectStairs()
        if #stairs == 0 then log("F2 : aucun escalier rotatif chargé."); return end
        log("F2 : activation de " .. #stairs .. " escalier(s) rotatif(s)...")
        for _, s in ipairs(stairs) do
            StartElevatorMotion(s, { probeComp = "SM_TopStairRotator" })
        end
    end)
end)

-- ============================================================================
--  CONSOLE IN-GAME — commande "unlock"
--   unlock list          -> liste les ascenseurs chargés (avec leur nom = slug)
--   unlock <nom>         -> active cet ascenseur précis
--   unlock <nom> tp      -> l'active ET t'y téléporte
--
--  Le handler console de UE4SS s'exécute sur le game thread : on appelle donc
--  les fonctions du jeu directement (Ar, l'OutputDevice, n'est valide que
--  pendant l'appel synchrone — pas question de le différer).
-- ============================================================================
-- Écrit à la fois dans la console in-game (Ar) et dans la console UE4SS.
local function cout(Ar, msg)
    pcall(function() if Ar then Ar:Log(msg) end end)
    log(msg)
end

-- Snapshot de la dernière liste affichée par "unlock list", pour pouvoir taper
-- juste "unlock <n°>". On fige l'ordre au moment du list : le numéro reste valable
-- même si le joueur bouge (l'ordre par distance changerait sinon).
local lastList = {}

local function ResolveByIndex(n)
    if #lastList == 0 then lastList = BuildElevatorList() end   -- au cas où : list implicite
    local e = lastList[n]
    if not e then return nil, "numéro hors liste — refais 'unlock list'." end
    if not (e.actor and e.actor:IsValid()) then
        return nil, "cet ascenseur n'est plus chargé — refais 'unlock list'."
    end
    return e, nil
end

-- Retrouve un ascenseur par son nom. Renvoie (elem, nil) si trouvé,
-- sinon (nil, candidats) pour un message d'ambiguïté.
local function FindElevatorByName(name)
    local list = BuildElevatorList()
    name = string.lower(name)
    for _, e in ipairs(list) do                       -- 1) slug exact
        if string.lower(e.slug) == name then return e, nil end
    end
    local matches = {}                                -- 2) sous-chaîne slug/label
    for _, e in ipairs(list) do
        if string.find(string.lower(e.slug), name, 1, true)
        or string.find(string.lower(e.label), name, 1, true) then
            table.insert(matches, e)
        end
    end
    if #matches == 1 then return matches[1], nil end
    return nil, matches
end

local function TeleportToElevator(e)
    local pawn = GetPawn()
    if not pawn then return false, "joueur introuvable" end
    local loc = ProbeLocation(e.actor, e.probeComp)
    if not loc then return false, "position de l'ascenseur introuvable" end
    -- +200 cm : on se pose au-dessus de la plateforme plutôt que dedans.
    local dest = { X = loc.X, Y = loc.Y, Z = loc.Z + 200.0 }
    local ok = pcall(function() pawn:K2_SetActorLocation(dest, false, {}, true) end)
    return ok, (not ok) and "K2_SetActorLocation a échoué" or nil
end

-- ============================================================================
--  PORTES — "unlock door" : ouvre la porte la plus proche
--
--  Toutes les portes dérivent de BP_MovingObject_C (via BP_SimpleMovingDoor_C) et
--  exposent : Unlock(LockParameter:Name, bInstant:bool), MoveForward(bInstant:bool)
--  = ouvrir, MoveReverse(bInstant:bool) = fermer, Lock(...). On déverrouille puis on
--  ouvre ; si rien ne bouge, on tente l'autre sens (porte peut-être déjà ouverte).
-- ============================================================================
local DOOR_CLASSES = {
    "BP_SimpleMovingDoor_C", "BP_GameplayDoor_C",
    "BP_GameplayDoorBastion_C", "BP_GameplayDoor_PERKS_C",
}

local function CollectDoors()
    local found, seen = {}, {}
    for _, cls in ipairs(DOOR_CLASSES) do
        local ok, list = pcall(function() return FindAllOf(cls) end)
        if ok and list then
            for _, a in pairs(list) do
                if a and a:IsValid() then
                    local nok, fn = pcall(function() return a:GetFullName() end)
                    if nok and fn and not string.find(fn, "Default__", 1, true) and not seen[fn] then
                        seen[fn] = true
                        table.insert(found, a)
                    end
                end
            end
        end
    end
    return found
end

local function NearestDoor()
    local pawn = GetPawn()
    local ppos = pawn and pawn:K2_GetActorLocation() or nil
    local best, bestd
    for _, d in ipairs(CollectDoors()) do
        local dl = ProbeLocation(d)
        local dist = (ppos and dl) and Dist3(ppos, dl) or nil
        if dist and (not bestd or dist < bestd) then best, bestd = d, dist end
    end
    return best, bestd
end

-- IMPORTANT — leçon du crash : on N'appelle QUE PlayMover / ReverseMover.
--  * Les fonctions de porte (Unlock/MoveForward/MoveReverse) sont des BlueprintEvents
--    qui, appelés à froid, déréférencent un composant nul -> CRASH natif (non rattrapable).
--  * UpdateMoverState est REDÉFINI par les portes (émissif/son/séquence) -> même risque,
--    on l'évite aussi.
--  PlayMover/ReverseMover sont la fonction de BASE BP_MovingObject (non redéfinie), qui
--  joue juste le MoverTimeline -> déplace le battant. C'est ce qui marche sans crash pour
--  les ascenseurs/escaliers.
-- Volontairement SYNCHRONE et minimal : on joue le timeline et c'est tout.
-- PAS de vérification différée : beaucoup de portes sont des portes de TRANSITION —
-- les ouvrir déclenche un changement de zone qui DÉTRUIT la porte ; relire sa position
-- 800 ms plus tard = lecture de mémoire libérée -> CRASH (confirmé en jeu). PlayMover
-- suffit à l'ouvrir, on n'a rien à re-vérifier.
local function OpenDoor(door, Ar)
    local ok = pcall(function() door:PlayMover() end)
    if ok then cout(Ar, "[unlock] porte : ouverture envoyée (PlayMover).")
    else       cout(Ar, "[unlock] PlayMover a échoué sur cette porte.") end
end

RegisterConsoleCommandGlobalHandler("unlock", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local sub = (p[1] and string.lower(p[1])) or "list"

    -- unlock list
    if sub == "list" then
        local list = BuildElevatorList()
        lastList = list                              -- fige l'ordre pour "unlock <n°>"
        if #list == 0 then cout(Ar, "[unlock] aucun ascenseur chargé actuellement."); return true end
        cout(Ar, "──── ascenseurs chargés (" .. #list .. ") ────")
        for i, e in ipairs(list) do
            cout(Ar, string.format("%2d. %-26s %-46s %s %s",
                i, e.slug, e.label, FmtCourse(e), FmtDist(e)))
        end
        cout(Ar, "→ unlock <n°>   (ex. unlock 4)   |   ajoute 'tp' pour t'y téléporter")
        return true
    end

    -- unlock zones : force le déblocage de toutes les zones maintenant
    if sub == "zones" then
        local added = UnlockAllZonesNow()
        if added == nil then
            cout(Ar, "[unlock] LevelLoader pas encore chargé — réessaie une fois en jeu.")
        elseif added == 0 then
            cout(Ar, "[unlock] zones déjà toutes débloquées.")
        else
            cout(Ar, "[unlock] " .. added .. " zone(s) débloquée(s).")
        end
        return true
    end

    -- unlock door : ouvre la porte la plus proche
    if sub == "door" then
        local door, dist = NearestDoor()
        if not door then cout(Ar, "[unlock] aucune porte chargée à proximité."); return true end
        local fn = "?"; pcall(function() fn = door:GetFullName() end)
        cout(Ar, string.format("[unlock] porte la plus proche (%.0f m) — ouverture...",
            (dist or 0) / 100))
        OpenDoor(door, Ar)
        return true
    end

    -- unlock <nom> [tp]  — 'tp' peut être n'importe où dans les paramètres
    local tp, nameParts = false, {}
    for _, tok in ipairs(p) do
        if string.lower(tok) == "tp" then tp = true
        else table.insert(nameParts, tok) end
    end
    local name = table.concat(nameParts, " ")
    if name == "" then
        cout(Ar, "[unlock] usage : unlock list  |  unlock <n°|nom> [tp]")
        return true
    end

    local e, matches
    if string.match(name, "^%d+$") then          -- "unlock 4" : par numéro de la liste
        local err
        e, err = ResolveByIndex(tonumber(name))
        if not e then cout(Ar, "[unlock] " .. err); return true end
    else                                          -- "unlock <nom>" : par slug/label
        e, matches = FindElevatorByName(name)
    end
    if not e then
        if matches and #matches > 1 then
            cout(Ar, "[unlock] '" .. name .. "' est ambigu :")
            for _, m in ipairs(matches) do cout(Ar, "   - " .. m.slug .. "  (" .. m.label .. ")") end
        else
            cout(Ar, "[unlock] aucun ascenseur nommé '" .. name .. "'. Fais : unlock list")
        end
        return true
    end

    cout(Ar, string.format("[unlock] %s [%s] — %s", e.label, e.slug, FmtCourse(e)))
    StartElevatorMotion(e.actor, { db = e.db })
    if tp then
        local ok, err = TeleportToElevator(e)
        cout(Ar, ok and "  → téléporté sur l'ascenseur." or ("  → téléport impossible : " .. tostring(err)))
    end
    return true
end)
log("Console : tape 'unlock list' dans la console in-game (F10).")

-- ============================================================================
--  CORE GIVER — commande "core waste|fire|water|glitch"
--
--  Fait apparaître un core élémentaire devant le joueur (BP_PortableItem_<X>Ball,
--  dérive de BP_PortableItem_C) puis le lui met dans les mains via StartGrab.
--  Le grab déclenche la charge élémentaire du jeu (UI + LB + pouvoir).
--  Spawn = BeginDeferredActorSpawnFromClass + FinishSpawningActor (6 entrées UE5).
--  Éléments réels : Water, Waste, Lava(=fire), Corruption(=glitch).
-- ============================================================================
local CORE_BASE = "/Game/Game/Placeable/InteractiveObjects/PortableItem/"
local CORE_ELEMENTS = {
    waste  = { path = CORE_BASE .. "BP_PortableItem_WasteBall.BP_PortableItem_WasteBall_C",           short = "BP_PortableItem_WasteBall_C",      label = "Waste" },
    fire   = { path = CORE_BASE .. "BP_PortableItem_LavaBall.BP_PortableItem_LavaBall_C",             short = "BP_PortableItem_LavaBall_C",       label = "Lava (feu)" },
    water  = { path = CORE_BASE .. "BP_PortableItem_WaterBall.BP_PortableItem_WaterBall_C",           short = "BP_PortableItem_WaterBall_C",      label = "Water" },
    glitch = { path = CORE_BASE .. "BP_PortableItem_CorruptionBall.BP_PortableItem_CorruptionBall_C", short = "BP_PortableItem_CorruptionBall_C", label = "Corruption (glitch)" },
    power  = { path = CORE_BASE .. "BP_PortableItem_Power.BP_PortableItem_Power_C",                   short = "BP_PortableItem_Power_C",          label = "PowerCore" },
}

-- UClass du ball : objet-classe si chargé, sinon la classe d'une instance présente.
local function ResolveCoreClass(e)
    local c = StaticFindObject(e.path)
    if c and c:IsValid() then return c end
    local inst = FindFirstOf(e.short)
    if inst and inst:IsValid() then
        local ok, k = pcall(function() return inst:GetClass() end)
        if ok and k and k:IsValid() then return k end
    end
    return nil
end

-- Spawne le ball devant le joueur. Renvoie (actor, nil) ou (nil, message).
local function SpawnCoreBall(e, pawn)
    local world = UEHelpers.GetWorld()
    if not (world and world:IsValid()) then return nil, "world introuvable." end
    local GS = StaticFindObject("/Script/Engine.Default__GameplayStatics")
    if not (GS and GS:IsValid()) then return nil, "GameplayStatics introuvable." end
    local KML = StaticFindObject("/Script/Engine.Default__KismetMathLibrary")
    if not (KML and KML:IsValid()) then return nil, "KismetMathLibrary introuvable." end
    local cls = ResolveCoreClass(e)
    if not (cls and cls:IsValid()) then
        return nil, "classe pas chargée (" .. e.short .. "). Approche-toi une fois d'un core " ..
                    e.label .. " pour la charger, puis réessaie."
    end

    local loc = pawn:K2_GetActorLocation()
    local fwd = pawn:GetActorForwardVector()
    local pos = { X = loc.X + fwd.X * 120.0, Y = loc.Y + fwd.Y * 120.0, Z = loc.Z + 40.0 }
    local xf
    local okT = pcall(function()
        xf = KML:MakeTransform(pos, { Pitch = 0.0, Yaw = 0.0, Roll = 0.0 }, { X = 1.0, Y = 1.0, Z = 1.0 })
    end)
    if not okT or not xf then return nil, "MakeTransform a échoué." end

    local actor
    local okS, errS = pcall(function()
        actor = GS:BeginDeferredActorSpawnFromClass(world, cls, xf, 1, nil, 0)  -- 1 = AlwaysSpawn
    end)
    if not okS then return nil, "spawn a levé : " .. tostring(errS) end
    if not (actor and actor:IsValid()) then return nil, "spawn a renvoyé un acteur nul." end

    for _, n in ipairs({ 3, 2 }) do   -- FinishSpawningActor : 3 args (UE5 récent) ou 2
        local okF = pcall(function()
            if n == 3 then GS:FinishSpawningActor(actor, xf, 0) else GS:FinishSpawningActor(actor, xf) end
        end)
        if okF then break end
    end
    return actor, nil
end

RegisterConsoleCommandGlobalHandler("core", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local key = (p[1] and string.lower(p[1])) or ""
    local e = CORE_ELEMENTS[key]
    if not e then
        cout(Ar, "[core] usage : core waste|fire|water|glitch|power [nograb]")
        return true
    end
    -- 'nograb' : le core apparaît par terre sans être attrapé (pour tester
    -- l'infinite core en forme de One : spawn un core et ne l'absorbe pas).
    local nograb = false
    for _, tok in ipairs(p) do
        local t = string.lower(tok)
        if t == "nograb" or t == "drop" or t == "nopickup" then nograb = true end
    end
    local pawn = GetPawn()
    if not pawn then cout(Ar, "[core] joueur introuvable."); return true end
    local actor, err = SpawnCoreBall(e, pawn)
    if not actor then cout(Ar, "[core] " .. tostring(err)); return true end
    if nograb then
        cout(Ar, "[core] " .. e.label .. " posé devant toi (non attrapé).")
    else
        pcall(function() pawn:StartGrab(actor) end)
        cout(Ar, "[core] " .. e.label .. " donné.")
    end
    return true
end)
log("Console : tape 'core water' (waste|fire|water|glitch) dans la console in-game.")

-- ============================================================================
--  F4 : AIDE
-- ============================================================================
RegisterKeyBind(Key.F4, function()
    log("======== FADING ECHO — FE UNLOCKER ========")
    log("F1  murs rouges (alpha)")
    log("F2  ACTIVE les escaliers rotatifs (les déploie)")
    log("F3  ascenseur le + proche : le fait bouger")
    log("F4  cette aide")
    log("--- console in-game (F10) ---")
    log("unlock list        liste les ascenseurs (numérotés)")
    log("unlock <n°>        active l'ascenseur n° (ex. unlock 4)")
    log("unlock <n°> tp     l'active et t'y téléporte")
    log("unlock zones       débloque toutes les zones (auto au chargement)")
    log("unlock door        ouvre la porte la plus proche de toi")
    log("core <type>        core : waste|fire|water|glitch|power  (+ nograb = posé)")
    log("  (<n°> ou le nom complet marchent tous les deux)")
    log("===========================================")
end)

log("Chargé. F4 = aide. (unlock zones + anti-blockers actifs)")
