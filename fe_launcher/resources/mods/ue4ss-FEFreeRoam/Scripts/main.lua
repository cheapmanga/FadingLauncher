-- ============================================================================
--  FADING ECHO — FREE ROAM  (mod séparé : explorer librement)
--
--  Fait en fond (automatique) :
--   - MURS ROUGES : désactive en continu les BP_PlayerBlockerForAlpha_C.
--   - REROUTE : tue le garde-fou démo. Le LevelLoader reroute vers le Bastion
--     (+ TP) si tu charges une zone absente de DemoAllowedLevels. On ajoute la
--     zone en cours de chargement à cette liste EN PRÉ-HOOK de LoadZone, donc
--     avant le test -> plus jamais "hors liste", pour N'IMPORTE quelle zone.
--
--  Commande console (F10) :
--   trigger            désactive le trigger/volume le plus proche de toi
--   trigger all        désactive tous les triggers/volumes chargés
--   trigger death      désactive tous les volumes de mort/void
--   walls              force la désactivation des murs rouges maintenant
-- ============================================================================

local UEHelpers = require("UEHelpers")

local function log(m) print("[FreeRoam] " .. tostring(m) .. "\n") end
local function cout(Ar, m)
    pcall(function() if Ar then Ar:Log(m) end end)
    log(m)
end

-- ---------------------------------------------------------------------------
--  Joueur
-- ---------------------------------------------------------------------------
local function isRealActor(a)
    if not (a and a:IsValid()) then return false end
    local fn = ""; pcall(function() fn = a:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function GetPawn()
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do
            if c and c:IsValid() then
                local pk = c.Pawn
                if isRealActor(pk) then return pk end
            end
        end
    end
    local ok, p = pcall(UEHelpers.GetPlayerPawn)
    if ok and isRealActor(p) then return p end
    return nil
end

local function Dist2(a, b)
    local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return dx*dx + dy*dy + dz*dz
end

-- ============================================================================
--  MURS ROUGES (Alpha Blockers) — désactivation continue
-- ============================================================================
local function DisableBlocker(b)
    if not (b and b:IsValid()) then return end
    pcall(function()
        if b.BoxCol then b.BoxCol:SetCollisionEnabled(0) end
        if b.BoxTrigger then b.BoxTrigger:SetCollisionEnabled(0) end
        if b.Cube then b.Cube:SetVisibility(false, true) end
        b:SetActorEnableCollision(false)
        b:SetActorHiddenInGame(true)
    end)
end

local function DisableAllWalls()
    local n = 0
    local ok, list = pcall(function() return FindAllOf("BP_PlayerBlockerForAlpha_C") end)
    if ok and list then
        for _, b in pairs(list) do
            if b and b:IsValid() then DisableBlocker(b); n = n + 1 end
        end
    end
    return n
end

LoopAsync(3000, function()
    pcall(DisableAllWalls)   -- re-désactive ceux qui (re)spawnent
    return false
end)

-- ============================================================================
--  REROUTE OFF — pré-hook LoadZone : la zone chargée est ajoutée à
--  DemoAllowedLevels AVANT le test "zone autorisée ?" -> pas de reroute Bastion.
-- ============================================================================
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
    log("reroute évité : zone ajoutée à DemoAllowedLevels.")
end)
log("Reroute off (pré-hook LoadZone actif).")

-- ============================================================================
--  TRIGGERS / VOLUMES — désactivation à la demande
-- ============================================================================
-- classes ciblables (le TriggerVolume générique + les volumes gameplay connus)
local TRIGGER_CLASSES = {
    "TriggerVolume",
    "BP_CustomDeathVolume_C", "BP_SaveRestrictionVolume_C", "BP_DifficultyZoneTrigger_C",
    "BP_CameraVolume_C", "BP_AudioCharacterOnTriggerBox_C", "BP_RadioTrigger_C",
    "BP_WaterTrigger_C", "BP_ZoneLoader_C",
}
-- sous-ensemble "mort / void"
local DEATH_CLASSES = { "BP_CustomDeathVolume_C" }

local function CollectTriggers(classes)
    local found, seen = {}, {}
    for _, cls in ipairs(classes) do
        local ok, list = pcall(function() return FindAllOf(cls) end)
        if ok and list then
            for _, a in pairs(list) do
                if a and a:IsValid() then
                    local nok, fn = pcall(function() return a:GetFullName() end)
                    if nok and fn and not string.find(fn, "Default__", 1, true) and not seen[fn] then
                        seen[fn] = true
                        table.insert(found, { actor = a, class = cls })
                    end
                end
            end
        end
    end
    return found
end

local function DisableTrigger(a)
    pcall(function() a:SetActorEnableCollision(false) end)   -- coupe collision + overlap
    pcall(function() a:SetActorHiddenInGame(true) end)
end

RegisterConsoleCommandGlobalHandler("trigger", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local sub = (p[1] and string.lower(p[1])) or "nearest"

    if sub == "all" then
        local list = CollectTriggers(TRIGGER_CLASSES)
        for _, t in ipairs(list) do DisableTrigger(t.actor) end
        cout(Ar, "[trigger] " .. #list .. " trigger(s)/volume(s) désactivé(s).")
        return true
    end

    if sub == "death" or sub == "void" then
        local list = CollectTriggers(DEATH_CLASSES)
        for _, t in ipairs(list) do DisableTrigger(t.actor) end
        cout(Ar, "[trigger] " .. #list .. " volume(s) de mort désactivé(s).")
        return true
    end

    -- défaut : le plus proche
    local pawn = GetPawn()
    local ppos = pawn and pawn:K2_GetActorLocation() or nil
    if not ppos then cout(Ar, "[trigger] joueur introuvable."); return true end
    local best, bestd, bestcls
    for _, t in ipairs(CollectTriggers(TRIGGER_CLASSES)) do
        local loc; pcall(function() loc = t.actor:K2_GetActorLocation() end)
        if loc then
            local d = Dist2(ppos, loc)
            if not bestd or d < bestd then best, bestd, bestcls = t.actor, d, t.class end
        end
    end
    if not best then cout(Ar, "[trigger] aucun trigger/volume trouvé à proximité."); return true end
    DisableTrigger(best)
    cout(Ar, string.format("[trigger] désactivé : %s (à %.0f m).", bestcls, math.sqrt(bestd) / 100))
    return true
end)

-- ============================================================================
--  Commande console : walls  (force les murs rouges off maintenant)
-- ============================================================================
RegisterConsoleCommandGlobalHandler("walls", function(FullCommand, Parameters, Ar)
    local n = DisableAllWalls()
    cout(Ar, "[walls] " .. n .. " mur(s) rouge(s) désactivé(s).")
    return true
end)

log("Chargé. Murs rouges + reroute off en fond. Console : trigger | trigger all | trigger death | walls.")
