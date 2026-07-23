-- ============================================================================
--  FADING ECHO — FEPerf  (v1)
--
--  10 presets de performance. Plus le numero est ELEVE, plus on a de FPS
--  (et plus c'est moche). Preset 0 = remise aux defauts moteur.
--
--    fps <0-10>      applique un preset
--    fps status      preset courant + rappel de ce qu'il fait
--    fps list        la liste des 10 presets
--    fps stat        bascule l'overlay `stat unit` (ms CPU/GPU) pour mesurer
--    fps off         = fps 0
--
--  Raccourcis (pave numerique, choisis pour ne PAS entrer en conflit avec les
--  F1-F10 des autres mods FE) :
--    Pave +          preset suivant  (plus de FPS)
--    Pave -          preset precedent (plus beau)
--    Pave *          affiche le statut
--
--  ---------------------------------------------------------------------------
--  ⚠️ PIEGE `Ar` (repris de FEDevMenu, a deja crashe un mod)
--  Le FOutputDevice `Ar` n'est valide QUE dans le corps SYNCHRONE du handler.
--  Dans ExecuteInGameThread / LoopAsync c'est un pointeur mort ->
--  EXCEPTION_ACCESS_VIOLATION lecture 0x8. pcall NE PROTEGE PAS.
--  => dans tout code differe : print() uniquement.
--
--  ⚠️ Certaines cvars sont marquees ECVF_Cheat et sont IGNOREES en build
--  Shipping. Le mod ne peut pas le savoir : une commande refusee ne remonte
--  aucune erreur. C'est sans danger, ca ne fait juste rien.
-- ============================================================================

local UEHelpers = require("UEHelpers")

local MOD  = "[FEPerf] "
local DEFAULT_PRESET = 0        -- preset applique au lancement (0 = ne rien toucher)

local Current  = 0
local StatOn   = false

local function log(m) print(MOD .. tostring(m) .. "\n") end
local function say(Ar, m)       -- corps SYNCHRONE du handler UNIQUEMENT
    log(m)
    if Ar then pcall(function() Ar:Log(MOD .. tostring(m)) end) end
end

-- ---------------------------------------------------------------------------
--  Console moteur  (helpers valides en jeu dans FEDevMenu, 21/07/2026)
-- ---------------------------------------------------------------------------
local function isRealObject(o)
    if not (o and o:IsValid()) then return false end
    local fn = ""
    pcall(function() fn = o:GetFullName() end)
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

local function KSL()
    local ok, o = pcall(UEHelpers.GetKismetSystemLibrary)
    if ok and o and o:IsValid() then return o end
    return StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
end

-- ⚠️ SpecificPlayer : passer le PC courant. nil a fait echouer la commande
-- dans FEDevMenu v5 (l'argument objet ne tolere pas nil ici).
local function Console(cmd)
    local k, w, pc = KSL(), GetWorld(), GetPC()
    if not (k and w) then return false, "KismetSystemLibrary ou World introuvable" end
    local ok, err = pcall(function() k:ExecuteConsoleCommand(w, cmd, pc) end)
    return ok, (not ok) and tostring(err) or nil
end

-- ---------------------------------------------------------------------------
--  RESET : defauts moteur.
--  Applique AVANT chaque preset, pour que passer de 8 a 3 ne laisse pas
--  trainer les reglages du 8. Chaque preset est donc auto-suffisant.
--  ⚠️ Ce sont les defauts MOTEUR, pas forcement ceux que le jeu se met tout
--  seul au demarrage. Retour 100 % propre = menu graphique du jeu, ou relancer.
-- ---------------------------------------------------------------------------
local RESET = {
    "sg.ResolutionQuality 100", "sg.ViewDistanceQuality 3", "sg.AntiAliasingQuality 3",
    "sg.ShadowQuality 3", "sg.GlobalIlluminationQuality 3", "sg.ReflectionQuality 3",
    "sg.PostProcessQuality 3", "sg.TextureQuality 3", "sg.EffectsQuality 3",
    "sg.FoliageQuality 3", "sg.ShadingQuality 3",
    "r.ScreenPercentage 100", "r.AntiAliasingMethod 4",
    "r.MotionBlurQuality 4", "r.DepthOfFieldQuality 2", "r.BloomQuality 5",
    "r.Tonemapper.Quality 5", "r.SSR.Quality 3", "r.VolumetricFog 1",
    "r.ViewDistanceScale 1", "foliage.DensityScale 1", "grass.DensityScale 1",
    "r.Lumen.DiffuseIndirect.Allow 1", "r.Lumen.Reflections.Allow 1",
    "r.DynamicGlobalIlluminationMethod 1", "r.ReflectionMethod 1",
    "r.Nanite.MaxPixelsPerEdge 1", "r.SkeletalMeshLODBias 0",
    "r.StaticMeshLODDistanceScale 1", "r.Shadow.DistanceScale 1",
    "r.Shadow.MaxCSMResolution 2048", "r.Streaming.MipBias 0",
    "r.DistanceFieldShadowing 1", "r.AmbientOcclusionLevels -1",
    "r.DetailMode 2", "r.MaterialQualityLevel 1", "r.EyeAdaptationQuality 2",
    "r.LensFlareQuality 2", "r.SceneColorFringeQuality 1", "r.LightFunctionQuality 2",
    "r.SeparateTranslucency 1",
}

-- Applique a TOUS les presets >= 1 : le framerate ne sert a rien s'il est
-- plafonne par le cap moteur ou la VSync.
local UNCAP = { "t.MaxFPS 0", "r.VSync 0" }

-- ---------------------------------------------------------------------------
--  LES 10 PRESETS
--  name / hint / cmds (deltas appliques par-dessus RESET)
-- ---------------------------------------------------------------------------
local PRESETS = {
    [1] = { name = "Vanilla+",
            hint = "aucune perte visuelle : juste cap FPS/VSync off, flou de mouvement et profondeur de champ coupes",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0" } },

    [2] = { name = "Eleve",
            hint = "post-process allege (reflets ecran, bloom, tonemapper)",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.SSR.Quality 2", "r.BloomQuality 4", "r.Tonemapper.Quality 3",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0" } },

    [3] = { name = "Eleve-",
            hint = "ombres / GI / reflets / effets en qualite 2, le reste intact",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ShadowQuality 2", "sg.GlobalIlluminationQuality 2",
                     "sg.ReflectionQuality 2", "sg.EffectsQuality 2",
                     "sg.PostProcessQuality 2", "r.SSR.Quality 1" } },

    [4] = { name = "Moyen",
            hint = "tous les groupes de scalabilite en 2 + rendu a 90 %",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ViewDistanceQuality 2", "sg.AntiAliasingQuality 2",
                     "sg.ShadowQuality 2", "sg.GlobalIlluminationQuality 2",
                     "sg.ReflectionQuality 2", "sg.PostProcessQuality 2",
                     "sg.TextureQuality 2", "sg.EffectsQuality 2",
                     "sg.FoliageQuality 2", "sg.ShadingQuality 2",
                     "r.ScreenPercentage 90", "r.Shadow.DistanceScale 0.8",
                     "r.SSR.Quality 1" } },

    [5] = { name = "Moyen-",
            hint = "brouillard volumetrique et reflets ecran coupes, rendu a 85 %",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ViewDistanceQuality 2", "sg.AntiAliasingQuality 2",
                     "sg.ShadowQuality 1", "sg.GlobalIlluminationQuality 1",
                     "sg.ReflectionQuality 1", "sg.PostProcessQuality 2",
                     "sg.TextureQuality 2", "sg.EffectsQuality 2",
                     "sg.FoliageQuality 2", "sg.ShadingQuality 2",
                     "r.ScreenPercentage 85", "r.SSR.Quality 0",
                     "r.VolumetricFog 0", "r.ViewDistanceScale 0.9",
                     "foliage.DensityScale 0.8", "grass.DensityScale 0.8",
                     "r.Shadow.DistanceScale 0.7" } },

    [6] = { name = "Bas — Lumen coupe",
            hint = "gros palier : eclairage dynamique Lumen desactive (GI + reflets), tout en qualite 1",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ViewDistanceQuality 1", "sg.AntiAliasingQuality 1",
                     "sg.ShadowQuality 1", "sg.GlobalIlluminationQuality 0",
                     "sg.ReflectionQuality 0", "sg.PostProcessQuality 1",
                     "sg.TextureQuality 1", "sg.EffectsQuality 1",
                     "sg.FoliageQuality 1", "sg.ShadingQuality 1",
                     "r.ScreenPercentage 80", "r.SSR.Quality 0", "r.VolumetricFog 0",
                     "r.Lumen.DiffuseIndirect.Allow 0", "r.Lumen.Reflections.Allow 0",
                     "r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 2",
                     "r.ViewDistanceScale 0.8", "foliage.DensityScale 0.6",
                     "grass.DensityScale 0.6", "r.Shadow.DistanceScale 0.6",
                     "r.BloomQuality 2" } },

    [7] = { name = "Bas- — ombres coupees",
            hint = "plus d'ombres dynamiques, vegetation et distance d'affichage bien reduites",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ViewDistanceQuality 1", "sg.AntiAliasingQuality 1",
                     "sg.ShadowQuality 0", "sg.GlobalIlluminationQuality 0",
                     "sg.ReflectionQuality 0", "sg.PostProcessQuality 1",
                     "sg.TextureQuality 1", "sg.EffectsQuality 0",
                     "sg.FoliageQuality 0", "sg.ShadingQuality 1",
                     "r.ScreenPercentage 75", "r.SSR.Quality 0", "r.VolumetricFog 0",
                     "r.Lumen.DiffuseIndirect.Allow 0", "r.Lumen.Reflections.Allow 0",
                     "r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 2",
                     "r.ViewDistanceScale 0.65", "foliage.DensityScale 0.45",
                     "grass.DensityScale 0.45", "r.Shadow.DistanceScale 0.4",
                     "r.Shadow.MaxCSMResolution 1024", "r.DistanceFieldShadowing 0",
                     "r.BloomQuality 1", "r.Nanite.MaxPixelsPerEdge 2",
                     "r.AmbientOcclusionLevels 0" } },

    [8] = { name = "Tres bas",
            hint = "scalabilite 0 partout, TSR remplace par du FXAA, rendu a 66 %",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ViewDistanceQuality 0", "sg.AntiAliasingQuality 0",
                     "sg.ShadowQuality 0", "sg.GlobalIlluminationQuality 0",
                     "sg.ReflectionQuality 0", "sg.PostProcessQuality 0",
                     "sg.TextureQuality 0", "sg.EffectsQuality 0",
                     "sg.FoliageQuality 0", "sg.ShadingQuality 0",
                     "r.ScreenPercentage 66", "r.AntiAliasingMethod 1",
                     "r.SSR.Quality 0", "r.VolumetricFog 0",
                     "r.Lumen.DiffuseIndirect.Allow 0", "r.Lumen.Reflections.Allow 0",
                     "r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 2",
                     "r.ViewDistanceScale 0.5", "foliage.DensityScale 0.3",
                     "grass.DensityScale 0.3", "r.Shadow.DistanceScale 0.3",
                     "r.Shadow.MaxCSMResolution 512", "r.DistanceFieldShadowing 0",
                     "r.BloomQuality 1", "r.Nanite.MaxPixelsPerEdge 3",
                     "r.AmbientOcclusionLevels 0", "r.SkeletalMeshLODBias 1",
                     "r.StaticMeshLODDistanceScale 2", "r.DetailMode 1",
                     "r.MaterialQualityLevel 0" } },

    [9] = { name = "Patate",
            hint = "plus d'anti-aliasing du tout, rendu a 58 %, textures en basse resolution",
            cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                     "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                     "sg.ViewDistanceQuality 0", "sg.AntiAliasingQuality 0",
                     "sg.ShadowQuality 0", "sg.GlobalIlluminationQuality 0",
                     "sg.ReflectionQuality 0", "sg.PostProcessQuality 0",
                     "sg.TextureQuality 0", "sg.EffectsQuality 0",
                     "sg.FoliageQuality 0", "sg.ShadingQuality 0",
                     "r.ScreenPercentage 58", "r.AntiAliasingMethod 0",
                     "r.SSR.Quality 0", "r.VolumetricFog 0",
                     "r.Lumen.DiffuseIndirect.Allow 0", "r.Lumen.Reflections.Allow 0",
                     "r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 2",
                     "r.ViewDistanceScale 0.4", "foliage.DensityScale 0.15",
                     "grass.DensityScale 0.15", "r.Shadow.DistanceScale 0.2",
                     "r.Shadow.MaxCSMResolution 512", "r.DistanceFieldShadowing 0",
                     "r.BloomQuality 0", "r.Tonemapper.Quality 0",
                     "r.Nanite.MaxPixelsPerEdge 4", "r.AmbientOcclusionLevels 0",
                     "r.SkeletalMeshLODBias 2", "r.StaticMeshLODDistanceScale 4",
                     "r.DetailMode 0", "r.MaterialQualityLevel 0",
                     "r.EyeAdaptationQuality 0", "r.SeparateTranslucency 0",
                     "r.Streaming.MipBias 1", "r.LightFunctionQuality 0" } },

    [10] = { name = "Patate ultime",
             hint = "rendu a 50 %, LOD au minimum, vegetation supprimee. C'est laid, c'est le but.",
             cmds = { "r.MotionBlurQuality 0", "r.DepthOfFieldQuality 0",
                      "r.LensFlareQuality 0", "r.SceneColorFringeQuality 0",
                      "sg.ViewDistanceQuality 0", "sg.AntiAliasingQuality 0",
                      "sg.ShadowQuality 0", "sg.GlobalIlluminationQuality 0",
                      "sg.ReflectionQuality 0", "sg.PostProcessQuality 0",
                      "sg.TextureQuality 0", "sg.EffectsQuality 0",
                      "sg.FoliageQuality 0", "sg.ShadingQuality 0",
                      "r.ScreenPercentage 50", "r.AntiAliasingMethod 0",
                      "r.SSR.Quality 0", "r.VolumetricFog 0",
                      "r.Lumen.DiffuseIndirect.Allow 0", "r.Lumen.Reflections.Allow 0",
                      "r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 2",
                      "r.ViewDistanceScale 0.3", "foliage.DensityScale 0",
                      "grass.DensityScale 0", "r.Shadow.DistanceScale 0.1",
                      "r.Shadow.MaxCSMResolution 256", "r.DistanceFieldShadowing 0",
                      "r.BloomQuality 0", "r.Tonemapper.Quality 0",
                      "r.Nanite.MaxPixelsPerEdge 6", "r.AmbientOcclusionLevels 0",
                      "r.SkeletalMeshLODBias 3", "r.StaticMeshLODDistanceScale 8",
                      "r.DetailMode 0", "r.MaterialQualityLevel 0",
                      "r.EyeAdaptationQuality 0", "r.SeparateTranslucency 0",
                      "r.Streaming.MipBias 2.5", "r.LightFunctionQuality 0",
                      "r.Fog 0" } },
}

