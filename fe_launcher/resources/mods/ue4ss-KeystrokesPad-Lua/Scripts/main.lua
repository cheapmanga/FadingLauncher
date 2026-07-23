-- ============================================================================
--  Keystrokes Pad (Lua) — input display MANETTE pour Fading Echo
--  Rendu : dessiné sur le HUD du jeu (AYgroHUD -> DrawRect/DrawText).
--  Input : PlayerController:IsInputKeyDown (boutons)
--          + GetInputAnalogKeyState (gâchettes) + GetInputAnalogStickState (sticks).
--
--  Touches :
--    F8 = afficher / masquer l'overlay
--    F9 = auto-diagnostic (console UE4SS)
--
--  ⚠️ Non testé en jeu (analogique manette via Lua = best-effort). Si un élément
--     manque, lance F9 et envoie-moi la sortie -> je corrige les noms d'FKey/enums.
-- ============================================================================

local UEHelpers = require("UEHelpers")

-- Boutons manette (FKey Unreal). Layout en cellules.
local BUTTONS = {
    -- face buttons (droite)
    { label = "Y",  fkey = "Gamepad_FaceButton_Top",    col = 7,   row = 1 },
    { label = "X",  fkey = "Gamepad_FaceButton_Left",   col = 6,   row = 2 },
    { label = "B",  fkey = "Gamepad_FaceButton_Right",  col = 8,   row = 2 },
    { label = "A",  fkey = "Gamepad_FaceButton_Bottom", col = 7,   row = 3 },
    -- d-pad (gauche)
    { label = "Up", fkey = "Gamepad_DPad_Up",           col = 1,   row = 1 },
    { label = "Lt", fkey = "Gamepad_DPad_Left",         col = 0,   row = 2 },
    { label = "Rt", fkey = "Gamepad_DPad_Right",        col = 2,   row = 2 },
    { label = "Dn", fkey = "Gamepad_DPad_Down",         col = 1,   row = 3 },
    -- bumpers + start/back + clic sticks
    { label = "LB", fkey = "Gamepad_LeftShoulder",      col = 0,   row = 0 },
    { label = "RB", fkey = "Gamepad_RightShoulder",     col = 8,   row = 0 },
    { label = "Bk", fkey = "Gamepad_Special_Left",      col = 3.4, row = 0 },
    { label = "St", fkey = "Gamepad_Special_Right",     col = 4.6, row = 0 },
    { label = "L3", fkey = "Gamepad_LeftThumbstick",    col = 3.4, row = 4 },
    { label = "R3", fkey = "Gamepad_RightThumbstick",   col = 4.6, row = 4 },
}

-- Gâchettes analogiques (axe 0..1)
local TRIGGERS = {
    { label = "LT", fkey = "Gamepad_LeftTriggerAxis",  col = 0, row = 4 },
    { label = "RT", fkey = "Gamepad_RightTriggerAxis", col = 7, row = 4 },
}

-- Enum EControllerAnalogStick : CAS_None=0, CAS_LeftStick=1, CAS_RightStick=2
local STICK_LEFT, STICK_RIGHT = 1, 2

local ORIGIN_X, ORIGIN_Y = 60.0, 220.0
local CELL, BOX, TEXT_SCALE = 40.0, 34.0, 1.0

local C_IDLE   = { R = 0.12, G = 0.12, B = 0.14, A = 0.72 }
local C_ACTIVE = { R = 0.31, G = 0.78, B = 1.00, A = 0.95 }
local C_BORDER = { R = 0.00, G = 0.00, B = 0.00, A = 0.85 }
local C_T_IDLE = { R = 0.85, G = 0.85, B = 0.88, A = 1.00 }
local C_T_ON   = { R = 0.04, G = 0.04, B = 0.06, A = 1.00 }
local C_BARBG  = { R = 0.10, G = 0.10, B = 0.12, A = 0.72 }

local Visible, PC, Font, HookCount = true, nil, nil, 0

local function log(m) print("[KeystrokesPad] " .. tostring(m) .. "\n") end

local function GetPC()
    if PC and PC:IsValid() then return PC end
    local ok, pc = pcall(UEHelpers.GetPlayerController)
    if ok and pc and pc:IsValid() then PC = pc; return PC end
    local list = FindAllOf("PlayerController")
    if list then for _, c in ipairs(list) do if c:IsValid() then PC = c; return PC end end end
    return nil
end

local function GetFont()
    if Font and Font:IsValid() then return Font end
    pcall(function() LoadAsset("/Engine/EngineFonts/Roboto") end)
    local ok, f = pcall(StaticFindObject, "/Engine/EngineFonts/Roboto.Roboto")
    if ok and f and f:IsValid() then Font = f end
    return Font
end

local function IsDown(fkeyName)
    local pc = GetPC(); if not pc then return false end
    local ok, res = pcall(function() return pc:IsInputKeyDown({ KeyName = FName(fkeyName) }) end)
    return ok and res and true or false
end

local function AnalogKey(fkeyName)
    local pc = GetPC(); if not pc then return 0.0 end
    local ok, res = pcall(function() return pc:GetInputAnalogKeyState({ KeyName = FName(fkeyName) }) end)
    return (ok and type(res) == "number") and res or 0.0
end

local function StickState(which)
    local pc = GetPC(); if not pc then return 0.0, 0.0 end
    local ok, x, y = pcall(function() return pc:GetInputAnalogStickState(which, 0.0, 0.0) end)
    if ok and type(x) == "number" and type(y) == "number" then return x, y end
    return 0.0, 0.0
