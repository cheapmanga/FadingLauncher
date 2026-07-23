-- ============================================================================
--  FADING ECHO — DEV TOOLKIT  (v4)
--
--  Tout ce qui a été trouvé de "fait pour les devs" dans le jeu, en un mod.
--
--    devmenu [extra|off|status]   menu pause dev (DEBUG / LOAD / CHECKPOINT…)
--    cheat   list | <alias> [arg] les 23 fonctions du YgroCheatManager
--    cam     [spawn|despawn|off]  caméra libre (moteur) et spectateur (jeu)
--    devmap  list | <nom>         charge une map de dev
--
--  Sorties détaillées : FENÊTRE DE CONSOLE UE4SS.
--  Console du jeu : touche ²  (AZERTY)
--
--  ---------------------------------------------------------------------------
--  CE QUI EST VALIDÉ EN JEU (21/07/2026, build 1.0.27900)
--    - devmenu : DEBUG / LOAD / CHECKPOINT apparaissent
--    - EnableCheats fonctionne (Fly répond "you feel much lighter")
--    - écrire une propriété au nom contenant une espace : w["Build Config"] = 0
--  CE QUI NE L'EST PAS : cheat (23 fn), cam, devmap. Tout est protégé par pcall
--  et rapporte son échec, mais un appel peut avoir un effet inattendu.
--  ---------------------------------------------------------------------------
--  ⚠️ PIÈGE `Ar` — a crashé la v1, NE JAMAIS REFAIRE
--  Le FOutputDevice `Ar` du handler n'est valide QUE dans le corps SYNCHRONE.
--  Dans ExecuteInGameThread / LoopAsync c'est un pointeur mort ->
--  EXCEPTION_ACCESS_VIOLATION lecture 0x8 (FOutputDevice::Serialize).
--  pcall NE PROTÈGE PAS (violation native, pas erreur Lua).
--  => dans tout code différé : print() uniquement.
-- ============================================================================

local UEHelpers = require("UEHelpers")

local MENU_CLASS = "WBP_PauseMenu_Main_C"
local PROP       = "Build Config"   -- ⚠️ nom avec ESPACE
local BUILD_DEBUG, BUILD_SHIPPING = 0, 1
local VIS_VISIBLE, VIS_COLLAPSED   = 0, 1

local function log(m) print("[FEDev] " .. tostring(m) .. "\n") end
local function say(Ar, m)           -- corps synchrone du handler UNIQUEMENT
    log(m)
    if Ar then pcall(function() Ar:Log("[FEDev] " .. tostring(m)) end) end
end

-- ---------------------------------------------------------------------------
--  Helpers communs
-- ---------------------------------------------------------------------------
-- Nom complet d'un objet, sans jamais planter (helper absent de ce mod avant le
-- 22/07 : ExitFreeCam l'utilisait, d'ou "attempt to call a nil value (global 'Name')").
local function Name(o)
    if not o then return "(nil)" end
    local n = "?"
    pcall(function() n = o:GetFullName() end)
    return n
end

local function isRealObject(o)
    if not (o and o:IsValid()) then return false end
    local fn = ""
    pcall(function() fn = o:GetFullName() end)
    -- Les Class Default Objects sont des gabarits, pas l'objet vivant.
    return not string.find(fn, "Default__", 1, true)
end

local function GetPC()
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do if isRealObject(c) then return c end end
    end
    local ok, pc = pcall(UEHelpers.GetPlayerController)
    if ok and isRealObject(pc) then return pc end
    return nil
end

local function GetWorld()
    local ok, w = pcall(UEHelpers.GetWorld)
    if ok and w and w:IsValid() then return w end
    local pc = GetPC()
    if pc then
        local w2
        pcall(function() w2 = pc:GetWorld() end)
        if w2 and w2:IsValid() then return w2 end
    end
    return nil
end

local function KSL()   -- UKismetSystemLibrary (ExecuteConsoleCommand)
    local ok, o = pcall(UEHelpers.GetKismetSystemLibrary)
    if ok and o and o:IsValid() then return o end
    return StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
end

local function GPS()   -- UGameplayStatics (OpenLevel, GetGameMode)
    local ok, o = pcall(UEHelpers.GetGameplayStatics)
    if ok and o and o:IsValid() then return o end
    return StaticFindObject("/Script/Engine.Default__GameplayStatics")
end

