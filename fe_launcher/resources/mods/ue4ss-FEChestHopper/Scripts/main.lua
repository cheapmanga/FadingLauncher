-- ============================================================================
--  FADING ECHO — CHEST HOPPER
--
--  Commande console (F10) :
--     chest              -> téléporte au coffre suivant (1er appel = le plus proche)
--     chest reset        -> reconstruit la tournée depuis ta position actuelle
--     chest prev         -> revient au coffre précédent
--     chest <n>          -> saute directement au n-ième coffre de la tournée
--     chest list         -> liste les coffres trouvés + leur distance
--
--  Principe : au 1er 'chest', on collecte tous les coffres CHARGÉS, on les trie
--  par distance au joueur, et on parcourt cette liste figée. Elle est refaite
--  automatiquement si le nombre de coffres change (streaming de niveau) ou via
--  'chest reset'.
--
--  ⚠️ Le tri est figé au moment de la construction : c'est voulu. Un tri
--  recalculé à chaque saut renverrait sans cesse au coffre d'où l'on vient
--  (distance 0), on ne visiterait jamais toute la zone.
--
--  ⚠️ Seuls les coffres dont le sous-niveau est CHARGÉ sont visibles par
--  FindAllOf. Les coffres d'une zone non streamée n'existent pas encore côté
--  moteur — aucun mod ne peut les atteindre. 'chest list' montre ce qui est
--  réellement trouvé à l'instant T.
--
--  Classes : /Game/Game/Placeable/InteractiveObjects/Chest/
-- ============================================================================

local UEHelpers = require("UEHelpers")

local function log(m) print("[ChestHopper] " .. tostring(m) .. "\n") end
local function cout(Ar, m)
    pcall(function() if Ar then Ar:Log(m) end end)
    log(m)
end

-- Hauteur ajoutée à la destination : on se pose AU-DESSUS du coffre plutôt que
-- dedans (sinon la capsule du joueur peut se coincer dans la collision).
local Z_OFFSET = 150.0

local CHEST_CLASSES = {
    "BP_Chest_Small_C",
    "BP_Chest_Medium_C",
    "BP_Chest_Big_C",
    "BP_Chest_Special_LevelUp_C",
    "BP_Chest_ALIENWARE_C",
}

-- Libellé court pour l'affichage
local function PrettyClass(fullname)
    local n = tostring(fullname or "")
    for _, cls in ipairs(CHEST_CLASSES) do
        if string.find(n, cls, 1, true) then
            return (string.gsub(string.gsub(cls, "^BP_Chest_", ""), "_C$", ""))
        end
    end
    return "Chest"
end

-- ---------------------------------------------------------------------------
--  Helpers acteurs / joueur  (mêmes garde-fous que les autres mods FE)
-- ---------------------------------------------------------------------------
local function isRealActor(a)
    if not (a and a:IsValid()) then return false end
    local fn = ""
    pcall(function() fn = a:GetFullName() end)
    -- On exclut les Class Default Objects : ce sont des gabarits, pas des
    -- acteurs posés dans le niveau (ils ont une position bidon, souvent 0,0,0).
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
        for _, a in pairs(list) do
            if isRealActor(a) then return a end
        end
    end
    return nil
end

local function ProbeLocation(actor)
    local loc
    pcall(function() loc = actor:K2_GetActorLocation() end)
    if loc and loc.X then return loc end
    return nil
end

local function Dist3(a, b)
    local dx, dy, dz = a.X - b.X, a.Y - b.Y, a.Z - b.Z
    return math.sqrt(dx * dx + dy * dy + dz * dz)
end

-- ---------------------------------------------------------------------------
--  Collecte
-- ---------------------------------------------------------------------------
local function CollectChests()
    local found, seen = {}, {}
    for _, cls in ipairs(CHEST_CLASSES) do
        local ok, list = pcall(function() return FindAllOf(cls) end)
        if ok and list then
            for _, a in pairs(list) do
                if isRealActor(a) then
                    local nok, fn = pcall(function() return a:GetFullName() end)
                    if nok and fn and not seen[fn] then
                        seen[fn] = true
                        local loc = ProbeLocation(a)
                        if loc then
                            table.insert(found, { actor = a, loc = loc, name = fn, label = PrettyClass(fn) })
                        end
                    end
                end
            end
        end
    end
    return found
end

-- ---------------------------------------------------------------------------
--  État de la tournée
-- ---------------------------------------------------------------------------
local tour = {}   -- liste triée par distance, figée
local idx = 0     -- index du dernier coffre visité (0 = pas encore parti)

