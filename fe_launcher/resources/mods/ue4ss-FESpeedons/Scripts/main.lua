-- ============================================================================
--  FADING ECHO — SPEEDONS  (v2)
--
--  Recolore One aux couleurs d'une DA "SpeeDons" (néon cyan / magenta sur base
--  sombre) en écrivant les PARAMÈTRES VECTORIELS de ses matériaux.
--
--  Commandes (console du jeu = touche ² , ou console UE4SS) :
--     speedons                  état + rappel des commandes
--     speedons on               applique la palette
--     speedons off              restaure les matériaux d'origine
--     speedons lock             réapplique en boucle (formes / respawn écrasent)
--     speedons dump             inventaire des composants et de leurs slots
--     speedons set <role> <hex> change une couleur à chaud (ex: set accent 00E5FF)
--     speedons boost <n>        intensité émissive (défaut 1.0)
--     speedons preset <nom>     speedons | invert | mono | silhouette
--     speedons blast <param> <hex>   force UN paramètre partout (exploration)
--
--  Retours détaillés : FENÊTRE DE CONSOLE UE4SS.
--
-- ============================================================================
--  ⚠️⚠️  CE QUE LA v1 A FAIT DE FAUX — LIRE AVANT DE TOUCHER  ⚠️⚠️
--
--  La v1 écrivait tous les noms de paramètres connus sur tous les slots, puis
--  RELISAIT pour "confirmer". Elle a annoncé 216 paramètres confirmés. C'ÉTAIT
--  FAUX, intégralement.
--
--  RAISON : un UMaterialInstanceDynamic STOCKE la valeur d'un paramètre même
--  quand ce paramètre N'EXISTE PAS dans le matériau compilé — c'est un simple
--  TArray d'overrides. K2_GetVectorParameterValue relit CE TABLEAU, pas le
--  shader. Donc écrire-puis-relire réussit TOUJOURS, y compris sur un nom
--  inventé. On ne vérifiait pas que le jeu écoutait, on vérifiait qu'on avait
--  bien écrit dans sa propre poche.
--
--  Preuve dans le log : "Fluid Color", "InsideColor", "Outline2_Color" donnés
--  OK sur le CORPS de One, dont le matériau n'a AUCUN paramètre vectoriel.
--
--  IL N'EXISTE PAS DE SONDE D'EXISTENCE FIABLE À L'EXÉCUTION. Les getters BP ne
--  rendent pas de booléen de présence, et UMaterialInstance::GetVectorParameter
--  Value (celui qui rend un bool) n'est pas exposé au Blueprint.
--
--  => LA VÉRITÉ VIENT DES ASSETS, PAS DU RUNTIME. On ne pousse que les
--     paramètres DÉCLARÉS par le matériau de base, relevés dans l'extract
--     FModel (table FAMILIES ci-dessous). Les logs disent "écrit", jamais
--     "confirmé" : on n'a aucun moyen de confirmer, autant l'assumer.
-- ============================================================================
--
--  ---------------------------------------------------------------------------
--  CE QUI EST RÉELLEMENT PILOTABLE (relevé dans l'extract, build démo)
--
--   A. TÊTE / CHEVEUX — MI_MainCharaHead -> MM_Character
--        VECTEURS : BlinkColor (FFFFFF), HairColor (00D6FF, déjà cyan)
--                   + PortalSphereLocation et EyesPosition, qui sont des
--                     POSITIONS déguisées en vecteurs : NE PAS Y TOUCHER.
--        SCALAIRES : Emmissive Hair/NEAR/MID boost, EmissivePower, BlinkSpeed
--
--   B. CORPS + CAPE — MI_MainCharaBody / MI_MainCharaCape -> MM_Character_opt
--        VECTEURS : AUCUN. Le seul est PortalSphereLocation (une position).
--        La couleur du corps vient des TEXTURES (Basecolor_Shard/_Near/_Mid).
--        => on ne peut PAS teinter le corps. Ce n'est pas exposé. Ne pas
--           rechercher : c'est vérifié, pas supposé.
--        SCALAIRES : Emmissive NEAR boost, Emmissive MID boost
--
--   C. CONTOUR — coques d'outline -> MM_OutlineOverlay
--        VECTEURS : Color (101010), TopColor (FF00EB), BottomColor (00FFFF),
--                   DissolveColor (00E4FF), TargetedColor (D8D8D8)
--        => le shader d'outline du jeu est DÉJÀ un dégradé cyan -> magenta.
--           C'est LE levier visible, et le plus "SpeeDons" par nature.
--
--  ---------------------------------------------------------------------------
--  LE CONTOUR EST UNE COQUE INVERSÉE, PAS UN OVERLAY MATERIAL
--
--  (établi le 22/07 par le mod FESkins — ne pas reprendre à zéro)
--  BP_OverlayMeshComponent DUPLIQUE le mesh au BeginPlay en SkeletalMeshComponent
--  supplémentaires, ATTACHÉS AU COMPOSANT "Mesh" (donc FRÈRES du manager, jamais
--  ses enfants), portant un MID de MM_OutlineOverlay. Confirmé en jeu 22/07 :
--  2 coques, 4 slots chacune.
--
--  ⚠️ Le nom du matériau d'une coque n'est PAS "MI_OutlineOne" (le jeu crée des
--  MID_*). On ne peut donc PAS reconnaître la famille "outline" au nom : on la
--  déduit de la PROVENANCE (composant collecté via BP_OverlayMeshComponent).
--
--  ---------------------------------------------------------------------------
--  PIÈGES UE4SS DÉJÀ PAYÉS — NE PAS LES REFAIRE
--   1. `Ar` n'est valide QUE dans le corps SYNCHRONE du handler (sinon AV 0x8).
--   2. Une UFUNCTION n'est PAS une `function` Lua : ne jamais tester le type.
--   3. Jamais de chaîne Lua brute sur un paramètre FName (AV 0x70).
--      SetVectorParameterValue prend un FName => TOUJOURS FName("...").
--   4. `o:IsValid()` plante si `o` n'est pas un UObject => okObj() partout.
--   5. Un appel qui ne lève pas d'erreur NE PROUVE RIEN — et sur un MID, une
--      RELECTURE NON PLUS (cf. le grand encadré ci-dessus).
--   6. `K2_GetComponentsByClass` rend 0 composant sur CE pawn — vérifié le
--      22/07 avec /Script/Engine.MeshComponent PUIS avec PrimitiveComponent,
--      et avec lecture TArray (GetArrayNum + [i]) en plus de pairs(). C'est
--      bien le pawn qui ne répond pas. On passe par pawn.Mesh et
--      BP_OverlayMeshComponent, qui répondent tous les deux.
--      (Reste vrai en général : le retour de cette fonction EST un TArray, à
--       lire GetArrayNum()+[i] — un pairs() seul ne rendrait rien.)
--   7. `#table` vaut 0 sur une table à clés chaînes. Compter à la main.
-- ============================================================================

local UEHelpers = require("UEHelpers")

-- ---------------------------------------------------------------------------
--  PALETTE  — c'est ICI qu'on change les couleurs.
--
--  ⚠️ Je n'ai pas pu vérifier la charte graphique officielle de SpeeDons 2026
--  (speedons.fr en 403, rien d'exploitable en recherche). Cette palette est un
--  néon cyan/magenta sur base sombre — la signature visuelle historique de
--  l'événement, PAS une charte vérifiée. Corrige les hex ici, ou à chaud avec
--  `speedons set <role> <hex>`.
-- ---------------------------------------------------------------------------
local PALETTE = {
    accent  = "00E5FF",   -- cyan néon    : cheveux, bas du contour
    accent2 = "FF2ED1",   -- magenta néon : blink, haut du contour
    light   = "FFFFFF",   -- blanc        : liseré de ciblage
    dark    = "0B0B14",   -- presque noir : base du contour (défaut jeu 101010)
}

local PRESETS = {
    -- fidèle au rendu du jeu : silhouette noire, dégradé cyan -> magenta
    speedons   = { accent = "00E5FF", accent2 = "FF2ED1", light = "FFFFFF", dark = "0B0B14" },
    invert     = { accent = "FF2ED1", accent2 = "00E5FF", light = "FFFFFF", dark = "0B0B14" },
    mono       = { accent = "00E5FF", accent2 = "00E5FF", light = "FFFFFF", dark = "000000" },
    -- silhouette entièrement cyan au lieu de noire : bien plus visible
    silhouette = { accent = "00E5FF", accent2 = "FF2ED1", light = "FFFFFF", dark = "00E5FF" },

    -- ⚠️ PRESET DE TEST — couleurs volontairement HORRIBLES et sans rapport avec
    -- la DA. Raison d'être : la palette "speedons" est un néon cyan/magenta…
    -- posé sur un jeu dont les défauts SONT déjà un néon cyan/magenta
    -- (HairColor 00D6FF, Color 101010, TopColor FF00EB, BottomColor 00FFFF).
    -- On remplaçait donc du cyan par du cyan : AUCUN changement perceptible,
    -- alors que toute la plomberie fonctionnait. Constaté le 22/07 après avoir
    -- cherché le bug pendant trois itérations.
    -- => TOUJOURS valider une chaîne de rendu avec une couleur ABERRANTE avant
    --    de conclure qu'elle ne marche pas.
    test = { accent = "00FF00", accent2 = "FFFF00", light = "FF0000", dark = "FF0000" },
}

local BOOST = 1.0     -- multiplicateur des couleurs et des scalaires émissifs

-- ---------------------------------------------------------------------------
--  FAMILLES DE MATÉRIAUX — LA VÉRITÉ, relevée dans l'extract FModel.
--
--  On n'écrit QUE ce qui est déclaré ici. Ajouter un nom au hasard ne "marche"
--  pas : ça écrit dans le vide en silence (cf. l'encadré du haut).
--
--  vectors : nom du paramètre -> rôle de palette
--  scalars : nom du paramètre -> valeur de base (multipliée par BOOST)
-- ---------------------------------------------------------------------------
local FAMILIES = {
    -- MM_Character (tête / cheveux). PortalSphereLocation et EyesPosition sont
    -- des POSITIONS : volontairement absentes.
    head = {
        label   = "MM_Character (tête/cheveux)",
        vectors = { HairColor = "accent", BlinkColor = "accent2" },
        scalars = { ["Emmissive Hair boost"] = 1.5,
                    ["Emmissive NEAR boost"] = 2.0,
                    ["Emmissive MID boost"]  = 1.2,
                    ["EmissivePower"]        = 1.0 },
    },
    -- MM_Character_opt (corps / cape). AUCUN vecteur : ce n'est pas un oubli.
    body = {
        label   = "MM_Character_opt (corps/cape) — aucune couleur exposée",
        vectors = {},
        scalars = { ["Emmissive NEAR boost"] = 2.0,
                    ["Emmissive MID boost"]  = 1.2 },
    },
    -- MM_OutlineOverlay (coques d'outline).
    outline = {
        label   = "MM_OutlineOverlay (contour)",
        vectors = { Color         = "dark",
                    TopColor      = "accent2",
                    BottomColor   = "accent",
                    DissolveColor = "accent",
                    TargetedColor = "light" },
        scalars = {},
    },
}

-- ---------------------------------------------------------------------------
--  Journalisation
--  Le verrou tourne toutes les 2 s : sans garde-fou il inonde la console et
--  rend la lecture d'une commande impossible.
-- ---------------------------------------------------------------------------
local quietDepth = 0
local function log(m)
    if quietDepth > 0 then return end
    print("[FESpeedons] " .. tostring(m) .. "\n")
end
local function loud(m) print("[FESpeedons] " .. tostring(m) .. "\n") end
local function quietly(fn)
    quietDepth = quietDepth + 1
    local ok, r = pcall(fn)
    quietDepth = quietDepth - 1
    if not ok then return nil end
    return r
end
local function say(Ar, m)            -- corps SYNCHRONE du handler UNIQUEMENT
    log(m)
    if Ar then pcall(function() Ar:Log("[FESpeedons] " .. tostring(m)) end) end
end

-- ---------------------------------------------------------------------------
--  Helpers objets (cf. piège 4)
-- ---------------------------------------------------------------------------
local function okObj(o)
    if not o then return false end
    local v = false
    pcall(function() v = o:IsValid() end)
    return v
end

local function isRealObject(o)
    if not okObj(o) then return false end
    local fn = ""
    pcall(function() fn = o:GetFullName() end)
    return not string.find(fn, "Default__", 1, true)
end

local function Name(o)
    if not okObj(o) then return "(nil)" end
    local n = "?"
    pcall(function() n = o:GetFullName() end)
    return n
end

local function ShortName(o)
    local n = Name(o)
    return string.match(n, "([^%.%s/]+)$") or n
end

local function ClassOf(o)
    local c
    pcall(function() c = o:GetClass():GetFullName() end)
    if not c then return nil end
    return string.match(c, "([^%.%s/]+)$") or c
end

local function GetPawn()
    local cs = FindAllOf("PlayerController")
    if cs then
        for _, c in pairs(cs) do
            if isRealObject(c) then
                local pk
                pcall(function() pk = c.Pawn end)
                if isRealObject(pk) then return pk end
            end
        end
    end
    local list = FindAllOf("BP_CoreYgroCharacter_C")
    if list then
        for _, a in pairs(list) do if isRealObject(a) then return a end end
    end
    return nil
end

-- ---------------------------------------------------------------------------
--  Couleurs
--
--  ⚠️ Un hex est en sRGB, un FLinearColor est en LINÉAIRE. Écrire la valeur
--  brute donne un rendu délavé et faux (le cyan tire vers le blanc). La
--  conversion sRGB -> linéaire n'est pas optionnelle.
-- ---------------------------------------------------------------------------
local function srgbToLinear(c)
    if c <= 0.04045 then return c / 12.92 end
    return ((c + 0.055) / 1.055) ^ 2.4
end

local function HexToLinear(hex, mul)
    hex = string.gsub(tostring(hex), "^#", "")
    if #hex ~= 6 then return nil end
    local r = tonumber(string.sub(hex, 1, 2), 16)
    local g = tonumber(string.sub(hex, 3, 4), 16)
    local b = tonumber(string.sub(hex, 5, 6), 16)
    if not (r and g and b) then return nil end
    mul = mul or 1.0
    return {
        R = srgbToLinear(r / 255) * mul,
        G = srgbToLinear(g / 255) * mul,
        B = srgbToLinear(b / 255) * mul,
        A = 1.0,
    }
end

local function ColorOf(role)
    return HexToLinear(PALETTE[role] or "FFFFFF", BOOST)
end

-- ---------------------------------------------------------------------------
--  Écriture
--
--  PAS de relecture "de confirmation" : sur un MID elle ne prouve rien (encadré
--  du haut). On rapporte ce qu'on a ÉCRIT, et on ne pousse que des paramètres
--  déclarés par le matériau de base. `ok` ne signifie donc que "l'appel n'a pas
--  levé d'erreur".
-- ---------------------------------------------------------------------------
local function SetVector(mid, pname, col)
    return pcall(function() mid:SetVectorParameterValue(FName(pname), col) end)
end

local function SetScalar(mid, pname, v)
    return pcall(function() mid:SetScalarParameterValue(FName(pname), v) end)
end

-- ---------------------------------------------------------------------------
--  Obtenir un matériau ÉCRITURABLE sur un slot
--
--  Les matériaux en place sont déjà des MID_ créés par le jeu (variable
--  DynamicMaterials sur le pawn) : on écrit dessus directement, sans remplacer
--  le slot. Sinon on fabrique un MID depuis le matériau en place, et on garde
--  l'ancien pour 'speedons off'.
-- ---------------------------------------------------------------------------
local touched = {}         -- { { comp, index, prev } }  slots réellement REMPLACÉS
local touchedKeys = {}

local function RememberSlot(comp, index, prev)
    local k = Name(comp) .. "#" .. index
    if touchedKeys[k] then return end
    touchedKeys[k] = true
    touched[#touched + 1] = { comp = comp, index = index, prev = prev }
end

-- ⚠️ RECONNAÎTRE UN MID SE FAIT SUR LA CLASSE, JAMAIS SUR LE NOM.
-- Bug de la v2 (constaté 22/07) : le test était string.find(nom, "MID"). Or les
-- MID que CE mod crée s'appellent "FESpeedons…" — sans "MID" dedans. Ils
-- n'étaient donc jamais reconnus comme dynamiques, et chaque Apply en créait
-- 4 de plus. Avec 'speedons lock' (2 s) = ~120 MID/minute qui fuient.
local function isMID(o)
    if not okObj(o) then return false end
    local c = ClassOf(o) or ""
    if c == "MaterialInstanceDynamic" then return true end
    return string.find(ShortName(o), "MID", 1, true) ~= nil   -- repli
end

local function WritableMaterial(comp, index)
    local prev
    pcall(function() prev = comp:GetMaterial(index) end)

    if isMID(prev) then
        return prev, prev                     -- déjà dynamique : on écrit dessus
    end

    local mid
    pcall(function() mid = comp:CreateDynamicMaterialInstance(index, prev, FName("FESpeedons")) end)
    if not okObj(mid) then
        pcall(function() mid = comp:CreateDynamicMaterialInstance(index) end)
    end
    if okObj(mid) then
        RememberSlot(comp, index, prev)
        return mid, prev
    end
    return okObj(prev) and prev or nil, prev
end

-- ---------------------------------------------------------------------------
--  Composants
-- ---------------------------------------------------------------------------
local function GetMesh()
    local pawn = GetPawn()
    if not pawn then return nil, "joueur introuvable" end
    local m
    pcall(function() m = pawn.Mesh end)
    if okObj(m) then return m, nil end
    return nil, "composant Mesh introuvable sur le pawn"
end

-- Reprise de la version qui MARCHE dans FESkins (cf. piège 6) : classe
-- PrimitiveComponent, et lecture du retour en TArray avec repli pairs().
local function ListPawnMeshComponents()
    local pawn = GetPawn()
    if not pawn then return {} end
    local out, seen = {}, {}
    local cls = StaticFindObject("/Script/Engine.PrimitiveComponent")
    if not cls then return out end
    local comps
    pcall(function() comps = pawn:K2_GetComponentsByClass(cls) end)
    if not comps then return out end

    local function add(c)
        if okObj(c) then
            local k = Name(c)
            if not seen[k] then seen[k] = true; out[#out + 1] = c end
        end
    end

    local n = 0
    pcall(function() n = comps:GetArrayNum() end)
    if n and n > 0 then
        for i = 1, n do
            local c
            pcall(function() c = comps[i] end)
            add(c)
        end
    else
        pcall(function() for _, c in pairs(comps) do add(c) end end)
    end
    return out
end

-- ⚠️ UNE COQUE MASQUÉE NE SE VERRA JAMAIS, quelle que soit sa couleur.
-- FESkins sait ÉTEINDRE l'outline ('skin outline off' / 'outline lock', qui
-- pose bVisible=false / bHiddenInGame=true sur ces mêmes composants). Si cette
-- commande a déjà tourné dans la session, recolorer le contour est sans effet
-- visible — et rien dans nos logs ne le dirait. On le RELIT donc explicitement.
local function ReadVisibility(smc)
    local vis, hid = "?", "?"
    pcall(function() vis = tostring(smc.bVisible) end)
    if vis == "?" or vis == "nil" then pcall(function() vis = tostring(smc:IsVisible()) end) end
    pcall(function() hid = tostring(smc.bHiddenInGame) end)
    return vis, hid
end

local function GetOverlayComp()
    local pawn = GetPawn()
    if not pawn then return nil end
    local ov
    pcall(function() ov = pawn.BP_OverlayMeshComponent end)
    if okObj(ov) then return ov end
    return nil
end

-- Union des trois sources connues, dédupliquée sur GetFullName. Aucune n'est
-- garantie peuplée ; en jeu (22/07) SkeletalsOverlay a rendu les 2 coques.
local function CollectOverlaySMC(ov)
    local out, seen = {}, {}
    local function push(o)
        if not okObj(o) then return end
        local fn = Name(o)
        if seen[fn] then return end
        seen[fn] = true
        out[#out + 1] = o
    end
    local function eatArray(arr)
        if arr == nil then return end
        local cnt = 0
        pcall(function() cnt = arr:GetArrayNum() end)
        if cnt and cnt > 0 then
            for i = 1, cnt do
                local e
                pcall(function() e = arr[i] end)
                push(e)
            end
        else
            pcall(function() for _, e in pairs(arr) do push(e) end end)
        end
    end

    local a
    pcall(function() a = ov.SkeletalsOverlay end)
    eatArray(a)
    for _, slot in ipairs({ "OutlineOverlay", "StatusOverlay" }) do
        local om
        pcall(function() om = ov[slot] end)
        if okObj(om) then
            local arr
            pcall(function() arr = om.SkeletalMeshComponents end)
            eatArray(arr)
        end
    end
    return out
end

-- ---------------------------------------------------------------------------
--  Famille d'un slot du MESH PRINCIPAL, déduite du nom du matériau en place.
--  Les MID gardent le nom de l'asset source : MID_MainCharaHead_0, etc.
--  (les coques d'outline, elles, ne sont PAS reconnaissables au nom : leur
--  famille vient de leur provenance, cf. en-tête)
-- ---------------------------------------------------------------------------
local function FamilyOfSlot(comp, index)
    local mat
    pcall(function() mat = comp:GetMaterial(index) end)
    local n = ShortName(mat)
    if string.find(n, "Head", 1, true) then return "head", n end
    if string.find(n, "Body", 1, true) or string.find(n, "Cape", 1, true) then return "body", n end
    return nil, n
end

-- ---------------------------------------------------------------------------
--  SLOT 0 DU MESH : MI_Character_Skin<N> — NON RÉSOLU
--
--  Le dump en jeu (22/07) donne 4 slots sur CharacterMesh0 :
--      [0] MID_MI_Character_Skin1        <- inconnu
--      [1] MID_MI_MainCharaBody_Skin1    -> MM_Character_opt
--      [2] MID_MI_MainCharaHead_Skin1    -> MM_Character
--      [3] MID_MI_MainCharaCape_..._Skin1-> MM_Character_opt
--
--  MI_Character n'existe PAS dans l'extract de la DÉMO (qui n'a aucun dossier
--  Skin<N>/) : impossible de lire son matériau parent, donc impossible de
--  savoir quels paramètres il déclare. Je ne devine pas — le slot est ignoré.
--
--  Pour trancher, deux voies :
--    - fournir l'extract uasset du jeu COMPLET (build 1.0.27900), et lire le
--      Parent de MI_Character_Skin1 ;
--    - ou empiriquement : `speedons blast HairColor FF0000` puis REGARDER.
--      Si une partie de One vire au rouge, le paramètre existe sur ce slot.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
--  Application
-- ---------------------------------------------------------------------------
local applied = false
local locked  = false
local lastReport = ""

-- famKey = nil -> on déduit slot par slot (mesh principal)
--          "outline" -> forcé (coques)
local function PaintComponent(comp, famKey, written, skipped)
    local n = 0
    pcall(function() n = comp:GetNumMaterials() end)
    if n == 0 then return end

    for i = 0, n - 1 do
        local key, matName = famKey, nil
        if not key then key, matName = FamilyOfSlot(comp, i) end
        if not matName then matName = select(2, FamilyOfSlot(comp, i)) end

        local fam = key and FAMILIES[key] or nil
        if not fam then
            skipped[#skipped + 1] = string.format("%s[%d] %s — famille inconnue, ignoré",
                ShortName(comp), i, matName or "?")
        else
            local mid = WritableMaterial(comp, i)
            if not okObj(mid) then
                skipped[#skipped + 1] = string.format("%s[%d] %s — pas de matériau écriturable",
                    ShortName(comp), i, matName or "?")
            else
                local any = false
                for pname, role in pairs(fam.vectors) do
                    if SetVector(mid, pname, ColorOf(role)) then
                        any = true
                        written[#written + 1] = string.format("%s[%d] %s = #%s (%s)",
                            ShortName(comp), i, pname, PALETTE[role], role)
                    end
                end
                for pname, base in pairs(fam.scalars) do
                    if SetScalar(mid, pname, base * BOOST) then
                        any = true
                        written[#written + 1] = string.format("%s[%d] %s = %.2f",
                            ShortName(comp), i, pname, base * BOOST)
                    end
                end
                if not any then
                    skipped[#skipped + 1] = string.format("%s[%d] %s — %s : rien à écrire",
                        ShortName(comp), i, matName or "?", fam.label)
                end
            end
        end
    end
end

local function Apply()
    local pawn = GetPawn()
    if not pawn then return false, "joueur introuvable (charge une partie d'abord)" end

    local written, skipped = {}, {}
    local seen, nComp = {}, 0
    local function paint(c, famKey)
        if not okObj(c) then return end
        local fn = Name(c)
        if seen[fn] then return end
        seen[fn] = true
        nComp = nComp + 1                      -- piège 7 : #seen vaudrait 0
        PaintComponent(c, famKey, written, skipped)
    end

    paint(select(1, GetMesh()), nil)           -- famille déduite par slot

    local ov = GetOverlayComp()
    if okObj(ov) then
        for _, smc in ipairs(CollectOverlaySMC(ov)) do paint(smc, "outline") end
    end

    applied = #written > 0
    lastReport = table.concat(written, "\n    ")
    if #skipped > 0 then
        lastReport = lastReport .. "\n  ignoré :\n    " .. table.concat(skipped, "\n    ")
    end

    if #written == 0 then
        return false, "rien écrit. Fais 'speedons dump' : soit les composants ne "
                   .. "sont pas construits (lance depuis le JEU, pas le menu), soit "
                   .. "les noms de matériaux de cette build diffèrent de l'extract."
    end
    return true, string.format("%d écriture(s) sur %d composant(s), %d slot(s) ignoré(s)",
                               #written, nComp, #skipped)
end

local function Restore()
    if #touched == 0 then
        return false, "rien à restaurer : aucun slot n'a été REMPLACÉ (les matériaux "
                   .. "en place étaient déjà des MID, on a écrit dedans). Ils se "
                   .. "réinitialisent au changement de forme ou au rechargement de zone."
    end
    local n = 0
    for _, rec in ipairs(touched) do
        if okObj(rec.comp) and okObj(rec.prev) then
            if pcall(function() rec.comp:SetMaterial(rec.index, rec.prev) end) then n = n + 1 end
        end
    end
    touched, touchedKeys = {}, {}
    applied = false
    return true, n .. " slot(s) restauré(s)"
end

-- ---------------------------------------------------------------------------
--  blast — force UN paramètre sur TOUS les slots.
--  Outil d'EXPLORATION uniquement : aucun moyen de savoir si le paramètre
--  existe, il faut REGARDER L'ÉCRAN. Si rien ne bouge, il n'existe pas.
-- ---------------------------------------------------------------------------
local function Blast(pname, hex)
    local col = HexToLinear(hex, BOOST)
    if not col then return false, "hex invalide" end
    local n = 0
    local function doComp(c)
        if not okObj(c) then return end
        local num = 0
        pcall(function() num = c:GetNumMaterials() end)
        for i = 0, num - 1 do
            local mid = WritableMaterial(c, i)
            if okObj(mid) and SetVector(mid, pname, col) then n = n + 1 end
        end
    end
    doComp(select(1, GetMesh()))
    local ov = GetOverlayComp()
    if okObj(ov) then for _, s in ipairs(CollectOverlaySMC(ov)) do doComp(s) end end
    return true, n .. " slot(s) écrit(s) avec " .. pname .. " = #" .. hex
                 .. " — REGARDE L'ÉCRAN : si rien ne change, le paramètre n'existe pas."
end

-- ============================================================================
--  DIAGNOSTICS — parce que 50 écritures "réussies" ont donné ZÉRO changement
--  visuel en jeu (22/07). Deux causes possibles, et un test pour chacune.
--
--   (1) On n'écrit pas sur les matériaux réellement RENDUS.
--       -> `speedons proof` : on remplace carrément le matériau du CORPS par
--          celui du contour (unlit, masqué, normales extrudées). Si le corps de
--          One ne change PAS d'aspect, c'est qu'on ne touche pas au mesh rendu,
--          et le problème n'a rien à voir avec les paramètres.
--
--   (2) Le jeu réimpose ses valeurs à chaque frame (les MID du personnage sont
--       pilotés par le Blueprint dans Tick). Une boucle à 2 s ne peut pas
--       battre du 60 Hz.
--       -> `speedons watch <param>` : on écrit une valeur repère, puis on relit
--          plusieurs fois. Si la valeur REVIENT à autre chose, c'est le jeu qui
--          réécrit. (Ici la relecture est légitime : on ne cherche pas à prouver
--          l'existence du paramètre, mais à détecter qu'un TIERS écrit dessus.)
-- ============================================================================

local function ReadVector(mid, pname)
    local out
    for _, fn in ipairs({ "K2_GetVectorParameterValue", "GetVectorParameterValue" }) do
        local ok = pcall(function() out = mid[fn](mid, FName(pname)) end)
        if ok and out then return out end
    end
    return nil
end

local function fmtCol(c)
    if not c then return "(illisible)" end
    local r, g, b
    pcall(function() r, g, b = c.R, c.G, c.B end)
    if not r then return "(illisible)" end
    return string.format("%.3f/%.3f/%.3f", r, g, b)
end

-- Slot de la tête sur le mesh principal (celui qui déclare HairColor).
local function HeadSlot()
    local mesh = select(1, GetMesh())
    if not okObj(mesh) then return nil, nil end
    local n = 0
    pcall(function() n = mesh:GetNumMaterials() end)
    for i = 0, n - 1 do
        if select(1, FamilyOfSlot(mesh, i)) == "head" then return mesh, i end
    end
    return mesh, nil
end

local proofSaved = nil       -- { comp, index, prev }

local function Proof()
    local mesh = select(1, GetMesh())
    if not okObj(mesh) then return false, "mesh introuvable" end

    -- On récupère le matériau d'une coque d'outline : unlit + masqué, donc son
    -- effet sur le corps est impossible à rater.
    local ov = GetOverlayComp()
    if not okObj(ov) then return false, "BP_OverlayMeshComponent introuvable" end
    local shells = CollectOverlaySMC(ov)
    if #shells == 0 then return false, "aucune coque d'outline" end
    local outMat
    pcall(function() outMat = shells[1]:GetMaterial(0) end)
    if not okObj(outMat) then return false, "matériau d'outline illisible" end

    -- Slot du CORPS (pas la tête : on veut que ça saute aux yeux).
    local n, target = 0, nil
    pcall(function() n = mesh:GetNumMaterials() end)
    for i = 0, n - 1 do
        local _, nm = FamilyOfSlot(mesh, i)
        if nm and string.find(nm, "Body", 1, true) then target = i break end
    end
    if not target then return false, "slot corps introuvable" end

    local prev
    pcall(function() prev = mesh:GetMaterial(target) end)
    proofSaved = { comp = mesh, index = target, prev = prev }
    if not pcall(function() mesh:SetMaterial(target, outMat) end) then
        return false, "SetMaterial a échoué"
    end
    return true, "matériau du contour posé sur le slot corps [" .. target .. "].\n"
              .. "    REGARDE ONE. Si son corps n'a pas changé d'aspect, on n'écrit\n"
              .. "    PAS sur le mesh rendu -> les paramètres n'y sont pour rien.\n"
              .. "    'speedons proof off' pour remettre."
end

local function ProofOff()
    if not proofSaved then return false, "aucun test en cours" end
    local ok = pcall(function()
        proofSaved.comp:SetMaterial(proofSaved.index, proofSaved.prev)
    end)
    proofSaved = nil
    return ok, ok and "matériau d'origine remis" or "échec de la restauration"
end

-- Écrit une valeur repère puis relit N fois : si ça dérive, un tiers réécrit.
local function Watch(pname)
    local mesh, slot = HeadSlot()
    if not okObj(mesh) or not slot then return false, "slot tête introuvable" end
    local mid = WritableMaterial(mesh, slot)
    if not okObj(mid) then return false, "matériau non écriturable" end

    local before = ReadVector(mid, pname)
    local mark = { R = 1.0, G = 0.0, B = 0.0, A = 1.0 }   -- rouge pur = repère
    SetVector(mid, pname, mark)
    loud("[watch] " .. pname .. " avant = " .. fmtCol(before) .. "  -> écrit 1.000/0.000/0.000")

    local n = 0
    LoopAsync(300, function()
        n = n + 1
        local now = ReadVector(mid, pname)
        loud("[watch] t+" .. (n * 300) .. "ms : " .. fmtCol(now))
        if n >= 6 then
            loud("[watch] terminé. Si la valeur a QUITTÉ 1.000/0.000/0.000, le jeu")
            loud("        réécrit ce paramètre en continu -> il faut hooker sa")
            loud("        fonction d'écriture, pas boucler toutes les 2 s.")
            loud("        Si elle est RESTÉE et que rien n'a changé à l'écran, le")
            loud("        paramètre n'influence pas le rendu de ce matériau.")
            return true
        end
        return false
    end)
    return true, "surveillance de " .. pname .. " lancée (2 s, console UE4SS)"
end

-- ============================================================================
--  IDENTIFIER UN SLOT À L'ŒIL — `speedons slot <n> <hex>`
--
--  VALIDÉ EN JEU 22/07 : preset `test` -> le contour passe au ROUGE PUR, mais
--  les cheveux ne verdissent PAS. Donc :
--    - la chaîne d'écriture fonctionne (Color pilote bien la silhouette) ;
--    - `HairColor` sur le slot 2 (MI_MainCharaHead_Skin1) ne pilote RIEN de
--      visible. Les cheveux sont ailleurs — probablement le slot 0
--      (MI_Character_Skin1), justement celui qu'on ne sait pas résoudre.
--
--  Cette commande arrose UN SEUL slot avec tous les noms de couleur plausibles,
--  y compris ceux des matériaux de cheveux du jeu (MM_BlackHair / MM_UnlitHair
--  déclarent Hair_Color1 / Hair_Color2). On regarde ce qui change à l'écran :
--  c'est la seule preuve valable (cf. l'encadré du haut).
-- ============================================================================
local SLOT_PROBE_PARAMS = {
    "HairColor", "Hair_Color1", "Hair_Color2",   -- cheveux (MM_Character, Bigoudi)
    "BlinkColor", "Color", "Emissive Color",     -- génériques
    "BodyColor", "Tint", "Base Color", "BaseColor",
}

local function PaintSlot(index, hex)
    local mesh = select(1, GetMesh())
    if not okObj(mesh) then return false, "mesh introuvable" end
    local n = 0
    pcall(function() n = mesh:GetNumMaterials() end)
    if index < 0 or index >= n then
        return false, "slot hors bornes (0.." .. (n - 1) .. ")"
    end
    local col = HexToLinear(hex, BOOST)
    if not col then return false, "hex invalide" end

    local mid = WritableMaterial(mesh, index)
    if not okObj(mid) then return false, "slot non écriturable" end

    local _, matName = FamilyOfSlot(mesh, index)
    local k = 0
    for _, pname in ipairs(SLOT_PROBE_PARAMS) do
        if SetVector(mid, pname, col) then k = k + 1 end
    end
    return true, string.format("slot [%d] %s : %d nom(s) de couleur écrits en #%s.\n"
        .. "    REGARDE ONE — ce qui change identifie ce slot. Rien ne change =\n"
        .. "    ce slot ne porte aucune de ces couleurs.", index, matName or "?", k, hex)
end

-- ---------------------------------------------------------------------------
--  Diagnostic — inventaire pur, n'écrit RIEN.
-- ---------------------------------------------------------------------------
local function Dump()
    local pawn = GetPawn()
    if not pawn then log("joueur introuvable") return end
    log("--------------------------------------------------------------")
    log("pawn = " .. ShortName(pawn) .. " [" .. (ClassOf(pawn) or "?") .. "]")

    local function listSlots(c, tag, famKey)
        if not okObj(c) then log(tag .. " : INTROUVABLE") return end
        local n = 0
        pcall(function() n = c:GetNumMaterials() end)
        log(tag .. " : " .. ShortName(c) .. " [" .. (ClassOf(c) or "?") .. "] "
            .. n .. " slot(s)")
        for i = 0, n - 1 do
            local key, matName = famKey, nil
            if not key then key, matName = FamilyOfSlot(c, i) end
            if not matName then matName = select(2, FamilyOfSlot(c, i)) end
            local fam = key and FAMILIES[key]
            log(string.format("   [%d] %-42s -> %s", i, matName or "?",
                fam and fam.label or "famille inconnue (ignoré)"))
        end
    end

    listSlots(select(1, GetMesh()), "mesh principal", nil)

    local ov = GetOverlayComp()
    if okObj(ov) then
        local smcs = CollectOverlaySMC(ov)
        log("BP_OverlayMeshComponent : " .. ShortName(ov) .. " -> " .. #smcs .. " coque(s)")
        local anyHidden = false
        for _, s in ipairs(smcs) do
            local vis, hid = ReadVisibility(s)
            local ko = (vis == "false" or hid == "true")
            if ko then anyHidden = true end
            log("  coque " .. ShortName(s) .. "  bVisible=" .. vis
                .. "  bHiddenInGame=" .. hid .. (ko and "   << MASQUÉE" or ""))
            listSlots(s, "  coque", "outline")
        end
        if anyHidden then
            log("  note : une coque masquée est NORMALE — la 2e est le StatusOverlay,")
            log("         que le jeu n'affiche qu'au ciblage. La recolorer ne se voit")
            log("         donc pas tant que One n'est pas ciblé. Rien d'anormal.")
        end
    else
        log("BP_OverlayMeshComponent INTROUVABLE (pas de contour à recolorer)")
    end

    local comps = ListPawnMeshComponents()
    log(#comps .. " composant(s) primitive sur le pawn (via PrimitiveComponent) :")
    for _, c in ipairs(comps) do
        local n = 0
        pcall(function() n = c:GetNumMaterials() end)
        log("   " .. ShortName(c) .. " [" .. (ClassOf(c) or "?") .. "] " .. n .. " slot(s)")
    end

    log("rappel : le CORPS de One n'a AUCUN paramètre de couleur (textures).")
    log("         seuls la tête (HairColor/BlinkColor) et le contour sont pilotables.")
    log("--------------------------------------------------------------")
end

-- ---------------------------------------------------------------------------
--  Verrou — le jeu réimpose ses matériaux au changement de forme / au respawn.
--  Boucle SILENCIEUSE : une ligne uniquement quand le résultat CHANGE.
-- ---------------------------------------------------------------------------
local lastLockMsg = nil
LoopAsync(2000, function()
    if locked then
        local msg = quietly(function()
            local ok, m = Apply()
            return (ok and "OK " or "KO ") .. tostring(m)
        end)
        if msg and msg ~= lastLockMsg then
            lastLockMsg = msg
            loud("[verrou] " .. msg)
        end
    end
    return false
end)

-- ---------------------------------------------------------------------------
--  Commandes
--  ⚠️ Ar UNIQUEMENT dans le corps synchrone (piège 1).
-- ---------------------------------------------------------------------------
local function reapply(tag)
    ExecuteInGameThread(function()
        local ok, msg = Apply()
        log(tag .. " -> " .. tostring(msg))
        if ok then log("    " .. lastReport) end
    end)
end

RegisterConsoleCommandGlobalHandler("speedons", function(FullCommand, Parameters, Ar)
    local p = Parameters or {}
    local key = (p[1] and string.lower(p[1])) or ""

    if key == "on" then
        say(Ar, "application de la palette…")
        reapply("on")
        return true
    end

    if key == "off" then
        say(Ar, "restauration…")
        locked = false
        ExecuteInGameThread(function()
            local ok, msg = Restore()
            log("off -> " .. tostring(msg))
        end)
        return true
    end

    if key == "lock" then
        locked = not locked
        lastLockMsg = nil
        say(Ar, locked and "verrou ACTIF : réapplication toutes les 2 s." or "verrou levé.")
        return true
    end

    if key == "dump" then
        say(Ar, "inventaire — résultats dans la console UE4SS.")
        ExecuteInGameThread(Dump)
        return true
    end

    if key == "set" then
        local role = p[2] and string.lower(p[2]) or ""
        local hex  = p[3]
        if not PALETTE[role] then
            say(Ar, "rôles : accent | accent2 | light | dark")
            return true
        end
        if not HexToLinear(hex) then
            say(Ar, "hex invalide. Format RRGGBB (ex: speedons set accent 00E5FF)")
            return true
        end
        PALETTE[role] = string.gsub(hex, "^#", "")
        say(Ar, role .. " = #" .. PALETTE[role] .. " — réapplication…")
        reapply("set")
        return true
    end

    if key == "boost" then
        local v = tonumber(p[2])
        if not v or v < 0 then
            say(Ar, "usage : speedons boost <n>   (1.0 = neutre, 2.0 = deux fois plus lumineux)")
            return true
        end
        BOOST = v
        say(Ar, "boost = " .. v .. " — réapplication…")
        reapply("boost")
        return true
    end

    if key == "preset" then
        local nm = p[2] and string.lower(p[2]) or ""
        local ps = PRESETS[nm]
        if not ps then
            say(Ar, "presets : speedons | invert | mono | silhouette | test (couleurs criardes)")
            return true
        end
        for k, v in pairs(ps) do PALETTE[k] = v end
        say(Ar, "preset '" .. nm .. "' chargé — réapplication…")
        reapply("preset")
        return true
    end

    if key == "blast" then
        local pname, hex = p[2], p[3]
        if not pname or not HexToLinear(hex) then
            say(Ar, "usage : speedons blast <NomDuParametre> <RRGGBB>")
            say(Ar, "exploration seulement — REGARDE L'ÉCRAN, aucun retour ne prouve rien.")
            return true
        end
        say(Ar, "blast " .. pname .. " = #" .. hex .. "…")
        ExecuteInGameThread(function()
            local ok, msg = Blast(pname, hex)
            log("blast -> " .. tostring(msg))
        end)
        return true
    end

    if key == "slot" then
        local idx = tonumber(p[2])
        local hex = p[3] or "00FF00"
        if not idx then
            say(Ar, "usage : speedons slot <n> [RRGGBB]   (défaut vert pur)")
            say(Ar, "arrose UN slot du mesh avec tous les noms de couleur plausibles.")
            return true
        end
        say(Ar, "sondage du slot " .. idx .. "…")
        ExecuteInGameThread(function()
            local ok, msg = PaintSlot(math.floor(idx), hex)
            log("slot -> " .. tostring(msg))
        end)
        return true
    end

    if key == "proof" then
        if p[2] and string.lower(p[2]) == "off" then
            say(Ar, "restauration du test…")
            ExecuteInGameThread(function()
                local ok, msg = ProofOff()
                log("proof off -> " .. tostring(msg))
            end)
            return true
        end
        say(Ar, "test d'atteignabilité du mesh rendu…")
        ExecuteInGameThread(function()
            local ok, msg = Proof()
            log("proof -> " .. tostring(msg))
        end)
        return true
    end

    if key == "watch" then
        local pname = p[2] or "HairColor"
        say(Ar, "surveillance de " .. pname .. " — résultats dans la console UE4SS.")
        ExecuteInGameThread(function()
            local ok, msg = Watch(pname)
            log("watch -> " .. tostring(msg))
        end)
        return true
    end

    say(Ar, "DIAGNOSTIC : speedons slot <n> [hex] | proof [off] | watch <param>")
    say(Ar, "speedons on | off | lock | dump")
    say(Ar, "speedons set <accent|accent2|light|dark> <RRGGBB>")
    say(Ar, "speedons boost <n> | preset <speedons|invert|mono|silhouette|test>")
    say(Ar, "speedons blast <param> <RRGGBB>   (exploration, sans garantie)")
    say(Ar, "palette : accent #" .. PALETTE.accent .. "  accent2 #" .. PALETTE.accent2
            .. "  light #" .. PALETTE.light .. "  dark #" .. PALETTE.dark
            .. "  boost " .. BOOST)
    say(Ar, "état : " .. (applied and "appliqué" or "non appliqué")
            .. " | verrou : " .. tostring(locked))
    say(Ar, "PILOTABLE : tête (HairColor/BlinkColor) + contour (5 couleurs).")
    say(Ar, "PAS pilotable : le corps — ses couleurs sont dans les TEXTURES.")
    return true
end)

log("Chargé (v2). 'speedons dump' pour l'inventaire, 'speedons on' pour appliquer.")
log("v2 : la v1 annonçait 216 paramètres 'confirmés' — c'était faux (relecture")
log("     d'un MID = relecture de ses propres overrides). On ne pousse plus que")
log("     les paramètres réellement déclarés par les matériaux.")