-- ---------------------------------------------------------------------------
--  Application
-- ---------------------------------------------------------------------------
local function RunList(list)
    local okc, kof = 0, 0
    for _, c in ipairs(list) do
        local ok = Console(c)
        if ok then okc = okc + 1 else kof = kof + 1 end
    end
    return okc, kof
end

-- ⚠️ Differe -> print() uniquement, JAMAIS Ar (voir en-tete).
local function Apply(n)
    ExecuteInGameThread(function()
        local a, b = RunList(RESET)                 -- repart toujours du meme etat
        local c, d = 0, 0
        if n >= 1 then
            local e, f = RunList(UNCAP); c, d = c + e, d + f
            local p = PRESETS[n]
            local g, h = RunList(p.cmds); c, d = c + g, d + h
            log(("preset %d — %s"):format(n, p.name))
            log("  " .. p.hint)
        else
            log("preset 0 — defauts moteur restaures")
        end
        log(("  %d commandes passees, %d en echec"):format(a + c, b + d))
        Current = n
    end)
end

local function Status(Ar)
    if Current == 0 then
        say(Ar, "preset 0 (defauts moteur). `fps 1` a `fps 10` pour monter en FPS.")
    else
        local p = PRESETS[Current]
        say(Ar, ("preset %d/10 — %s"):format(Current, p.name))
        say(Ar, "  " .. p.hint)
    end
