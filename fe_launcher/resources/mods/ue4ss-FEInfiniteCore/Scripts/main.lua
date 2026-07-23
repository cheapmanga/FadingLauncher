-- ============================================================================
--  FADING ECHO — INFINITE CORE (déclencheur déterministe)
--
--  En UNE touche : donne un core À One (spawné DANS le joueur, pas à côté →
--  StartGrab immédiat, pas de temps de vol) puis, après un délai réglable
--  < 1 s, provoque une MORT DANS LE VIDE via TriggerInstantFallDeath.
--
--  Pourquoi ça vise le glitch (modèle confirmé reverse + dev) :
--   - StartGrab pose les 2 couches du core : (A) l'acteur physique lié à One,
--     (B) la charge élémentaire qui pilote l'UI + le prompt LB.
--   - La mort dans le vide force One en HUMAIN et reset les jauges, MAIS saute
--     l'étape KillGrabbedCore → la couche B reste. Résultat visé : humain +
--     core LB toujours affiché = "infinite core".
--   - Le délai grab→void est LE levier de constance (file de stats différée +
--     branches OnDeath sur "falling/human"). On le rend chiffré et réglable
--     au lieu de le jouer à l'œil.
--
--  ⚠ Non testé en jeu (machine sans le jeu). VOID_DELAY est à balayer.
--
--  Touche / console (F10) :
--   F7                    lance la séquence (grab + void après le délai)
--   icore                 idem
--   icore delay <ms>      règle le délai grab→void (défaut 500, borné < 1000)
--   icore type <t>        core donné : water|waste|fire|glitch (défaut water)
--   icore status          config courante
-- ============================================================================

local UEHelpers = require("UEHelpers")

