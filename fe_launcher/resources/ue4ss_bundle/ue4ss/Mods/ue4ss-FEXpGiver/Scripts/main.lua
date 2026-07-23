-- ============================================================================
--  FADING ECHO — XP GIVER  (points d'Ætherfact)
--
--  Console in-game (F10) :
--    xp             +1 point d'Ætherfact
--    xp <n>         +n points (ex. xp 5)
--    xp status      solde courant, sans rien donner
--
--  ---------------------------------------------------------------------------
--  CE QU'EST UN "POINT D'ÆTHERFACT" (relevé dans les données du jeu)
--
--  C'est la statistique **SkillPointBalance**, ligne 3 de la DataTable
--  DT_PerksStatTemplate (/Game/Game/Perks/Test/DT_PerksStatTemplate) :
--      [ 3] SkillPointBalance   default=0  min=0  max=+Inf
--
--  Preuves croisées :
--   * WBP_PerkToolTip affiche "Cost" + "Ætherfact point(s)" -> c'est le prix des perks.
--   * CHAQUE DA_Perk_*.json porte une StatisticCondition sur SkillPointBalance
--     (le contrôle du coût à l'achat).
--   * DA_IncreaseSkillPoints_XS_StatisticModifier = "SkillPointBalance += 1.0"
--     (Operator=Addition, Operand=FlatValue 1.0, StatisticIndex=3) — c'est la
--     récompense de level-up du jeu, référencée par DA_LevelUpDescriptor.
--
--  ---------------------------------------------------------------------------
--  POURQUOI IncreaseStatisticBaseValue ET PAS ApplyStatisticModifierSet
--
--  UStatisticHolderComponent expose 6 fonctions BlueprintCallable (confirmées au
--  PDB, symboles exec*). Signatures EXACTES, lues dans les symboles mangés :
--
--      ?IncreaseStatisticBaseValue@UStatisticHolderComponent@@QEAAXVFString@@M@Z
--      ?SetStatisticBaseValue@UStatisticHolderComponent@@QEAAXVFString@@M@Z
--      ?GetStatisticValue@UStatisticHolderComponent@@QEBAMVFString@@@Z
--
--  soit : (FString StatisticName, float Value).
--
--  /!\ PIÈGE — StatisticName est une **FString**, pas une FName.
--  GetStatisticValue est surchargée en C++ (FString / FName / FStatisticIdentifier),
--  mais c'est la surcharge **FString** qui est exposée au Blueprint. Passer un objet
--  FName ici fait crasher le jeu : UE4SS écrit l'argument comme une StrProperty
--  (push_strproperty -> FString::SetCharArray) et déréférence n'importe quoi
--  -> EXCEPTION_ACCESS_VIOLATION. On passe donc une chaîne Lua brute.
--  (Le type FGenericPropertyParams des NewProp_ au PDB ne permet PAS de trancher
--   FName vs FString : il couvre les deux. Seul le symbole mangé le dit.)
--
--  Le jeu, lui, donne ses points via ApplyStatisticModifierSet(DA_IncreaseSkillPoints_XS).
--  On ne fait PAS ça ici : un modifier set est une COUCHE qu'on applique/retire
--  (Apply/Unapply). Rien ne garantit qu'appliquer deux fois le même descripteur
--  empile deux fois — or on veut justement pouvoir retaper 'xp' en boucle.
--  IncreaseStatisticBaseValue écrit la valeur de BASE : c'est cumulatif par
--  construction, donc répétable.
-- ============================================================================

local UEHelpers = require("UEHelpers")

local STAT = "SkillPointBalance"

local function log(m) print("[XpGiver] " .. tostring(m) .. "\n") end

-- Écrit à la fois dans la console in-game (Ar) et dans la console UE4SS.
local function cout(Ar, msg)
    pcall(function() if Ar then Ar:Log(msg) end end)
    log(msg)
end

-- vrai acteur/objet = pas un Class Default Object.
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
--  Trouver le StatisticHolderComponent qui porte DT_PerksStatTemplate.
--
--  Chemin principal : PH_XP_Manager_C (ActorComponent) expose une propriété
--  StatHolder : StatisticHolderComponent. C'est le composant qui gère la monnaie
--  (il a UpdateCurrency(CurrencyToAdd), XPCurrency, OnCurrencyIncrease) —
--  son holder est donc bien celui du template des perks.
--
--  Repli : on balaie les StatisticHolderComponent du pawn. Comme plusieurs
--  holders coexistent (un par template : santé, perks...), on ne peut pas les
--  distinguer par lecture seule — GetStatisticValue renvoie 0 aussi bien pour
--  "stat à zéro" que pour "stat inconnue de ce template". On tranche donc en
--  écrivant : le bon holder est celui dont la valeur bouge réellement.
-- ---------------------------------------------------------------------------
local function ManagerHolder()
    local mgrs = FindAllOf("PH_XP_Manager_C")
    if not mgrs then return nil end
    for _, m in pairs(mgrs) do
        if isReal(m) then
            local h
            pcall(function() h = m.StatHolder end)
            if h and h:IsValid() then return h end
        end
    end
    return nil
end

local function CandidateHolders()
    local out, seen = {}, {}
    local function add(h)
        if h and h:IsValid() then
            local fn = ""; pcall(function() fn = h:GetFullName() end)
            if not seen[fn] and not string.find(fn, "Default__", 1, true) then
                seen[fn] = true; table.insert(out, h)
            end
        end
    end
    add(ManagerHolder())                      -- le bon, en principe
    local ok, list = pcall(function() return FindAllOf("StatisticHolderComponent") end)
    if ok and list then
        for _, h in pairs(list) do add(h) end -- repli : tous les autres
    end
    return out
end

-- /!\ StatisticName est une FString, PAS une FName (voir l'entête). On passe donc
-- une chaîne Lua brute : UE4SS la convertit en FString pour la StrProperty.
local function ReadPoints(holder)
    local v
    local ok = pcall(function() v = holder:GetStatisticValue(STAT) end)
    if ok and type(v) == "number" then return v end
    return nil
end

-- Donne n points. Renvoie (holder, avant, apres) si ça a marché, sinon nil.
local function GivePoints(n)
    for _, h in ipairs(CandidateHolders()) do
        local ready = true
        pcall(function() ready = h:IsReady() end)
        if ready ~= false then
            local before = ReadPoints(h)
            if before then
                pcall(function() h:IncreaseStatisticBaseValue(STAT, n * 1.0) end)
                local after = ReadPoints(h)
                -- On ne valide que si la valeur a VRAIMENT bougé : c'est ce qui
                -- distingue le holder du template perks des autres holders.
                if after and after > before then return h, before, after end
            end
        end
    end
    return nil
end

RegisterConsoleCommandGlobalHandler("xp", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local a1 = p[1] and string.lower(p[1]) or nil

    if a1 == "status" then
        for _, h in ipairs(CandidateHolders()) do
            local v = ReadPoints(h)
            if v then
                cout(Ar, string.format("[xp] solde : %.0f point(s) d'Ætherfact.", v))
                return true
            end
        end
        cout(Ar, "[xp] holder de statistiques introuvable — es-tu bien en jeu ?")
        return true
    end

    local n = 1
    if a1 then
        n = tonumber(a1)
        if not n or n < 1 then
            cout(Ar, "[xp] usage : xp  |  xp <n>  |  xp status")
            return true
        end
        n = math.floor(n)
    end

    if not GetPawn() then
        cout(Ar, "[xp] joueur introuvable — es-tu bien en jeu (pas dans un menu) ?")
        return true
    end

    local h, before, after = GivePoints(n)
    if not h then
        cout(Ar, "[xp] échec : aucun holder n'a accepté d'incrémenter " .. STAT ..
                 ". Ouvre l'arbre de perks une fois puis réessaie.")
        return true
    end
    cout(Ar, string.format("[xp] +%d → %.0f point(s) d'Ætherfact (avant : %.0f).",
        n, after, before))
    return true
end)

log("Chargé. Console in-game (F10) : xp  |  xp <n>  |  xp status")