-- Exécute une commande console moteur. Renvoie (ok, err).
-- ⚠️ SpecificPlayer laissé à nil VOLONTAIREMENT : une fois ToggleDebugCamera actif,
-- le PlayerController est remplacé par un ADebugCameraController. Lui passer le PC
-- courant visait alors le mauvais contrôleur et la commande n'arrivait plus —
-- c'est ce qui empêchait de RESSORTIR de la caméra. nil = premier joueur local.
local function Console(cmd)
    local k, w, pc = KSL(), GetWorld(), GetPC()
    if not (k and w) then return false, "KismetSystemLibrary ou World introuvable" end
    -- SpecificPlayer : passer le PC courant. (Le mettre à nil a fait échouer la
    -- commande en v5 — l'argument objet ne tolère pas nil ici.)
    local ok, err = pcall(function() k:ExecuteConsoleCommand(w, cmd, pc) end)
    return ok, (not ok) and tostring(err) or nil
end

-- CheatCall est défini plus bas, après GetCheatManager (dépendance d'ordre).
local CheatCall
-- ⚠️ ExitFreeCam (plus haut que la section cheats) utilise GetPawn : sans cette
-- déclaration anticipée, Lua la compile en globale nil.
local GetPawn

-- ---------------------------------------------------------------------------
--  CHEATS : catalogue du YgroCheatManager
--  arg = nil | "int" | "text" | "str" | "actor"
--  ⚠️ 3 noms contiennent une ESPACE -> cm["Nom"](cm)
--  ⚠️ Les fautes de frappe sont CELLES DU JEU : ToggleInifiniteMana,
--     CharaterOptimization. Les corriger ferait échouer l'appel.
-- ---------------------------------------------------------------------------
local CHEATS = {
    { "abilities",  "UnlockAllAbilities",       nil,     "débloque toutes les capacités" },
    { "health",     "ToggleInfiniteHealth",     nil,     "vie infinie (bascule)" },
    { "mana",       "ToggleInifiniteMana",      nil,     "mana infinie (bascule)" },
    { "aether",     "RefillAether",             nil,     "recharge l'Aether" },
    { "xp",         "AddMaxXP",                 nil,     "ajoute le max d'XP" },
    { "kill",       "KillAllEnemies",           nil,     "tue tous les ennemis" },
    { "glitchtp",   "ToggleGlitchTP",           nil,     "téléportation glitch (bascule)" },
    { "combat",     "ActivateCombatCheat",      nil,     "cheat de combat" },
    { "perf",       "ActivatePerfMode",         nil,     "mode performance" },
    { "debugcam",   "ToggleUseDebugCamera",     nil,     "caméra debug côté jeu (bascule)" },
    { "spellaim",   "ToggleShowSpellAim",       nil,     "affiche la visée des sorts" },
    { "viewrot",    "ViewRotToPawnRot",         nil,     "aligne la vue sur le pawn" },
    { "squad",      "ToggleSquadSpawn",         nil,     "spawn d'escouade (bascule)" },
    { "squadreset", "ResetSquad",               nil,     "réinitialise l'escouade" },
    { "squadget",   "GetCurrentSquad",          nil,     "lit l'escouade courante" },
    { "enemyint",   "ToggleEnemyInterrupt",     nil,     "interruption ennemie (bascule)" },
    { "playerint",  "TogglePlayerInterrupt",    nil,     "interruption joueur (bascule)" },
    { "hud",        "Toggle HUD",               nil,     "affiche/masque le HUD" },
    { "waterform",  "Unlock Water Form",        nil,     "débloque la Water Form" },
    { "dialogue",   "Change Dialogue Style",    "int",   "style de dialogue — ex: cheat dialogue 1" },
    { "checkpoint", "SpawnAtCheckpoint",        "text",  "TP checkpoint — ex: cheat checkpoint VolcanoMid" },
    { "optimize",   "CharaterOptimization",     "actor", "optimise un acteur (défaut : le joueur)" },
    { "call",       "CallCheatManagerFunction", "str",   "dispatcher interne du jeu" },
}

-- ---------------------------------------------------------------------------
--  MAPS DE DEV réellement packagées (vérifié dans l'index .utoc de la build)
--  Les 4 autres niveaux "Only" (Quarry/Volcano/Wonder/Bastion) et NewGym /
--  ArenaDifficultyTests sont ABSENTS : ne pas les proposer, ils renvoient au menu.
-- ---------------------------------------------------------------------------
local DEVMAPS = {
    { "tree",    "YGRO_TreeOnly_P",   "Big Tree isolé — micro LD, sans passe visuelle" },
    { "grid",    "GridSandBox",       "bac à sable grille + mares de fluides" },
    { "debug",   "YGRO_DEBUG",        "map de debug" },
    { "struct",  "TestingStructures", "structures de test (PreProd)" },
    { "light",   "LD_LightingProto",  "prototype d'éclairage" },
    { "game",    "YGRO_P",            "le jeu (retour à la map principale)" },
}

-- ---------------------------------------------------------------------------
--  Verrous du menu pause
-- ---------------------------------------------------------------------------
local function GetCheatManager()
    local pc = GetPC()
    if pc then
        local cm
        pcall(function() cm = pc.CheatManager end)
        if cm and cm:IsValid() then return cm end
    end
    local list = FindAllOf("YgroCheatManager_C")
    if list then
        for _, c in pairs(list) do if isRealObject(c) then return c end end
    end
    return nil
end

-- Appelle une fonction du CheatManager par son nom. Renvoie (ok, err).
-- Voie PRIVILÉGIÉE pour les cheats moteur (EnableDebugCamera…) : l'objet est
-- résolu, aucun marshalling de chaîne, aucune dépendance à la console.
CheatCall = function(name, ...)
    local cm = GetCheatManager()
    if not cm then return false, "CheatManager absent" end
    local args = { ... }
    local ok, err = pcall(function() cm[name](cm, table.unpack(args)) end)
    return ok, (not ok) and tostring(err) or nil
end

-- ---------------------------------------------------------------------------
--  Caméra libre du moteur : SORTIR demande un autre objet que pour ENTRER.
--
--  EnableDebugCamera remplace le PlayerController par un ADebugCameraController,
--  qui possède SON PROPRE CheatManager. Or UCheatManager::DisableDebugCamera ne
--  fait quelque chose que si son outer EST ce contrôleur. Appeler DisableDebugCamera
--  sur le CheatManager d'origine ne produit donc RIEN — c'est ce qui bloquait
--  dans la freecam (constaté en jeu le 21/07).
--  => pour sortir : viser le CheatManager du ADebugCameraController.
-- ---------------------------------------------------------------------------
local function GetDebugCameraController()
    local list = FindAllOf("DebugCameraController")
    if list then
        for _, c in pairs(list) do if isRealObject(c) then return c end end
    end
    return nil
end

-- UCheatManager::DisableDebugCamera caste son OUTER en ADebugCameraController.
-- Il faut donc l'appeler sur le CheatManager DU CONTRÔLEUR DE DEBUG, et celui-ci
-- n'existe pas d'office : un contrôleur spawné ne reçoit pas AddCheats.
-- On le fabrique avec EnableCheats (execEnableCheats confirmé sur APlayerController ;
-- execSwitchController et execAddCheats, eux, n'existent PAS -> pas d'autre voie).
local function ExitFreeCam()
    local dcc = GetDebugCameraController()
    if not dcc then return true, "aucun DebugCameraController (deja sorti)" end
    log("  DCC trouve : " .. Name(dcc))

    -- 1) DisableDebugCamera sur le CheatManager DU DCC (il caste son outer).
    local dcm
    pcall(function() dcm = dcc.CheatManager end)
    if not (dcm and dcm:IsValid()) then
        log("  CheatManager du DCC absent -> EnableCheats() dessus")
        pcall(function() dcc:EnableCheats() end)
        pcall(function() dcm = dcc.CheatManager end)
    end
    if dcm and dcm:IsValid() then
        pcall(function() dcm:DisableDebugCamera() end)
        if not GetDebugCameraController() then return true, "DisableDebugCamera (CheatManager du DCC)" end
        pcall(function() dcm:ToggleDebugCamera() end)
        if not GetDebugCameraController() then return true, "ToggleDebugCamera (CheatManager du DCC)" end
    end

    -- 2) CheatManager du joueur, puis console.
    pcall(function() local cm = GetCheatManager(); if cm then cm:DisableDebugCamera() end end)
    if not GetDebugCameraController() then return true, "CheatManager du joueur" end
    Console("DisableDebugCamera")
    if not GetDebugCameraController() then return true, "console" end

    -- 3) RECUPERATION DIRECTE : rendre la possession et la vue au controleur
    --    d'origine. ⚠️ NE PAS considerer cela comme un succes : le DCC garde le
    --    UPlayer (donc l'entree), et UPlayer::SwitchController n'a PAS de thunk
    --    exec. Tant que le DCC existe, on est encore prisonnier (constate 22/07).
    local orig
    pcall(function() orig = dcc.OriginalControllerRef end)
    local pawn = GetPawn()
    if orig and orig:IsValid() and pawn then
        pcall(function() orig:Possess(pawn) end)
        pcall(function() orig:SetViewTargetWithBlend(pawn, 0.0, 0, 0.0, false) end)
        log("  vue rendue au controleur d'origine")
        if not GetDebugCameraController() then return true, "possession + vue restaurees" end
        log("  le DCC subsiste -> destruction")
    end

    -- 4) DESTRUCTION DU DebugCameraController.
    --    C'est la seule voie qui reste : ni DisableDebugCamera (le CheatManager du
    --    DCC ne peut pas etre cree, le mod CheatManagerEnabler intercepte
    --    EnableCheats), ni SwitchController (pas expose).
    if pcall(function() dcc:K2_DestroyActor() end) then
        log("  DCC detruit")
        local pc = GetPC()
        if pc and pawn then
            pcall(function() pc:Possess(pawn) end)
            pcall(function() pc:SetViewTargetWithBlend(pawn, 0.0, 0, 0.0, false) end)
        end
        if not GetDebugCameraController() then return true, "DebugCameraController detruit" end
        return true, "DCC detruit (une instance subsiste, relance si besoin)"
    end

    return false, "aucune voie n'a fonctionne - utilise 'devmap game' pour recharger"