local VOID_DELAY_MS = 1200         -- délai grab -> void (laisse l'absorption ~1s se finir)
local CORE_TYPE     = "water"      -- water|waste|fire|glitch
local SPAWN_IN_ME   = true         -- true = core spawné à ma position (grab instantané)

local BASE = "/Game/Game/Placeable/InteractiveObjects/PortableItem/"
local CORES = {
    water  = { path = BASE .. "BP_PortableItem_WaterBall.BP_PortableItem_WaterBall_C",           short = "BP_PortableItem_WaterBall_C",      label = "Water" },
    waste  = { path = BASE .. "BP_PortableItem_WasteBall.BP_PortableItem_WasteBall_C",           short = "BP_PortableItem_WasteBall_C",      label = "Waste" },
    fire   = { path = BASE .. "BP_PortableItem_LavaBall.BP_PortableItem_LavaBall_C",             short = "BP_PortableItem_LavaBall_C",       label = "Lava (feu)" },
    glitch = { path = BASE .. "BP_PortableItem_CorruptionBall.BP_PortableItem_CorruptionBall_C", short = "BP_PortableItem_CorruptionBall_C", label = "Corruption (glitch)" },
}

local function log(m) print("[InfCore] " .. tostring(m) .. "\n") end
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
            if c and c:IsValid() and isRealActor(c.Pawn) then return c.Pawn end
        end
    end
    local ok, p = pcall(UEHelpers.GetPlayerPawn)
    if ok and isRealActor(p) then return p end
    return nil
end

-- ---------------------------------------------------------------------------
--  Spawn du core + StartGrab
-- ---------------------------------------------------------------------------
local function ResolveCoreClass(e)
    local c = StaticFindObject(e.path)
    if c and c:IsValid() then return c end
    local inst = FindFirstOf(e.short)          -- fallback : classe d'une instance déjà chargée
    if inst and inst:IsValid() then
        local ok, k = pcall(function() return inst:GetClass() end)
        if ok and k and k:IsValid() then return k end
    end
    return nil
end

-- Renvoie (actor, nil) ou (nil, message).
local function SpawnCore(e, pawn)
    local world = UEHelpers.GetWorld()
    if not (world and world:IsValid()) then return nil, "world introuvable." end
    local GS  = StaticFindObject("/Script/Engine.Default__GameplayStatics")
    local KML = StaticFindObject("/Script/Engine.Default__KismetMathLibrary")
    if not (GS and GS:IsValid())  then return nil, "GameplayStatics introuvable." end
    if not (KML and KML:IsValid()) then return nil, "KismetMathLibrary introuvable." end
    local cls = ResolveCoreClass(e)
    if not (cls and cls:IsValid()) then
        return nil, "classe pas chargée (" .. e.short .. "). Approche-toi une fois d'un core "
                    .. e.label .. " pour la charger, puis réessaie."
    end

    local loc = pawn:K2_GetActorLocation()
    local pos
    if SPAWN_IN_ME then
        pos = { X = loc.X, Y = loc.Y, Z = loc.Z + 20.0 }             -- DANS le joueur
    else
        local fwd = pawn:GetActorForwardVector()
        pos = { X = loc.X + fwd.X * 120.0, Y = loc.Y + fwd.Y * 120.0, Z = loc.Z + 40.0 }
    end

    local xf
    local okT = pcall(function()
        xf = KML:MakeTransform(pos, { Pitch = 0.0, Yaw = 0.0, Roll = 0.0 }, { X = 1.0, Y = 1.0, Z = 1.0 })
    end)
    if not okT or not xf then return nil, "MakeTransform a échoué." end

    local actor
    local okS, errS = pcall(function()
        actor = GS:BeginDeferredActorSpawnFromClass(world, cls, xf, 1, nil, 0)   -- 1 = AlwaysSpawn
    end)
    if not okS then return nil, "spawn a levé : " .. tostring(errS) end
    if not (actor and actor:IsValid()) then return nil, "spawn a renvoyé un acteur nul." end

    for _, n in ipairs({ 3, 2 }) do   -- FinishSpawningActor : 3 args (UE5 récent) ou 2
        local okF = pcall(function()
            if n == 3 then GS:FinishSpawningActor(actor, xf, 0) else GS:FinishSpawningActor(actor, xf) end
        end)
        if okF then break end
    end
    return actor, nil
end

-- ---------------------------------------------------------------------------
--  Void instantané (le chemin qui saute KillGrabbedCore)
-- ---------------------------------------------------------------------------
local function TriggerVoid(pawn)
    local comp
    pcall(function() comp = pawn.BP_DeathBehaviour end)
    if not (comp and comp:IsValid()) then return false, "BP_DeathBehaviour introuvable." end
    local ok, err = pcall(function() comp:TriggerInstantFallDeath() end)
    if not ok then return false, "TriggerInstantFallDeath a levé : " .. tostring(err) end
    return true
end

-- ---------------------------------------------------------------------------
--  Séquence complète : grab -> (délai) -> void
-- ---------------------------------------------------------------------------
local running = false

local function RunSequence(Ar)
    if running then cout(Ar, "[icore] séquence déjà en cours."); return end
    local e = CORES[CORE_TYPE]
    if not e then cout(Ar, "[icore] type inconnu : " .. tostring(CORE_TYPE)); return end
    local pawn = GetPawn()
    if not pawn then cout(Ar, "[icore] joueur introuvable."); return end

    running = true
    ExecuteInGameThread(function()
        local actor, err = SpawnCore(e, pawn)
        if not actor then cout(Ar, "[icore] " .. tostring(err)); running = false; return end
        pcall(function() pawn:StartGrab(actor) end)
        cout(Ar, string.format("[icore] core %s donné — void dans %d ms.", e.label, VOID_DELAY_MS))
    end)

    -- délai one-shot puis void (return true = ne se répète pas)
    LoopAsync(VOID_DELAY_MS, function()
        ExecuteInGameThread(function()
            local p = GetPawn()
            if p then
                local ok, verr = TriggerVoid(p)
                if ok then cout(Ar, "[icore] void déclenché. Regarde le respawn : humain + core LB ?")
                else cout(Ar, "[icore] void raté : " .. tostring(verr)) end
            else
                cout(Ar, "[icore] joueur introuvable au moment du void.")
            end
        end)
        running = false
        return true
    end)
end

-- ---------------------------------------------------------------------------
--  VOID SEUL (recommandé) : tu absorbes un core toi-même sur un vrai
--  générateur (instantané), tu tiens le core en forme eau (prompt LB), PUIS
--  tu appuies -> void immédiat. Pas de spawn, pas de souci d'absorption.
-- ---------------------------------------------------------------------------
local function VoidNow(Ar)
    ExecuteInGameThread(function()
        local pawn = GetPawn()
        if not pawn then cout(Ar, "[ivoid] joueur introuvable."); return end
        local ok, err = TriggerVoid(pawn)
        if ok then cout(Ar, "[ivoid] void déclenché. Respawn : humain + core LB ?")
        else cout(Ar, "[ivoid] raté : " .. tostring(err)) end
    end)
end

-- ---------------------------------------------------------------------------
--  Entrées
-- ---------------------------------------------------------------------------
RegisterKeyBind(Key.F8, function() VoidNow(nil) end)          -- void seul (recommandé)
RegisterKeyBind(Key.F7, function() RunSequence(nil) end)      -- séquence auto (spawn+void)

RegisterConsoleCommandGlobalHandler("ivoid", function(FullCommand, Parameters, Ar)
    VoidNow(Ar)
    return true
end)

RegisterConsoleCommandGlobalHandler("icore", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local sub = (p[1] and string.lower(p[1])) or "run"

    if sub == "delay" then
        local n = tonumber(p[2])
        if not n then cout(Ar, "[icore] usage : icore delay <ms>"); return true end
        if n < 0 then n = 0 end
        if n > 5000 then n = 5000 end
        VOID_DELAY_MS = n
        cout(Ar, "[icore] délai grab->void = " .. VOID_DELAY_MS .. " ms.")
        return true
    end

    if sub == "type" then
        local t = p[2] and string.lower(p[2])
        if not (t and CORES[t]) then cout(Ar, "[icore] usage : icore type water|waste|fire|glitch"); return true end
        CORE_TYPE = t
        cout(Ar, "[icore] core donné = " .. CORES[t].label .. ".")
        return true
    end

    -- 'near' = spawn à côté (absorption plus longue = fenêtre de void plus large,
    -- plus tolérante) ; 'in' = spawn dans le joueur (absorption plus courte).
    if sub == "spawn" then
        local m = p[2] and string.lower(p[2])
        if m == "in" then SPAWN_IN_ME = true
        elseif m == "near" then SPAWN_IN_ME = false
        else cout(Ar, "[icore] usage : icore spawn in|near"); return true end
        cout(Ar, "[icore] spawn = " .. (SPAWN_IN_ME and "dans-moi (absorption courte)" or "à côté (fenêtre large)") .. ".")
        return true
    end

    if sub == "status" then
        cout(Ar, string.format("[icore] type=%s delay=%dms spawn=%s",
            CORE_TYPE, VOID_DELAY_MS, SPAWN_IN_ME and "dans-moi" or "devant"))
        return true
    end

    RunSequence(Ar)
    return true
end)

log("Chargé. F8 = VOID SEUL (tiens un core puis appuie — recommandé). F7 = séquence auto (spawn+void). Console : ivoid | icore | icore delay/type/spawn/status.")
