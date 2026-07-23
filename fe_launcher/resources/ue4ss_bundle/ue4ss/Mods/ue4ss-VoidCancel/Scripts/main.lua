--[[==============================================================
  Fading Echo — Void Cancel Toggle  (mod UE4SS Lua)
  F9  = ACTIVER le Void Cancel   (fall forever, no void, no respawn)
  F10 = DÉSACTIVER le Void Cancel (rétablit void + respawn)

  Mécanisme (confirmé par reverse du binaire) : sur le
  UDeathBehaviorComponent du joueur —
    PreventFallDeath()  -> inc PreventFallDeathVolumeActivated (no void)
    AllowFallDeath()    -> dec ce compteur
    SetPreventRevive(b) -> PreventRevive (no respawn)
  Le VC = compteur > 0 ET PreventRevive = true.

  N'appelle QUE ces UFUNCTIONs (pas de manip de stats) -> ne peut pas
  déclencher le crash du StatisticSubsystem.
================================================================]]--

------------------------------------------------------------------
-- CONFIG --------------------------------------------------------
------------------------------------------------------------------
local ACTIVATE_KEY   = Key.F9
local DEACTIVATE_KEY = Key.F10

------------------------------------------------------------------
-- INTERNES ------------------------------------------------------
------------------------------------------------------------------
local PLAYER_CLASS = "BP_CoreYgroCharacter_C"

local function log(m) print("[VoidCancel] " .. tostring(m) .. "\n") end

local function isValid(o)
    if o == nil then return false end
    local ok, v = pcall(function() return o:IsValid() end)
    return ok and v == true
end

local function getPawn()
    local p = FindFirstOf(PLAYER_CLASS)
    if isValid(p) then return p end
    return nil
end

-- récupère le UDeathBehaviorComponent DU JOUEUR
local function getDeathComp(pawn)
    local ok, c = pcall(function() return pawn.BP_DeathBehaviour end)
    if ok and isValid(c) then return c end
    ok, c = pcall(function() return pawn.DeathBehaviour end)
    if ok and isValid(c) then return c end
    -- fallback : instance globale (attention si plusieurs) — on prend celle du joueur si possible
    for _, name in ipairs({ "DeathBehaviorComponent", "UDeathBehaviorComponent" }) do
        local g = FindFirstOf(name)
        if isValid(g) then return g end
    end
    return nil
end

-- lit le compteur PreventFallDeathVolumeActivated (si la prop est réfléchie)
local function readCounter(comp)
    local ok, v = pcall(function() return comp.PreventFallDeathVolumeActivated end)
    if ok and type(v) == "number" then return v end
    return nil
end

local function withComp(fn)
    ExecuteInGameThread(function()
        local pawn = getPawn()
        if not pawn then log("Joueur introuvable (" .. PLAYER_CLASS .. ").") return end
        local comp = getDeathComp(pawn)
        if not comp then log("UDeathBehaviorComponent introuvable sur le joueur.") return end
        fn(comp)
    end)
end

local function activate()
    withComp(function(comp)
        pcall(function() comp:PreventFallDeath() end)   -- inc compteur -> no void
        pcall(function() comp:SetPreventRevive(true) end) -- no respawn
        local n = readCounter(comp)
        log("Void Cancel ACTIVÉ  (no void, no respawn)" .. (n and ("  [compteur=" .. n .. "]") or ""))
    end)
end

local function deactivate()
    withComp(function(comp)
        pcall(function() comp:SetPreventRevive(false) end) -- respawn réactivé
        -- ramener le compteur à 0 (refcount) sans passer en négatif
        local n = readCounter(comp)
        if n then
            local guard = 0
            while (readCounter(comp) or 0) > 0 and guard < 256 do
                pcall(function() comp:AllowFallDeath() end)
                guard = guard + 1
            end
        else
            -- compteur non lisible : on tente AllowFallDeath quelques fois + écriture directe
            for _ = 1, 8 do pcall(function() comp:AllowFallDeath() end) end
            pcall(function() comp.PreventFallDeathVolumeActivated = 0 end)
        end
        local left = readCounter(comp)
        log("Void Cancel DÉSACTIVÉ  (void + respawn rétablis)" .. (left and ("  [compteur=" .. left .. "]") or ""))
    end)
end

RegisterKeyBind(ACTIVATE_KEY, activate)
RegisterKeyBind(DEACTIVATE_KEY, deactivate)
log("Chargé.  F9 = activer Void Cancel  |  F10 = désactiver")
