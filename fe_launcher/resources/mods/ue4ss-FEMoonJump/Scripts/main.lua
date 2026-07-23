-- ============================================================================
--  FADING ECHO — MOON JUMP  (mod séparé : saut infini / vol à la BotW)
--
--  Deux modes indépendants :
--   - MOONJUMP (F7)  : tant que SAUT est MAINTENU, on force la vitesse verticale
--                      -> le perso monte en continu (le "moonjump" de BotW).
--                      Repose sur LaunchCharacter(vel, false, true) : UFUNCTION
--                      d'ACharacter, donc appelable via UE4SS.
--   - MULTIJUMP (F6) : JumpMaxCount = 999 -> on peut re-sauter en l'air à volonté
--                      (saut infini "classique", garde la physique du jeu).
--
--  Console (F10) :
--   moonjump            toggle moonjump
--   moonjump speed <n>  vitesse de montée (défaut 700, en cm/s)
--   moonjump key <FKey> touche surveillée (défaut SpaceBar ; ex. Gamepad_FaceButton_Bottom)
--   multijump           toggle multijump
--   moonjump status     état courant
-- ============================================================================

local UEHelpers = require("UEHelpers")

local RISE_SPEED   = 700          -- cm/s ; ~700 = montée franche mais contrôlable
local JUMP_KEY     = "SpaceBar"   -- FKey surveillée pour le maintien
local MULTI_COUNT  = 999
local TICK_MS      = 16           -- ~60 Hz

local MoonOn, MultiOn = false, false
local SavedJumpMax = nil          -- pour restaurer proprement

local function log(m) print("[MoonJump] " .. tostring(m) .. "\n") end
local function cout(Ar, m)
    pcall(function() if Ar then Ar:Log(m) end end)
    log(m)
end

-- ---------------------------------------------------------------------------
--  Joueur / controller
-- ---------------------------------------------------------------------------
local function isRealActor(a)
    if not (a and a:IsValid()) then return false end
    local fn = ""; pcall(function() fn = a:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function GetPC()
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do
            if c and c:IsValid() and isRealActor(c.Pawn) then return c end
        end
    end
    return nil
end

local function GetPawn()
    local pc = GetPC()
    if pc and isRealActor(pc.Pawn) then return pc.Pawn end
    local ok, p = pcall(UEHelpers.GetPlayerPawn)
    if ok and isRealActor(p) then return p end
    return nil
end

local function IsJumpHeld(pc)
    local ok, down = pcall(function()
        return pc:IsInputKeyDown({ KeyName = FName(JUMP_KEY) })
    end)
    return ok and down == true
end

-- ---------------------------------------------------------------------------
--  MOONJUMP : boucle de montée tant que la touche est tenue
-- ---------------------------------------------------------------------------
LoopAsync(TICK_MS, function()
    if MoonOn then
        pcall(function()
            local pc = GetPC()
            if not (pc and IsJumpHeld(pc)) then return end
            local pawn = pc.Pawn
            if not isRealActor(pawn) then return end
            ExecuteInGameThread(function()
                pcall(function()
                    -- XYOverride=false : on garde le contrôle horizontal.
                    -- ZOverride=true   : on écrase la vitesse verticale -> montée nette,
                    --                    la gravité ne s'accumule pas.
                    pawn:LaunchCharacter({ X = 0.0, Y = 0.0, Z = RISE_SPEED * 1.0 }, false, true)
                end)
            end)
        end)
    end
    return false
end)

-- ---------------------------------------------------------------------------
--  MULTIJUMP : JumpMaxCount
-- ---------------------------------------------------------------------------
local function ApplyMultiJump(on)
    local pawn = GetPawn()
    if not pawn then return false, "joueur introuvable" end
    local ok, err = pcall(function()
        if on then
            if SavedJumpMax == nil then SavedJumpMax = pawn.JumpMaxCount end
            pawn.JumpMaxCount = MULTI_COUNT
        else
            pawn.JumpMaxCount = SavedJumpMax or 1
        end
    end)
    if not ok then return false, tostring(err) end
    return true
end

-- Le pawn est recréé au respawn / changement de zone : on réapplique en fond.
LoopAsync(2000, function()
    if MultiOn then
        pcall(function()
            local pawn = GetPawn()
            if pawn and (pawn.JumpMaxCount or 0) < MULTI_COUNT then
                pawn.JumpMaxCount = MULTI_COUNT
            end
        end)
    end
    return false
end)

-- ---------------------------------------------------------------------------
--  Toggles
-- ---------------------------------------------------------------------------
local function ToggleMoon(Ar)
    MoonOn = not MoonOn
    cout(Ar, "[moonjump] " .. (MoonOn and ("ON — maintiens " .. JUMP_KEY .. " pour monter (" .. RISE_SPEED .. " cm/s).") or "OFF."))
end

local function ToggleMulti(Ar)
    local want = not MultiOn
    local ok, err = ApplyMultiJump(want)
    if not ok then cout(Ar, "[multijump] échec : " .. tostring(err)); return end
    MultiOn = want
    cout(Ar, "[multijump] " .. (MultiOn and ("ON — JumpMaxCount = " .. MULTI_COUNT .. ".") or "OFF — JumpMaxCount restauré."))
end

RegisterKeyBind(Key.F7, function() ToggleMoon(nil) end)
RegisterKeyBind(Key.F6, function() ExecuteInGameThread(function() ToggleMulti(nil) end) end)

-- ---------------------------------------------------------------------------
--  Console
-- ---------------------------------------------------------------------------
RegisterConsoleCommandGlobalHandler("moonjump", function(FullCommand, Parameters, Ar)
    local p   = Parameters or {}
    local sub = (p[1] and string.lower(p[1])) or "toggle"

    if sub == "speed" then
        local n = tonumber(p[2])
        if not n then cout(Ar, "[moonjump] usage : moonjump speed <nombre>"); return true end
        RISE_SPEED = n
        cout(Ar, "[moonjump] vitesse de montée = " .. n .. " cm/s.")
        return true
    end

    if sub == "key" then
        if not p[2] then cout(Ar, "[moonjump] usage : moonjump key <FKey>  (ex. SpaceBar)"); return true end
        JUMP_KEY = p[2]
        cout(Ar, "[moonjump] touche surveillée = " .. JUMP_KEY .. ".")
        return true
    end

    if sub == "status" then
        local pawn = GetPawn()
        local jm = "?"
        pcall(function() if pawn then jm = tostring(pawn.JumpMaxCount) end end)
        cout(Ar, string.format("[moonjump] moon=%s multi=%s speed=%d key=%s JumpMaxCount=%s",
            tostring(MoonOn), tostring(MultiOn), RISE_SPEED, JUMP_KEY, jm))
        return true
    end

    ToggleMoon(Ar)
    return true
end)

RegisterConsoleCommandGlobalHandler("multijump", function(FullCommand, Parameters, Ar)
    ExecuteInGameThread(function() ToggleMulti(Ar) end)
    return true
end)

log("Chargé. F7 = moonjump (maintenir " .. JUMP_KEY .. "), F6 = multijump. Console : moonjump | multijump.")