end

local function EnsureCheatManager()
    if GetCheatManager() then return true, "déjà actif" end
    local pc = GetPC()
    if not pc then return false, "PlayerController introuvable" end
    if not pcall(function() pc:EnableCheats() end) then return false, "EnableCheats() a échoué" end
    if not GetCheatManager() then return false, "EnableCheats() appelé mais CheatManager nul" end
    return true, "activé"
end

-- Verrou 1 du menu : Shipping -> Debug.
local function SetBuildConfig(value)
    local list = FindAllOf(MENU_CLASS)
    if not list then return 0, 0 end
    local ok, seen = 0, 0
    for _, w in pairs(list) do
        if isRealObject(w) then
            seen = seen + 1
            if pcall(function() w[PROP] = value end) then ok = ok + 1 end
        end
    end
    return ok, seen
end

-- Boutons SANS binding : masqués par du code impératif au Construct. Rien ne les
-- resurveille -> forcer leur Visibility suffit.
local EXTRA_BUTTONS = { "Button_LoadLevel", "Button_Save", "Button_Restart", "Button_LastCheckpoint" }

local function SetExtraButtons(vis)
    local list = FindAllOf(MENU_CLASS)
    if not list then return 0 end
    local n = 0
    for _, w in pairs(list) do
        if isRealObject(w) then
            for _, bn in ipairs(EXTRA_BUTTONS) do
                pcall(function()
                    local b = w[bn]
                    if b and b:IsValid() then b:SetVisibility(vis); n = n + 1 end
                end)
            end
        end
    end
    return n
