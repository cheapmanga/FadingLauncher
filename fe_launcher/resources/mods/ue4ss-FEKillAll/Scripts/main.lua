-- ============================================================================
--  FE KILL ALL  —  contournement de KillAllEnemies
--
--  Pourquoi ce mod : UYgroCheatManager_C::KillAllEnemies() s'appelle sans
--  erreur mais ne tue pas les ennemis du niveau. Son tableau interne
--  `Enemies` semble alimenté par le systeme de squad de debug, pas par les
--  ennemis places dans la map.
--
--  Ici on ne passe pas par le CheatManager : on enumere les ennemis vivants
--  et on declenche leur mort via leur propre composant BP_DeathBehaviour,
--  qui herite de UDeathBehaviorComponent.
--
--  Commandes (console du jeu, touche ²) :
--     killall          tue tous les ennemis charges
--     killall count    compte les ennemis sans rien tuer
--
--  ⚠️ PIEGE `Ar` (documente dans FEDevMenu, avait crashe la v1) :
--  le FOutputDevice n'est valide QUE dans le corps synchrone du handler.
--  Jamais dans du code differe -> ici tout est synchrone, donc Ar est sur.
-- ============================================================================

local ENEMY_CLASS = "BP_EnemyBase_C"

local function log(m) print("[KillAll] " .. tostring(m) .. "\n") end

local function say(Ar, m)
    log(m)
    if Ar then pcall(function() Ar:Log("[KillAll] " .. tostring(m)) end) end
end

-- Un Class Default Object est un gabarit, pas un ennemi vivant.
local function isLive(o)
    if not (o and o:IsValid()) then return false end
    local fn = ""
    pcall(function() fn = o:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function listEnemies()
    local out = {}
    local ok, all = pcall(function() return FindAllOf(ENEMY_CLASS) end)
    if not ok or not all then return out end
    for _, e in pairs(all) do
        if isLive(e) then table.insert(out, e) end
    end
    return out
end

-- Declenche la mort d'un ennemi. Renvoie (true, methode) ou (false, raison).
local function killOne(enemy)
    local dc = nil
    pcall(function() dc = enemy.BP_DeathBehaviour end)
    if not (dc and dc:IsValid()) then
        return false, "pas de BP_DeathBehaviour"
    end

    -- 1) Voie propre : héritée de UDeathBehaviorComponent, BlueprintCallable.
    local ok = pcall(function() dc:NotifyHealthToZero() end)
    if ok then return true, "NotifyHealthToZero" end

    -- 2) Repli : fonction de la Blueprint. Nom avec ESPACE -> syntaxe crochets.
    ok = pcall(function() dc["Die Common"](dc) end)
    if ok then return true, "Die Common" end

    -- 3) Dernier recours : le chemin "chute mortelle".
    ok = pcall(function() dc:TriggerInstantFallDeath() end)
    if ok then return true, "TriggerInstantFallDeath" end

    return false, "les 3 methodes ont echoue"
end

RegisterConsoleCommandHandler("killall", function(FullCommand, Parameters, Ar)
    local mode = (Parameters and Parameters[1] or ""):lower()
    local enemies = listEnemies()

    if #enemies == 0 then
        say(Ar, "aucun ennemi charge. Es-tu bien dans une zone avec des ennemis vivants ?")
        return true
    end

    if mode == "count" then
        say(Ar, #enemies .. " ennemi(s) charge(s)")
        return true
    end

    local killed, failed, how = 0, 0, {}
    for _, e in ipairs(enemies) do
        local ok, method = killOne(e)
        if ok then
            killed = killed + 1
            how[method] = (how[method] or 0) + 1
        else
            failed = failed + 1
            log("  echec : " .. tostring(method))
        end
    end

    say(Ar, killed .. " tue(s), " .. failed .. " echec(s) sur " .. #enemies)
    for m, n in pairs(how) do say(Ar, "  via " .. m .. " : " .. n) end
    say(Ar, "Verifie A L'ECRAN : un appel sans erreur ne prouve pas la mort.")
    return true
end)

log("charge. Commandes : killall | killall count")
