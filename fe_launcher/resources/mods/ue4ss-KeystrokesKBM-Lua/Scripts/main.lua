-- ============================================================================
--  Keystrokes KB+M (Lua) — input display CLAVIER + SOURIS pour Fading Echo
--  Rendu : dessiné sur le HUD du jeu (AYgroHUD -> DrawRect/DrawText).
--  Input : PlayerController:IsInputKeyDown(FKey).
--
--  Touches :
--    F8 = afficher / masquer l'overlay
--    F9 = auto-diagnostic (écrit dans la console UE4SS ce qui marche)
--
--  ⚠️ Comme je n'ai pas pu tester en jeu, ce mod est écrit "défensif" :
--     s'il n'affiche rien, lance F9 et envoie-moi la sortie console -> je corrige.
-- ============================================================================

local UEHelpers = require("UEHelpers")

-- ---------------------------------------------------------------------------
--  CONFIG — édite librement (colle à TES binds Fading Echo)
--  fkey = nom d'FKey Unreal. Clavier: "W","A","S","D","E","Q","SpaceBar",
--         "LeftShift","LeftControl". Souris: "LeftMouseButton",
--         "RightMouseButton","MiddleMouseButton".
--  col/row = position en cellules. w = largeur en cellules (1 par défaut).
-- ---------------------------------------------------------------------------
local KEYS = {
    { label = "W",     fkey = "W",                col = 1,   row = 0, w = 1   },
    { label = "A",     fkey = "A",                col = 0,   row = 1, w = 1   },
    { label = "S",     fkey = "S",                col = 1,   row = 1, w = 1   },
    { label = "D",     fkey = "D",                col = 2,   row = 1, w = 1   },
    { label = "Shift", fkey = "LeftShift",        col = 0,   row = 2, w = 1.6 },
    { label = "Ctrl",  fkey = "LeftControl",      col = 1.7, row = 2, w = 1.4 },
    { label = "E",     fkey = "E",                col = 3.2, row = 1, w = 1   },
    { label = "Q",     fkey = "Q",                col = 3.2, row = 2, w = 1   },
    { label = "Space", fkey = "SpaceBar",         col = 0,   row = 3, w = 3   },
    -- souris (décalées à droite)
    { label = "LMB",   fkey = "LeftMouseButton",  col = 5.2, row = 0, w = 1.2 },
    { label = "MMB",   fkey = "MiddleMouseButton",col = 6.5, row = 0, w = 1.2 },
    { label = "RMB",   fkey = "RightMouseButton", col = 7.8, row = 0, w = 1.2 },
}

-- Position / taille de l'overlay (en pixels écran)
local ORIGIN_X = 60.0
local ORIGIN_Y = 220.0
local CELL     = 40.0     -- pas de grille
local BOX      = 34.0     -- taille d'un pavé
local TEXT_SCALE = 1.0

-- Couleurs (FLinearColor, 0..1)
local C_IDLE   = { R = 0.12, G = 0.12, B = 0.14, A = 0.72 }
local C_ACTIVE = { R = 0.31, G = 0.78, B = 1.00, A = 0.95 }
local C_BORDER = { R = 0.00, G = 0.00, B = 0.00, A = 0.85 }
local C_T_IDLE = { R = 0.85, G = 0.85, B = 0.88, A = 1.00 }
local C_T_ON   = { R = 0.04, G = 0.04, B = 0.06, A = 1.00 }

-- ---------------------------------------------------------------------------
--  ÉTAT
-- ---------------------------------------------------------------------------
local Visible   = true
local PC        = nil     -- PlayerController caché
local Font      = nil     -- police pour DrawText
local HookCount = 0       -- nb de fois où le hook HUD a tourné (diag)

-- ---------------------------------------------------------------------------
--  UTILS
-- ---------------------------------------------------------------------------
local function log(msg) print("[KeystrokesKBM] " .. tostring(msg) .. "\n") end

local function GetPC()
    if PC and PC:IsValid() then return PC end
    local ok, pc = pcall(UEHelpers.GetPlayerController)
    if ok and pc and pc:IsValid() then PC = pc; return PC end
    local list = FindAllOf("PlayerController")
    if list then
        for _, c in ipairs(list) do
            if c:IsValid() then PC = c; return PC end
        end
    end
    return nil
end

local function GetFont()
    if Font and Font:IsValid() then return Font end
    -- police moteur standard ; chargée au besoin
    pcall(function() LoadAsset("/Engine/EngineFonts/Roboto") end)
    local ok, f = pcall(StaticFindObject, "/Engine/EngineFonts/Roboto.Roboto")
    if ok and f and f:IsValid() then Font = f end
    return Font
end

-- Une FKey est-elle enfoncée ? (via PlayerController)
local function IsDown(fkeyName)
    local pc = GetPC()
    if not pc then return false end
    local ok, res = pcall(function()
        return pc:IsInputKeyDown({ KeyName = FName(fkeyName) })
    end)
    if ok then return res and true or false end
    return false
end