end

-- ---------------------------------------------------------------------------
--  Cheats : invocation
-- ---------------------------------------------------------------------------
GetPawn = function()
    local pc = GetPC()
    if pc then
        local pk
        pcall(function() pk = pc.Pawn end)
        if isRealObject(pk) then return pk end
    end
    local list = FindAllOf("BP_CoreYgroCharacter_C")
    if list then
        for _, a in pairs(list) do if isRealObject(a) then return a end end
    end
    return nil
end

local function InvokeCheat(entry, rawArg)
    local cm = GetCheatManager()
    if not cm then return false, "CheatManager absent — lance 'devmenu' d'abord" end
    local name, kind = entry[2], entry[3]

    -- ⚠️ NE PAS tester type(fn) == "function" : UE4SS n'expose PAS les UFUNCTION
    -- comme des functions Lua mais comme un userdata appelable. Ce test rejetait
    -- les 23 appels (diagnostic "0/23" du 21/07) alors que l'objet était le bon.
    -- On appelle directement et on laisse pcall rapporter l'échec réel.
    local function call(...)
        local args = { ... }
        if string.find(name, " ", 1, true) then
            return cm[name](cm, table.unpack(args))   -- nom à espace : indexation
        end
        return cm[name](cm, table.unpack(args))
    end

    local ok, err
    if kind == nil then
        ok, err = pcall(function() call() end)
    elseif kind == "int" then
        local n = tonumber(rawArg)
        if not n then return false, "attend un nombre entier" end
        ok, err = pcall(function() call(math.floor(n)) end)
    elseif kind == "str" then
        -- StrProperty = FString : marshalling direct depuis une chaîne Lua, sans risque.
        if not rawArg or rawArg == "" then return false, "attend un texte en argument" end
        ok, err = pcall(function() call(rawArg) end)
    elseif kind == "text" then
        -- ⚠️ TextProperty = FText. Même famille de conversion que le FName qui a
        -- crashé le jeu (push_nameproperty, AV 0x70) ; push_textproperty n'est PAS
        -- vérifié sur cette build et pcall ne protégerait pas d'une AV native.
        -- On exige donc un 'force' explicite.
        if not rawArg or rawArg == "" then return false, "attend un texte en argument" end
        local forced, rest = rawArg:match("^force%s+(.*)$"), nil
        if not forced then
            return false, "paramètre FText NON VÉRIFIÉ sur cette build (risque de crash comme OpenLevel).\n"
                .. "         Sauvegarde, puis : cheat " .. entry[1] .. " force <valeur>"
        end
        rest = forced
        if rest == "" then return false, "il manque la valeur après 'force'" end
        ok, err = pcall(function() call(rest) end)
    elseif kind == "actor" then
        local t = GetPawn()
        if not t then return false, "joueur introuvable" end
        ok, err = pcall(function() call(t) end)
    end
    if not ok then return false, "échec : " .. tostring(err) end
    return true, "OK"