local function BuildTour(Ar)
    local pawn = GetPawn()
    if not pawn then return false, "joueur introuvable" end
    local ppos = ProbeLocation(pawn)
    if not ppos then return false, "position du joueur illisible" end

    local chests = CollectChests()
    if #chests == 0 then
        return false, "aucun coffre chargé (zone pas encore streamée ?) — essaie 'chest list'"
    end

    for _, c in ipairs(chests) do c.dist = Dist3(ppos, c.loc) end
    table.sort(chests, function(a, b) return a.dist < b.dist end)

    tour, idx = chests, 0
    return true, nil
end

-- La tournée est périmée si des coffres ont été chargés/déchargés depuis,
-- ou si un acteur mémorisé n'est plus valide (changement de zone).
local function TourIsStale()
    if #tour == 0 then return true end
    if #CollectChests() ~= #tour then return true end
    for _, c in ipairs(tour) do
        if not (c.actor and c.actor:IsValid()) then return true end
    end
    return false
end

local function TeleportTo(entry)
    local pawn = GetPawn()
    if not pawn then return false, "joueur introuvable" end
    -- On relit la position à chaud : un coffre peut avoir bougé (plateforme,
    -- ascenseur) depuis la construction de la tournée.
    local loc = ProbeLocation(entry.actor) or entry.loc
    local dest = { X = loc.X, Y = loc.Y, Z = loc.Z + Z_OFFSET }
    local ok = pcall(function() pawn:K2_SetActorLocation(dest, false, {}, true) end)
    return ok, (not ok) and "K2_SetActorLocation a échoué" or nil
end

local function GoTo(Ar, n)
    if n < 1 or n > #tour then
        cout(Ar, "[chest] index hors tournée (1.." .. #tour .. ").")
        return true
    end
    local e = tour[n]
    local ok, err = TeleportTo(e)
    if not ok then
        cout(Ar, "[chest] " .. tostring(err))
        return true
    end
    idx = n
    cout(Ar, string.format("[chest] %d/%d — %s (%.0f m du point de départ)",
        n, #tour, e.label, (e.dist or 0) / 100.0))
    return true
end

-- ---------------------------------------------------------------------------
--  Commande console
-- ---------------------------------------------------------------------------
RegisterConsoleCommandGlobalHandler("chest", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local key = (p[1] and string.lower(p[1])) or ""

    if key == "list" then
        local chests = CollectChests()
        if #chests == 0 then
            cout(Ar, "[chest] aucun coffre chargé actuellement.")
            return true
        end
        local pawn = GetPawn()
        local ppos = pawn and ProbeLocation(pawn) or nil
        if ppos then
            for _, c in ipairs(chests) do c.dist = Dist3(ppos, c.loc) end
            table.sort(chests, function(a, b) return a.dist < b.dist end)
        end
        cout(Ar, "[chest] " .. #chests .. " coffre(s) chargé(s) :")
        for i, c in ipairs(chests) do
            cout(Ar, string.format("   %2d. %-12s %6.0f m", i, c.label, (c.dist or 0) / 100.0))
        end
        return true
    end

    if key == "reset" or key == "again" or key == "restart" then
        local ok, err = BuildTour(Ar)
        if not ok then cout(Ar, "[chest] " .. tostring(err)); return true end
        cout(Ar, "[chest] tournée reconstruite : " .. #tour .. " coffre(s). Tape 'chest'.")
        return true
    end

    if key == "prev" or key == "back" then
        if #tour == 0 then cout(Ar, "[chest] pas de tournée en cours."); return true end
        return GoTo(Ar, idx - 1 >= 1 and idx - 1 or #tour)
    end

    if key == "help" or key == "?" then
        cout(Ar, "[chest] chest | chest reset | chest prev | chest <n> | chest list")
        return true
    end

    -- 'chest <n>'
    local n = tonumber(key)
    if n then
        if #tour == 0 then
            local ok, err = BuildTour(Ar)
            if not ok then cout(Ar, "[chest] " .. tostring(err)); return true end
        end
        return GoTo(Ar, math.floor(n))
    end

    if key ~= "" then
        cout(Ar, "[chest] argument inconnu : " .. key .. "  (essaie : chest help)")
        return true
    end

    -- 'chest' tout court : construire si besoin, puis avancer
    if TourIsStale() then
        local ok, err = BuildTour(Ar)
        if not ok then cout(Ar, "[chest] " .. tostring(err)); return true end
        cout(Ar, "[chest] tournée : " .. #tour .. " coffre(s) trouvé(s).")
    end

    local nxt = idx + 1
    if nxt > #tour then
        nxt = 1
        cout(Ar, "[chest] fin de la tournée — on repart du plus proche.")
    end
    return GoTo(Ar, nxt)
end)

log("Chargé. Tape 'chest' dans la console (F10). 'chest help' pour les options.")
