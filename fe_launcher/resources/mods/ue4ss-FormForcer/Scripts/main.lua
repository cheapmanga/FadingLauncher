-- ============================================================================
--  FADING ECHO — FORM FORCER  (mod séparé)
--
--  Commande console (F10) :
--     form water | waste | steam | nitro | glitch      -> force la forme
--     form <x> persistent                              -> la maintient en boucle
--     form stop                                        -> arrête la persistance
--
--  Levier : BP_CoreYgroCharacter_C:ActivateFluidFormNS(NewFormClass) — la SEULE
--  fonction de forme réellement appelable dans cette build (dump runtime). Elle
--  prend une CLASSE de forme (pas un FName).
--  /!\ SwitchToForm(FName), vu au désassemblage, N'EST PAS appelable ici : l'appeler
--      CRASHE (access violation). On ne l'utilise donc pas.
--
--  Classes (/Game/Game/Pawn/Playable/) : WaterForm_C, WasteForm_C, SteamForm_C,
--  BP_Player_BurningWasteForm_C (= "nitro"), CorruptionForm_C (= "glitch").
--
--  SÉCURITÉ : on ne passe la classe au natif QUE si elle est valide (jamais de nil).
-- ============================================================================

local UEHelpers = require("UEHelpers")

local function log(m) print("[FormForcer] " .. tostring(m) .. "\n") end
local function cout(Ar, m)
    pcall(function() if Ar then Ar:Log(m) end end)
    log(m)
end

local PB = "/Game/Game/Pawn/Playable/"   -- Playable base path
-- clef tapée -> { chemin de classe, nom court, libellé }
local FORMS = {
    water  = { path = PB .. "WaterForm.WaterForm_C",                              short = "WaterForm_C",                  label = "WaterForm" },
    waste  = { path = PB .. "WasteForm.WasteForm_C",                              short = "WasteForm_C",                  label = "WasteForm" },
    steam  = { path = PB .. "SteamForm.SteamForm_C",                              short = "SteamForm_C",                  label = "SteamForm" },
    nitro  = { path = PB .. "BP_Player_BurningWasteForm.BP_Player_BurningWasteForm_C", short = "BP_Player_BurningWasteForm_C", label = "BurningWasteForm" },
    glitch = { path = PB .. "CorruptionForm.CorruptionForm_C",                    short = "CorruptionForm_C",             label = "CorruptionForm" },
}

-- ---------------------------------------------------------------------------
--  Joueur (PlayerController d'abord, on exclut les Class Default Objects)
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
    local list = FindAllOf("BP_CoreYgroCharacter_C")
    if list then
        for _, a in pairs(list) do if isRealActor(a) then return a end end
    end
    return nil
end

-- UClass de la forme : objet-classe si chargé, sinon classe d'une instance présente.
local function ResolveFormClass(e)
    local c = StaticFindObject(e.path)
    if c and c:IsValid() then return c end
    local inst = FindFirstOf(e.short)
    if inst and inst:IsValid() then
        local ok, k = pcall(function() return inst:GetClass() end)
        if ok and k and k:IsValid() then return k end
    end
    return nil
end

-- Applique la forme. Renvoie (true) ou (false, message). NE passe JAMAIS un nil au natif.
local function ApplyForm(pawn, e)
    local cls = ResolveFormClass(e)
    if not (cls and cls:IsValid()) then
        return false, "classe pas chargée (" .. e.short .. "). Transforme-toi une fois dans cette forme (ou approche sa source) pour la charger, puis réessaie."
    end
    local ok = pcall(function() pawn:ActivateFluidFormNS(cls) end)
    return ok, (not ok) and "ActivateFluidFormNS a échoué." or nil
end

-- ---------------------------------------------------------------------------
--  Persistance : réapplique la forme voulue à intervalle.
-- ---------------------------------------------------------------------------
local persistKey = nil   -- clef de forme à maintenir, ou nil

LoopAsync(1000, function()
    if persistKey then
        local e = FORMS[persistKey]
        local pawn = e and GetPawn()
        if pawn then pcall(function() ApplyForm(pawn, e) end) end
    end
    return false
end)

-- ============================================================================
--  Commande console : form <élément> [persistent] | form stop
-- ============================================================================
RegisterConsoleCommandGlobalHandler("form", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local key = (p[1] and string.lower(p[1])) or ""

    if key == "stop" or key == "off" then
        persistKey = nil
        cout(Ar, "[form] persistance arrêtée.")
        return true
    end

    local e = FORMS[key]
    if not e then
        cout(Ar, "[form] usage : form water|waste|steam|nitro|glitch [persistent]  (ou : form stop)")
        return true
    end

    local persistent, forced = false, false
    for _, tok in ipairs(p) do
        local t = string.lower(tok)
        if t == "persistent" or t == "persist" or t == "loop" then persistent = true end
        if t == "force" then forced = true end
    end

    -- GARDE-FOU glitch (CorruptionForm) : crash CONFIRMÉ dans la démo (jauge de
    -- corruption non initialisée -> descripteur de stat nul -> crash au tick). On
    -- exige 'force', et on interdit la persistance (boucle de crash).
    if key == "glitch" and not forced then
        cout(Ar, "[form] glitch = CorruptionForm : CONNU pour crasher dans la démo")
        cout(Ar, "       (jauge de corruption non initialisée — confirmé par un dev).")
        cout(Ar, "       Sauvegarde ta partie, puis : form glitch force   pour tenter.")
        return true
    end
    if key == "glitch" then persistent = false end

    local pawn = GetPawn()
    if not pawn then cout(Ar, "[form] joueur introuvable."); return true end

    local ok, err = ApplyForm(pawn, e)
    if not ok then cout(Ar, "[form] " .. tostring(err)); return true end

    if persistent then
        persistKey = key
        cout(Ar, "[form] " .. key .. " (" .. e.label .. ") — PERSISTANT ('form stop' pour arrêter).")
    else
        persistKey = nil
        cout(Ar, "[form] " .. key .. " (" .. e.label .. ").")
    end
    return true
end)

log("Chargé. Tape 'form water' (water|waste|steam|nitro|glitch [persistent]) dans la console (F10).")