end

local function FindEntry(list, key, idx)
    key = string.lower(key or "")
    if key == "" then return nil end
    for _, e in ipairs(list) do if string.lower(e[1]) == key then return e end end
    local flat = string.gsub(key, "%s", "")
    for _, e in ipairs(list) do
        if string.lower(string.gsub(e[idx or 2], "%s", "")) == flat then return e end
    end
    return nil
end

-- ---------------------------------------------------------------------------
--  Caméra : spectateur du jeu (AYgroGameMode) — thunks exec confirmés au PDB
-- ---------------------------------------------------------------------------
local function GameModeCamera(spawn)
    local g, w = GPS(), GetWorld()
    if not (g and w) then return false, "GameplayStatics ou World introuvable" end
    local gm
    pcall(function() gm = g:GetGameMode(w) end)
    if not (gm and gm:IsValid()) then return false, "GameMode introuvable" end
    local fname = spawn and "SpawnDebugCamera" or "DespawnDebugCamera"
    local ok, err = pcall(function() gm[fname](gm) end)
    if not ok then return false, fname .. " : " .. tostring(err) end
    return true, fname .. " appelé"
end

-- ---------------------------------------------------------------------------
--  Persistance du menu (widget recréé à chaque ouverture). AUCUN Ar ici.
-- ---------------------------------------------------------------------------
local active, showExtra, lastReport = false, false, ""
local camOn = false   -- état suivi de la caméra libre du moteur

LoopAsync(1000, function()
    if active then
        pcall(function()
            ExecuteInGameThread(function()
                EnsureCheatManager()
                local ok, seen = SetBuildConfig(BUILD_DEBUG)
                if showExtra then SetExtraButtons(VIS_VISIBLE) end
                local rep = ok .. "/" .. seen .. (showExtra and " +extra" or "")
                if rep ~= lastReport then lastReport = rep; log("menu déverrouillé : " .. rep) end
            end)
        end)
    end
    return false
end)

