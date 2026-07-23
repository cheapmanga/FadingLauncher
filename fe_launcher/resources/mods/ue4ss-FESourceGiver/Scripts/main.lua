-- ============================================================================
--  FADING ECHO — SOURCE GIVER  (sources branchées au Bastion)
--
--  Console in-game (F10) :
--    source              +1 source
--    source <n>          +n sources           (ex. source 3)
--    source set <n>      fixe le total à n     (ex. source set 12 → ouvre la fin)
--    source status       affiche le total courant, sans rien changer
--    source unlocked <n> +n sources "trouvées" (jalons 1/3/6/9), voir plus bas
--
--  ---------------------------------------------------------------------------
--  CE QU'EST UNE "SOURCE EFFECTUÉE" (relevé dans les données du jeu)
--
--  Deux statistiques distinctes portent le mot "Source" dans FE :
--    * ConnectedSources = sources BRANCHÉES au Bastion. C'est le compteur qui
--      ouvre la fin : le Level BP YGRO_Bastion_Sh0_Gameplay teste
--      `ConnectedSources == 12` (StatisticCondition, index 18) pour lancer le
--      FinalFight (12 = 3 sources × 4 zones Volcano/Tree/Quarry/Wonder).
--    * UnlockedSources = sources TROUVÉES dans les zones. Jalons de progression
--      1 / 3 / 6 / 9 (index 23). N'ouvre PAS la fin à elle seule.
--
--  Par défaut ce mod incrémente **ConnectedSources** (= "sources effectuées",
--  celles qui comptent pour la fin). `source unlocked <n>` touche l'autre.
--
--  ---------------------------------------------------------------------------
--  API — UStatisticHolderComponent, fonctions BlueprintCallable (symboles PDB) :
--      ?IncreaseStatisticBaseValue@UStatisticHolderComponent@@QEAAXVFString@@M@Z
--      ?SetStatisticBaseValue@UStatisticHolderComponent@@QEAAXVFString@@M@Z
--      ?GetStatisticValue@UStatisticHolderComponent@@QEBAMVFString@@@Z
--  soit : (FString StatisticName, float Value).
--
--  /!\ PIÈGE — StatisticName est une **FString**, PAS une FName. Passer un objet
--  FName fait crasher le jeu (push_strproperty → FString::SetCharArray → ACCESS
--  VIOLATION). On passe donc une chaîne Lua brute.
--
--  ConnectedSources est une stat de l'entité **World** (template
--  DT_WorldEntityStatTemplate), pas du holder des perks. Plusieurs
--  StatisticHolderComponent coexistent (un par template) et sont indistinguables
--  en lecture seule : GetStatisticValue renvoie 0 aussi bien pour "stat à zéro"
--  que pour "stat inconnue de ce template". On tranche donc en écrivant : le bon
--  holder est le seul dont la valeur bouge réellement après un write. Une fois
--  trouvé, on le met en cache pour les commandes suivantes.
-- ============================================================================

local UEHelpers = require("UEHelpers")

local STAT_CONNECTED = "ConnectedSources"
local STAT_UNLOCKED  = "UnlockedSources"
local GOAL           = 12   -- ConnectedSources qui ouvre le FinalFight

local function log(m) print("[SourceGiver] " .. tostring(m) .. "\n") end

-- Écrit à la fois dans la console in-game (Ar) et dans la console UE4SS.
local function cout(Ar, msg)
    pcall(function() if Ar then Ar:Log(msg) end end)
    log(msg)
end

-- vrai objet = pas un Class Default Object.
local function isReal(o)
    if not (o and o:IsValid()) then return false end
    local fn = ""; pcall(function() fn = o:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function GetPawn()
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do
            if c and c:IsValid() then
                local pk = c.Pawn
                if isReal(pk) then return pk end
            end
        end
    end
    local ok, p = pcall(UEHelpers.GetPlayerPawn)
    if ok and isReal(p) then return p end
    return nil
end

-- ---------------------------------------------------------------------------
--  Holders de statistiques
-- ---------------------------------------------------------------------------
local function AllHolders()
    local out, seen = {}, {}
    local ok, list = pcall(function() return FindAllOf("StatisticHolderComponent") end)
    if ok and list then
        for _, h in pairs(list) do
            if h and h:IsValid() then
                local fn = ""; pcall(function() fn = h:GetFullName() end)
                if not seen[fn] and not string.find(fn, "Default__", 1, true) then
                    seen[fn] = true; table.insert(out, h)
                end
            end
        end
    end
    return out
end

-- /!\ chaîne Lua brute (FString), jamais un FName. Voir l'entête.
local function ReadStat(holder, stat)
    local v
    local ok = pcall(function() v = holder:GetStatisticValue(stat) end)
    if ok and type(v) == "number" then return v end
    return nil
end

local function holderReady(h)
    local ready = true
    pcall(function() ready = h:IsReady() end)
    return ready ~= false
end

-- Cache du holder qui porte la stat World (une fois identifié par un write qui
-- a bougé, on le réutilise pour les commandes suivantes).
local sourceHolder = nil

local function cachedHolderValid()
    return sourceHolder and sourceHolder:IsValid() and isReal(sourceHolder)
end

-- Incrémente `stat` de n sur le bon holder. Renvoie (holder, avant, apres) ou nil.
local function IncreaseStat(stat, n)
    -- 1) tente d'abord le holder en cache.
    if cachedHolderValid() and holderReady(sourceHolder) then
        local before = ReadStat(sourceHolder, stat)
        if before then
            pcall(function() sourceHolder:IncreaseStatisticBaseValue(stat, n * 1.0) end)
            local after = ReadStat(sourceHolder, stat)
            if after and after > before then return sourceHolder, before, after end
        end
    end
    -- 2) sinon on balaie tous les holders : le bon est celui dont la valeur bouge.
    for _, h in ipairs(AllHolders()) do
        if holderReady(h) then
            local before = ReadStat(h, stat)
            if before then
                pcall(function() h:IncreaseStatisticBaseValue(stat, n * 1.0) end)
                local after = ReadStat(h, stat)
                if after and after > before then
                    sourceHolder = h
                    return h, before, after
                end
            end
        end
    end
    return nil