end

local function Step(delta)
    local n = Current + delta
    if n < 0 then n = 0 elseif n > 10 then n = 10 end
    if n == Current then
        log(("deja au preset %d (min 0, max 10)"):format(Current))
        return
    end
    Apply(n)
end

-- ---------------------------------------------------------------------------
--  Commande console
-- ---------------------------------------------------------------------------
RegisterConsoleCommandGlobalHandler("fps", function(FullCommand, Parameters, Ar)
    local a = (Parameters[1] or ""):lower()

    if a == "" or a == "status" then
        Status(Ar)
        return true
    end

    if a == "list" then
        say(Ar, "presets (plus le numero est haut, plus il y a de FPS) :")
        say(Ar, "   0 — defauts moteur")
        for i = 1, 10 do
            say(Ar, ("  %2d — %s : %s"):format(i, PRESETS[i].name, PRESETS[i].hint))
        end
        return true
    end

    if a == "stat" then
        StatOn = not StatOn
        ExecuteInGameThread(function()
            Console("stat unit")
            log("overlay `stat unit` = " .. tostring(StatOn))
        end)
        say(Ar, "overlay ms CPU/GPU bascule (Frame / Game / Draw / GPU).")
        return true
    end

    if a == "off" then
        say(Ar, "retour au preset 0.")
        Apply(0)
        return true
    end

    local n = tonumber(a)
    if not n or n ~= math.floor(n) or n < 0 or n > 10 then
        say(Ar, "usage : fps <0-10> | status | list | stat | off")
        return true
    end

    -- Le detail part dans la fenetre UE4SS (code differe), on accuse juste reception ici.
    say(Ar, ("preset %d demande — detail dans la console UE4SS."):format(n))
    Apply(n)
    return true
end)

-- ---------------------------------------------------------------------------
--  Raccourcis clavier — pave numerique, pour ne pas marcher sur les F1-F10
--  deja pris par FEUnlocker-Plus / FEMoonJump / FEInfiniteCore / Keystrokes.
--  Repli sur NUM_9 / NUM_7 / NUM_8 si le build UE4SS n'expose pas ADD/SUBTRACT.
-- ---------------------------------------------------------------------------
local K_UP   = Key.ADD      or Key.NUM_NINE
local K_DOWN = Key.SUBTRACT or Key.NUM_SEVEN
local K_STAT = Key.MULTIPLY or Key.NUM_EIGHT

RegisterKeyBind(K_UP,   function() Step(1) end)
RegisterKeyBind(K_DOWN, function() Step(-1) end)
RegisterKeyBind(K_STAT, function() Status(nil) end)

-- ---------------------------------------------------------------------------
log("charge. `fps list` pour les 10 presets, pave +/- pour monter/descendre.")
if DEFAULT_PRESET and DEFAULT_PRESET > 0 then
    log(("application du preset par defaut (%d)..."):format(DEFAULT_PRESET))
    Apply(DEFAULT_PRESET)
end