-- ============================================================================
--  COMMANDE : devmenu
-- ============================================================================
RegisterConsoleCommandGlobalHandler("devmenu", function(FullCommand, Parameters, Ar)
    local key = (Parameters and Parameters[1] and string.lower(Parameters[1])) or ""

    if key == "off" or key == "stop" then
        active, showExtra = false, false
        say(Ar, "désactivé.")
        ExecuteInGameThread(function()
            local ok, seen = SetBuildConfig(BUILD_SHIPPING)
            SetExtraButtons(VIS_COLLAPSED)
            log("remis en Shipping : " .. ok .. "/" .. seen)
        end)
        return true
    end

    if key == "status" then
        local list = FindAllOf(MENU_CLASS)
        local n = 0
        if list then for _, w in pairs(list) do if isRealObject(w) then n = n + 1 end end end
        say(Ar, string.format("actif=%s extra=%s | CheatManager=%s | widgets=%d",
            tostring(active), tostring(showExtra), tostring(GetCheatManager() ~= nil), n))
        if n == 0 then say(Ar, "ouvre le menu pause une fois (Échap) puis retape devmenu.") end
        return true
    end

    if key == "extra" or key == "full" then
        showExtra = not showExtra
        active = true
        lastReport = ""
        say(Ar, showExtra and "boutons supplémentaires AFFICHÉS (LOAD LEVEL / SAVE / RESTART / LAST CHECKPOINT)."
                           or  "boutons supplémentaires masqués.")
        if showExtra then say(Ar, "note : LOAD LEVEL ne propose que des maps absentes — voir 'devmap' à la place.") end
        local want = showExtra and VIS_VISIBLE or VIS_COLLAPSED
        ExecuteInGameThread(function() log("extra ajustés : " .. SetExtraButtons(want)) end)
        return true
    end

    if key ~= "" and key ~= "on" then
        say(Ar, "usage : devmenu | devmenu extra | devmenu off | devmenu status")
        return true
    end

    active = true
    lastReport = ""
    say(Ar, "activé — réapplication auto chaque seconde.")
    ExecuteInGameThread(function()
        local ok, why = EnsureCheatManager()
        log("CheatManager : " .. (ok and why or ("ECHEC - " .. tostring(why))))
        local n, seen = SetBuildConfig(BUILD_DEBUG)
        log("menu déverrouillé : " .. n .. "/" .. seen)
    end)
    return true
end)