end

-- Fixe `stat` à target sur le bon holder. Renvoie (holder, avant, apres) ou nil.
local function SetStat(stat, target)
    local function tryOn(h)
        if not holderReady(h) then return nil end
        local before = ReadStat(h, stat)
        if not before then return nil end
        pcall(function() h:SetStatisticBaseValue(stat, target * 1.0) end)
        local after = ReadStat(h, stat)
        -- accepté si la valeur vaut bien la cible (et qu'on a pu la relire).
        if after and math.abs(after - target) < 0.001 then return before, after end
        return nil
    end

    if cachedHolderValid() then
        local b, a = tryOn(sourceHolder)
        if a then return sourceHolder, b, a end
    end
    for _, h in ipairs(AllHolders()) do
        local b, a = tryOn(h)
        if a then sourceHolder = h; return h, b, a end
    end
    return nil
end

-- Lit `stat` sur le premier holder qui la connaît (préférence au cache).
local function StatusOf(stat)
    if cachedHolderValid() then
        local v = ReadStat(sourceHolder, stat)
        if v then return v end
    end
    -- En lecture seule on ne distingue pas "0" de "inconnu" ; on renvoie la plus
    -- grande valeur lue (une source déjà branchée = valeur > 0 sur le bon holder).
    local best = nil
    for _, h in ipairs(AllHolders()) do
        local v = ReadStat(h, stat)
        if v and (not best or v > best) then best = v end
    end
    return best
end

-- ---------------------------------------------------------------------------
--  Commande console
-- ---------------------------------------------------------------------------
local USAGE = "[source] usage : source | source <n> | source set <n> | source status | source unlocked <n>"

RegisterConsoleCommandGlobalHandler("source", function(FullCommand, Parameters, Ar)
    local p  = Parameters or {}
    local a1 = p[1] and string.lower(p[1]) or nil
    local a2 = p[2]

    -- source status
    if a1 == "status" or a1 == "get" then
        local c = StatusOf(STAT_CONNECTED)
        local u = StatusOf(STAT_UNLOCKED)
        cout(Ar, string.format("[source] branchées (ConnectedSources) : %s / %d%s",
            c and string.format("%.0f", c) or "?", GOAL,
            u and string.format("   |   trouvées (UnlockedSources) : %.0f", u) or ""))
        if not c then
            cout(Ar, "[source] holder introuvable — es-tu bien en jeu (pas dans un menu) ?")
        end
        return true
    end

    -- source set <n>
    if a1 == "set" then
        local target = tonumber(a2)
        if not target or target < 0 then cout(Ar, USAGE); return true end
        target = math.floor(target)
        if not GetPawn() then cout(Ar, "[source] joueur introuvable — es-tu bien en jeu ?"); return true end
        local h, before, after = SetStat(STAT_CONNECTED, target)
        if not h then
            cout(Ar, "[source] échec : aucun holder n'a accepté d'écrire " .. STAT_CONNECTED ..
                     ". Charge d'abord le Bastion puis réessaie.")
            return true
        end
        cout(Ar, string.format("[source] ConnectedSources fixé à %.0f (avant : %.0f).", after, before))
        if after >= GOAL then
            cout(Ar, "[source] ≥ 12 → condition du FinalFight remplie.")
        end
        return true
    end

    -- source unlocked <n>
    if a1 == "unlocked" or a1 == "found" then
        local n = tonumber(a2) or 1
        if n < 1 then cout(Ar, USAGE); return true end
        n = math.floor(n)
        if not GetPawn() then cout(Ar, "[source] joueur introuvable — es-tu bien en jeu ?"); return true end
        local h, before, after = IncreaseStat(STAT_UNLOCKED, n)
        if not h then
            cout(Ar, "[source] échec : aucun holder n'a accepté d'incrémenter " .. STAT_UNLOCKED .. ".")
            return true
        end
        cout(Ar, string.format("[source] +%d → %.0f source(s) trouvée(s) (avant : %.0f).", n, after, before))
        return true
    end

    -- source  |  source <n>   → incrémente ConnectedSources
    local n = 1
    if a1 then
        n = tonumber(a1)
        if not n or n < 1 then cout(Ar, USAGE); return true end
        n = math.floor(n)
    end

    if not GetPawn() then
        cout(Ar, "[source] joueur introuvable — es-tu bien en jeu (pas dans un menu) ?")
        return true
    end

    local h, before, after = IncreaseStat(STAT_CONNECTED, n)
    if not h then
        cout(Ar, "[source] échec : aucun holder n'a accepté d'incrémenter " .. STAT_CONNECTED ..
                 ". Charge d'abord le Bastion (là où l'on branche les sources) puis réessaie.")
        return true
    end
    cout(Ar, string.format("[source] +%d → %.0f / %d source(s) branchée(s) (avant : %.0f).",
        n, after, GOAL, before))
    if after >= GOAL and before < GOAL then
        cout(Ar, "[source] ≥ 12 → condition du FinalFight remplie.")
    end
    return true
end)

log("Chargé. Console in-game (F10) : source | source <n> | source set <n> | source status")
