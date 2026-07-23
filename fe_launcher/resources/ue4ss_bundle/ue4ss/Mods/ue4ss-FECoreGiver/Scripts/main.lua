-- ============================================================================
--  FADING ECHO — CORE GIVER
--
--  Extrait autonome du bloc "CORE GIVER" du FE Unlocker : rien que le don de
--  core, sans les ascenseurs / zones / murs alpha / portes.
--
--  Console in-game (F10) :
--    core <élément>          waste | fire | water | glitch | power
--    core <élément> nograb   le pose devant toi sans l'attraper
--    core list               liste les éléments disponibles
--
--  Tout est en pcall : si une brique échoue, le jeu continue.
-- ============================================================================

local UEHelpers = require("UEHelpers")

local function log(m) print("[CoreGiver] " .. tostring(m) .. "\n") end

-- Écrit à la fois dans la console in-game (Ar) et dans la console UE4SS.
local function cout(Ar, msg)
    pcall(function() if Ar then Ar:Log(msg) end end)
    log(msg)
end

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
--  CORE GIVER
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

-- Ordre d'affichage stable pour "core list" (CORE_ELEMENTS est une table de hash).
local CORE_ORDER = { "waste", "fire", "water", "glitch", "power" }

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

    if key == "list" or key == "help" then
        cout(Ar, "──── cores disponibles ────")
        for _, k in ipairs(CORE_ORDER) do
            cout(Ar, string.format("  %-7s %s", k, CORE_ELEMENTS[k].label))
        end
        cout(Ar, "→ core <élément> [nograb]")
        return true
    end

    local e = CORE_ELEMENTS[key]
    if not e then
        cout(Ar, "[core] usage : core waste|fire|water|glitch|power [nograb]  |  core list")
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

log("Chargé. Console in-game (F10) : core waste|fire|water|glitch|power [nograb]")