-- ============================================================================
--  COMMANDE : cheat
-- ============================================================================
RegisterConsoleCommandGlobalHandler("cheat", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local key = (p[1] and string.lower(p[1])) or ""

    if key == "" or key == "help" or key == "list" then
        say(Ar, #CHEATS .. " fonctions — usage : cheat <alias> [argument]")
        for _, e in ipairs(CHEATS) do
            say(Ar, string.format("  %-11s %-26s%s", e[1], e[2], e[3] and ("  <" .. e[3] .. ">") or ""))
        end
        return true
    end

    -- Diagnostic : distingue "fonction introuvable" de "appelée sans effet".
    if key == "diag" then
        local cm = GetCheatManager()
        if not cm then say(Ar, "CheatManager ABSENT — lance 'devmenu' d'abord"); return true end
        local fn = "?"
        pcall(function() fn = cm:GetFullName() end)
        say(Ar, "CheatManager : " .. tostring(fn))
        -- ⚠️ On rapporte le TYPE RÉEL renvoyé par UE4SS, sans présumer que c'est
        -- une "function" — c'est justement cette hypothèse fausse qui a produit
        -- le diagnostic trompeur "0/23" le 21/07.
        local found, missing, kinds = 0, {}, {}
        for _, e in ipairs(CHEATS) do
            local t = "nil"
            pcall(function() local v = cm[e[2]]; t = (v == nil) and "nil" or type(v) end)
            kinds[t] = (kinds[t] or 0) + 1
            if t ~= "nil" then found = found + 1 else missing[#missing + 1] = e[2] end
        end
        local ks = {}
        for k, v in pairs(kinds) do ks[#ks + 1] = k .. "=" .. v end
        say(Ar, string.format("résolues : %d/%d  (types renvoyés : %s)",
            found, #CHEATS, table.concat(ks, ", ")))
        if #missing > 0 then say(Ar, "NIL : " .. table.concat(missing, ", ")) end
        return true
    end

    local entry = FindEntry(CHEATS, key)
    if not entry then say(Ar, "inconnu : '" .. key .. "' — tape 'cheat list'"); return true end

    local parts = {}
    for i = 2, #p do parts[#parts + 1] = tostring(p[i]) end
    local rawArg = table.concat(parts, " ")

    say(Ar, "appel de " .. entry[2] .. (rawArg ~= "" and (" (" .. rawArg .. ")") or "") .. "…")
    ExecuteInGameThread(function()
        if not EnsureCheatManager() then log("CheatManager absent — lance 'devmenu'"); return end
        local ok, msg = InvokeCheat(entry, rawArg)
        log(entry[2] .. " -> " .. tostring(msg))
    end)
    return true
end)

-- ============================================================================
--  COMMANDE : cam
--    cam            -> ToggleDebugCamera (caméra libre du MOTEUR, via CheatManager)
--    cam spawn      -> AYgroGameMode:SpawnDebugCamera   (spectateur du JEU)
--    cam despawn    -> AYgroGameMode:DespawnDebugCamera
--    cam off        -> despawn + nettoyage de secours
-- ============================================================================
-- ---------------------------------------------------------------------------
--  ENTREES DU SPECTATEUR
--
--  SpawnDebugCamera fait apparaitre BP_YgroSpectatorPawn, mais le PlayerController
--  continue de posseder One : les entrees vont au PERSONNAGE, jamais a la camera.
--  Il manque l'activation du contexte d'entree IMC_SpectatorCamera.
--
--  IMC_SpectatorCamera = 16 mappings, TOUS MANETTE (aucun clavier/souris).
--  En l'ajoutant, la manette pilote la camera pendant que le clavier garde le
--  personnage — les deux en meme temps.
--
--  ⚠️ AddMappingContext est expose sur UEnhancedInputSubsystemInterface (que
--  UEnhancedInputLocalPlayerSubsystem implemente), PAS sur le subsystem lui-meme :
--  chercher le symbole exact sur la mauvaise classe donne un faux negatif.
-- ---------------------------------------------------------------------------
local IMC_SPECTATOR = "/Game/Game/Pawn/Playable/Input/IMC_SpectatorCamera"

local function GetInputSubsystem()
    local s = FindFirstOf("EnhancedInputLocalPlayerSubsystem")
    if s and s:IsValid() then return s end
    return nil
end

local function ResolveAsset(path)
    local short = string.match(path, "([^/]+)$")
    local full = path .. "." .. short
    local o = StaticFindObject(full)
    if o and o:IsValid() then return o end
    for _ = 1, 3 do
        pcall(function() LoadAsset(path) end)
        o = StaticFindObject(full)
        if o and o:IsValid() then return o end
    end
    return nil
end

local function SetSpectatorInput(enable)
    local sub = GetInputSubsystem()
    if not sub then return false, "EnhancedInputLocalPlayerSubsystem introuvable" end
    local imc = ResolveAsset(IMC_SPECTATOR)
    if not imc then return false, "IMC_SpectatorCamera introuvable" end

    local ok = false
    if enable then
        -- Priorite elevee pour passer devant les contextes du gameplay.
        ok = pcall(function() sub:AddMappingContext(imc, 100, {}) end)
        if not ok then ok = pcall(function() sub:AddMappingContext(imc, 100) end) end
    else
        ok = pcall(function() sub:RemoveMappingContext(imc, {}) end)
        if not ok then ok = pcall(function() sub:RemoveMappingContext(imc) end) end
    end
    if not ok then return false, "AddMappingContext/RemoveMappingContext a echoue" end
    return true, enable and "contexte spectateur ACTIVE (manette)" or "contexte spectateur retire"
end

RegisterConsoleCommandGlobalHandler("cam", function(FullCommand, Parameters, Ar)
    local key = (Parameters and Parameters[1] and string.lower(Parameters[1])) or ""

    if key == "help" then
        say(Ar, "cam            (retiree) -> voir cam spawn")
        say(Ar, "cam spawn      spectateur du jeu (16 touches manette : vol, FOV, DOF, ralenti)")
        say(Ar, "cam despawn    quitte le spectateur")
        say(Ar, "cam input      active/retire les entrees manette (cam input off)")
        say(Ar, "cam off        tout couper")
        return true
    end

    if key == "input" then
        local off = (Parameters and Parameters[2] and string.lower(Parameters[2]) == "off")
        say(Ar, off and "retrait du contexte d'entree spectateur…"
                    or  "activation du contexte d'entree spectateur (MANETTE)…")
        ExecuteInGameThread(function()          -- pas de Ar ici
            local ok, msg = SetSpectatorInput(not off)
            log("cam input -> " .. tostring(msg))
        end)
        return true
    end

    if key == "spawn" or key == "spectator" then
        say(Ar, "spawn du spectateur du jeu…")
        ExecuteInGameThread(function()
            EnsureCheatManager()
            local ok, msg = GameModeCamera(true)
            log("cam spawn -> " .. tostring(msg))
            -- Sans ce contexte, les entrees restent sur le personnage.
            local iok, imsg = SetSpectatorInput(true)
            log("  entrees : " .. tostring(imsg))
            if ok then log("manette : sticks=vol/visée, RT/LT=haut/bas, LB/RB=FOV, A=DOF, X=ralenti, B=accéléré") end
        end)
        return true
    end

    if key == "despawn" then
        say(Ar, "despawn du spectateur…")
        ExecuteInGameThread(function() local _, m = GameModeCamera(false); log("cam despawn -> " .. tostring(m)) end)
        return true
    end

    if key == "off" then
        camOn = false
        say(Ar, "extinction des caméras…")
        ExecuteInGameThread(function()
            local ok, how = ExitFreeCam()
            log("sortie freecam -> " .. (ok and how or tostring(how)))
            GameModeCamera(false)
            log("caméras coupées")
        end)
        return true
    end

    -- défaut : caméra libre du moteur.
    -- On suit l'état nous-mêmes et on envoie Enable/Disable EXPLICITEMENT plutôt
    -- que Toggle : une fois la caméra active, le PC est un ADebugCameraController
    -- et la bascule ne revenait pas en arrière de façon fiable.
    -- ============================================================================
    --  FREECAM MOTEUR : RETIREE (22/07/2026)
    --
    --  EnableDebugCamera entre sans probleme, mais SORTIR est impossible de facon
    --  fiable sur cette installation :
    --    - DisableDebugCamera doit etre appele sur le CheatManager DU
    --      DebugCameraController (il caste son outer) ; or le mod
    --      CheatManagerEnabler intercepte EnableCheats -> ce CheatManager n'est
    --      jamais cree ("CheatManager already exist, skipping restoration").
    --    - UPlayer::SwitchController, la voie propre, n'a PAS de thunk exec.
    --    - Rendre possession + vue ne suffit pas : le DCC garde le UPlayer.
    --    - Detruire le DCC laisse un etat incertain.
    --  L'utilisateur est reste bloque 4 fois. On ne propose plus cette voie.
    --  'cam' redirige vers le spectateur du JEU, qui a un Despawn ecrit par les devs.
    -- ============================================================================
    say(Ar, "la freecam moteur a ete RETIREE : impossible d'en sortir de facon fiable.")
    say(Ar, "  cause : CheatManagerEnabler intercepte EnableCheats, donc")
    say(Ar, "  DisableDebugCamera ne peut pas fonctionner sur cette installation.")
    say(Ar, "  -> utilise 'cam spawn' (spectateur du jeu) et 'cam despawn'.")
    return true
end)

-- ============================================================================
--  COMMANDE : devmap
--  ⚠️ Charger une map QUITTE la partie en cours. Sauvegarde avant.
-- ============================================================================
RegisterConsoleCommandGlobalHandler("devmap", function(FullCommand, Parameters, Ar)
    local key = (Parameters and Parameters[1] and string.lower(Parameters[1])) or ""

    if key == "" or key == "list" or key == "help" then
        say(Ar, "maps de dev présentes dans cette build — usage : devmap <alias>")
        for _, m in ipairs(DEVMAPS) do
            say(Ar, string.format("  %-8s %-20s %s", m[1], m[2], m[3]))
        end
        say(Ar, "⚠️ charger une map QUITTE la partie en cours — sauvegarde avant.")
        return true
    end

    local m = FindEntry(DEVMAPS, key)
    if not m then say(Ar, "map inconnue : '" .. key .. "' — tape 'devmap list'"); return true end

    say(Ar, "chargement de " .. m[2] .. " …")
    ExecuteInGameThread(function()
        -- ⚠️ NE PAS appeler UGameplayStatics::OpenLevel ici : son 2e paramètre est
        -- un FName. Lui passer une chaîne Lua a CRASHÉ le jeu en v4
        -- (EXCEPTION_ACCESS_VIOLATION 0x70 dans LuaType::push_nameproperty).
        -- pcall NE PROTÈGE PAS de ça. La commande console ne prend que des
        -- chaînes : marshalling trivial, aucun risque de conversion.
        local ok, err = Console("open " .. m[2])
        log("open " .. m[2] .. " -> " .. (ok and "envoyé" or tostring(err)))
    end)
    return true
end)

log("Chargé (v4). Commandes : devmenu | cheat | cam | devmap  (ajoute 'list' ou 'help')")
