-- ============================================================================
--  FE PERK EXPLORER  (outil de diagnostic, temporaire)
--
--  But : COMPRENDRE comment le jeu range les perks / tags sur ton perso, pour
--  ensuite coder un vrai "debloquer toutes les perks" dans l'Unlocker.
--
--  Usage : charge une PARTIE (pas le menu), puis appuie sur F7.
--  Tout s'imprime dans la console UE4SS (la fenetre noire) et dans UE4SS.log.
--  -> copie/colle la sortie pour qu'on batisse le deblocage.
-- ============================================================================

local UEHelpers = require("UEHelpers")
local function log(m) print("[PerkExplorer] " .. tostring(m) .. "\n") end

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

-- compte + itere une liste FindAllOf sans supposer que # marche
local function each(list)
    local out = {}
    if list then for _, o in pairs(list) do out[#out + 1] = o end end
    return out
end

-- imprime les champs existants d'un objet (pcall sur chaque)
local function dumpFields(obj, fields)
    for _, f in ipairs(fields) do
        local ok, v = pcall(function() return obj[f] end)
        if ok and v ~= nil then
            local sv = "?"
            pcall(function()
                if type(v) == "userdata" then
                    if v.GetFullName then sv = v:GetFullName() else sv = "<userdata>" end
                else
                    sv = tostring(v)
                end
            end)
            log("      ." .. f .. " = " .. tostring(sv))
        end
    end
end

local function explore()
    log("================ EXPLORE PERKS (F7) ================")
    local pawn = GetPawn()
    if not pawn then log("Pawn introuvable -> charge une PARTIE d'abord."); return end
    log("Pawn: " .. pawn:GetFullName())

    -- 1) Composants du pawn : revele le composant de tags + les composants perks
    pcall(function()
        local comps = pawn.BlueprintCreatedComponents
        if comps then
            log("-- Composants du pawn --")
            for i = 1, #comps do
                local c = comps[i]
                if c and c:IsValid() then
                    local cn = ""; pcall(function() cn = c:GetClass():GetName() end)
                    local nm = ""; pcall(function() nm = c:GetName() end)
                    log("   [" .. i .. "] " .. nm .. "  :  " .. cn)
                end
            end
        else
            log("-- (pawn.BlueprintCreatedComponents indisponible) --")
        end
    end)

    -- 2) Handlers de tags cumulatifs (le coeur du systeme perks/abilities)
    for _, cls in ipairs({ "CumulativeTagsHandler", "CumulativeTagHandler" }) do
        local list = each(pcall(function() return FindAllOf(cls) end) and FindAllOf(cls) or nil)
        log("-- FindAllOf(" .. cls .. ") : " .. #list .. " instance(s) --")
        for _, h in ipairs(list) do
            if isRealActor(h) then
                log("   handler: " .. h:GetFullName())
                dumpFields(h, {
                    "CurrentTags", "ActiveTags", "Tags", "CumulativeTags",
                    "TagContainer", "CurrentCumulativeTags", "OwnedTags",
                    "TagCount", "CumulativeTagsMap",
                })
            end
        end
    end

    -- 3) Objets du systeme de perks charges en jeu
    for _, cls in ipairs({
        "BP_InteractiveObject_Loot_Perks_C",
        "BP_PerkSlotCpt_C",
        "PH_BP_PerkSystemInteraction_C",
    }) do
        local list = each(pcall(function() return FindAllOf(cls) end) and FindAllOf(cls) or nil)
        log("-- " .. cls .. " : " .. #list .. " instance(s) --")
        local shown = 0
        for _, o in ipairs(list) do
            if isRealActor(o) and shown < 4 then
                shown = shown + 1
                log("   " .. o:GetFullName())
                dumpFields(o, { "bLooted", "Looted", "bIsLooted", "PerkType", "LostPerk", "bUnlocked", "PerkTag" })
            end
        end
    end

    log("================ FIN EXPLORE ================")
end

RegisterKeyBind(Key.F7, explore)
log("Pret. Charge une partie puis appuie F7 (sortie dans la console UE4SS + UE4SS.log).")