end

local function DrawBox(hud, x, y, w, h, label, active)
    pcall(function()
        hud:DrawRect(C_BORDER, x - 1.5, y - 1.5, w + 3.0, h + 3.0)
        hud:DrawRect(active and C_ACTIVE or C_IDLE, x, y, w, h)
    end)
    local f = GetFont()
    if f then pcall(function()
        hud:DrawText(label, active and C_T_ON or C_T_IDLE, x + 6.0, y + h * 0.5 - 7.0, f, TEXT_SCALE, false)
    end) end
end

local function DrawBar(hud, x, y, w, h, t, label)
    if t < 0 then t = 0 elseif t > 1 then t = 1 end
    pcall(function()
        hud:DrawRect(C_BORDER, x - 1.5, y - 1.5, w + 3.0, h + 3.0)
        hud:DrawRect(C_BARBG, x, y, w, h)
        if t > 0 then hud:DrawRect(C_ACTIVE, x, y, w * t, h) end
    end)
    local f = GetFont()
    if f then pcall(function() hud:DrawText(label, C_T_IDLE, x, y + h + 2.0, f, TEXT_SCALE, false) end) end
end

-- carré de stick + point (x,y ∈ [-1,1])
local function DrawStick(hud, cx, cy, r, x, y, label)
    pcall(function()
        hud:DrawRect(C_BORDER, cx - r - 1.5, cy - r - 1.5, 2 * r + 3.0, 2 * r + 3.0)
        hud:DrawRect(C_IDLE, cx - r, cy - r, 2 * r, 2 * r)
        local dx = cx + x * (r - 4.0)
        local dy = cy - y * (r - 4.0)   -- Y écran inversé
        hud:DrawRect(C_ACTIVE, dx - 4.0, dy - 4.0, 8.0, 8.0)
    end)
    local f = GetFont()
    if f then pcall(function() hud:DrawText(label, C_T_IDLE, cx - r, cy + r + 3.0, f, TEXT_SCALE, false) end) end
end

local function DrawOverlay(hud)
    if not Visible then return end
    for _, b in ipairs(BUTTONS) do
        DrawBox(hud, ORIGIN_X + b.col * CELL, ORIGIN_Y + b.row * CELL, BOX, BOX, b.label, IsDown(b.fkey))
    end
    for _, t in ipairs(TRIGGERS) do
        DrawBar(hud, ORIGIN_X + t.col * CELL, ORIGIN_Y + t.row * CELL, 90.0, 14.0, AnalogKey(t.fkey), t.label)
    end
    local lx, ly = StickState(STICK_LEFT)
    local rx, ry = StickState(STICK_RIGHT)
    DrawStick(hud, ORIGIN_X + 3.9 * CELL, ORIGIN_Y + 2.2 * CELL, 30.0, lx, ly, "L-Stick")
    DrawStick(hud, ORIGIN_X + 5.6 * CELL, ORIGIN_Y + 2.2 * CELL, 30.0, rx, ry, "R-Stick")
end

local function InstallHudHook()
    local targets = {
        "/Script/UE_YGRO.YgroHUD:ReceiveDrawHUD",
        "/Script/Engine.HUD:ReceiveDrawHUD",
    }
    for _, path in ipairs(targets) do
        local ok = pcall(function()
            RegisterHook(path, function(self)
                HookCount = HookCount + 1
                local hud = self:get()
                if hud and hud:IsValid() then pcall(DrawOverlay, hud) end
            end)
        end)
        if ok then log("Hook HUD posé sur : " .. path) end
    end
end

local function SelfTest()
    log("===== AUTO-DIAGNOSTIC =====")
    local pc = GetPC()
    log("PlayerController : " .. (pc and "OK" or "INTROUVABLE"))
    if pc then
        local ok1, r1 = pcall(function() return pc:IsInputKeyDown({ KeyName = FName("Gamepad_FaceButton_Bottom") }) end)
        log("IsInputKeyDown(A) : " .. (ok1 and ("OUI (=" .. tostring(r1) .. ")") or "NON -> " .. tostring(r1)))
        local ok2, r2 = pcall(function() return pc:GetInputAnalogKeyState({ KeyName = FName("Gamepad_LeftTriggerAxis") }) end)
        log("GetInputAnalogKeyState(LT) : " .. (ok2 and ("OUI (=" .. tostring(r2) .. ")") or "NON -> " .. tostring(r2)))
        local ok3, x, y = pcall(function() return pc:GetInputAnalogStickState(STICK_LEFT, 0.0, 0.0) end)
        log("GetInputAnalogStickState(L) : " .. (ok3 and ("OUI (x=" .. tostring(x) .. ", y=" .. tostring(y) .. ")") or "NON -> " .. tostring(x)))
    end
    log("Font Roboto : " .. (GetFont() and "OK" or "INTROUVABLE"))
    log("HUD hook déclenché " .. HookCount .. " fois")
    log("===========================")
end

RegisterKeyBind(Key.F8, function() Visible = not Visible; log("Overlay = " .. tostring(Visible)) end)
RegisterKeyBind(Key.F9, function() SelfTest() end)

ExecuteWithDelay(3000, function()
    InstallHudHook()
    GetFont()
    log("Chargé. F8 = afficher/masquer, F9 = diagnostic.")
end)