-- Dessine un pavé (bordure + fond + label)
local function DrawBox(hud, x, y, w, h, label, active)
    pcall(function()
        -- bordure (rect noir légèrement plus grand)
        hud:DrawRect(C_BORDER, x - 1.5, y - 1.5, w + 3.0, h + 3.0)
        hud:DrawRect(active and C_ACTIVE or C_IDLE, x, y, w, h)
    end)
    local f = GetFont()
    if f then
        pcall(function()
            hud:DrawText(label, active and C_T_ON or C_T_IDLE,
                         x + 6.0, y + h * 0.5 - 7.0, f, TEXT_SCALE, false)
        end)
    end
end

-- ---------------------------------------------------------------------------
--  RENDU (appelé chaque frame par le hook HUD)
-- ---------------------------------------------------------------------------
local function DrawOverlay(hud)
    if not Visible then return end
    for _, k in ipairs(KEYS) do
        local x = ORIGIN_X + k.col * CELL
        local y = ORIGIN_Y + k.row * CELL
        local w = BOX * (k.w or 1)
        DrawBox(hud, x, y, w, BOX, k.label, IsDown(k.fkey))
    end
end

-- ---------------------------------------------------------------------------
--  HOOK HUD — on tente d'abord AYgroHUD, puis la classe moteur de base
-- ---------------------------------------------------------------------------
-- callback commun de rendu (utilisé par tous les hooks)
local function HudHookCb(self)
    HookCount = HookCount + 1
    local hud = self:get()
    if hud and hud:IsValid() then pcall(DrawOverlay, hud) end
end

-- Trouve l'instance HUD réelle et loggue sa classe (info décisive).
local function FindHUD()
    local hud = FindFirstOf("YgroHUD")
    if not (hud and hud:IsValid()) then hud = FindFirstOf("HUD") end
    if hud and hud:IsValid() then return hud end
    return nil
end

local function InstallHudHook()
    -- 1) hook générique sur la classe moteur de base (au cas où)
    pcall(function()
        RegisterHook("/Script/Engine.HUD:ReceiveDrawHUD", HudHookCb)
        log("Hook posé sur /Script/Engine.HUD:ReceiveDrawHUD")
    end)

    -- 2) découverte de l'instance HUD réelle -> hook sur SA classe
    local hud = FindHUD()
    if not hud then
        log("!! Instance HUD introuvable (FindFirstOf YgroHUD/HUD). HUD peut-être pas encore spawn.")
        return
    end
    log("HUD instance : " .. hud:GetFullName())
    pcall(function() hud.bShowHUD = true end) -- s'assurer que le HUD dessine

    local ok, cls = pcall(function() return hud:GetClass() end)
    if ok and cls and cls:IsValid() then
        local full = cls:GetFullName()          -- ex: "Class /Script/UE_YGRO.YgroHUD" ou "BlueprintGeneratedClass /Game/.../BP_YgroHUD.BP_YgroHUD_C"
        log("HUD class  : " .. full)
        local path = full:match("%S+%s+(.+)$")  -- retire le préfixe (Class/BlueprintGeneratedClass)
        if path then
            local hookPath = path .. ":ReceiveDrawHUD"
            local ok2 = pcall(function() RegisterHook(hookPath, HudHookCb) end)
            log("Hook classe réelle (" .. hookPath .. ") : " .. (ok2 and "posé" or "échec"))
        end
    end
end

-- ---------------------------------------------------------------------------
--  DIAGNOSTIC (F9)
-- ---------------------------------------------------------------------------
local function SelfTest()
    log("===== AUTO-DIAGNOSTIC =====")
    local pc = GetPC()
    log("PlayerController : " .. (pc and "OK" or "INTROUVABLE"))
    if pc then
        local ok, res = pcall(function() return pc:IsInputKeyDown({ KeyName = FName("W") }) end)
        log("IsInputKeyDown('W') appelable : " .. (ok and ("OUI (=" .. tostring(res) .. ")") or "NON -> " .. tostring(res)))
    end
    log("Font Roboto : " .. (GetFont() and "OK" or "INTROUVABLE (les pavés s'afficheront sans texte)"))
    local hud = FindHUD()
    if hud then
        log("HUD instance : " .. hud:GetFullName())
        local ok, cls = pcall(function() return hud:GetClass() end)
        if ok and cls and cls:IsValid() then log("HUD class : " .. cls:GetFullName()) end
        local ok2, sh = pcall(function() return hud.bShowHUD end)
        log("bShowHUD : " .. (ok2 and tostring(sh) or "illisible"))
    else
        log("HUD instance : INTROUVABLE")
    end
    log("HUD hook déclenché " .. HookCount .. " fois (doit augmenter si le HUD rend)")
    log("Overlay visible : " .. tostring(Visible))
    log("===========================")
end

-- ---------------------------------------------------------------------------
--  INIT
-- ---------------------------------------------------------------------------
RegisterKeyBind(Key.F8, function() Visible = not Visible; log("Overlay = " .. tostring(Visible)) end)
RegisterKeyBind(Key.F9, function() SelfTest() end)

-- on installe le hook un peu après le chargement (HUD pas dispo trop tôt)
ExecuteWithDelay(3000, function()
    InstallHudHook()
    GetFont()
    log("Chargé. F8 = afficher/masquer, F9 = diagnostic.")
end)
