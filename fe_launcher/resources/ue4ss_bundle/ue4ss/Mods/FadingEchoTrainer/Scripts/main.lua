local MOD_NAME = "[FadingEchoTrainer]"

local ueHelpersOk, UEHelpers = pcall(require, "UEHelpers")
if not ueHelpersOk then
    UEHelpers = nil
end

local savedTransform = nil
local cachedPlayerController = nil

local function log(message)
    print(MOD_NAME .. " " .. tostring(message))
end

local function safe(label, callback)
    local ok, result = pcall(callback)
    if not ok then
        log(label .. " failed: " .. tostring(result))
        return nil
    end

    return result
end

local function isValidObject(object)
    if object == nil then
        return false
    end

    local ok, valid = pcall(function()
        return object:IsValid()
    end)

    return ok and valid == true
end

local function numericField(source, field, fallback)
    if source == nil then
        return fallback or 0.0
    end

    local ok, value = pcall(function()
        return source[field]
    end)

    if ok and type(value) == "number" then
        return value
    end

    return fallback or 0.0
end

local function copyVector(source)
    if source == nil then
        return nil
    end

    return {
        X = numericField(source, "X", 0.0),
        Y = numericField(source, "Y", 0.0),
        Z = numericField(source, "Z", 0.0),
    }
end

local function copyRotator(source)
    if source == nil then
        return nil
    end

    return {
        Pitch = numericField(source, "Pitch", 0.0),
        Yaw = numericField(source, "Yaw", 0.0),
        Roll = numericField(source, "Roll", 0.0),
    }
end

local function fieldOrUnknown(source, field)
    if source == nil then
        return "?"
    end

    local ok, value = pcall(function()
        return source[field]
    end)

    if not ok or value == nil then
        return "?"
    end

    if type(value) == "number" then
        return string.format("%.2f", value)
    end

    return tostring(value)
end

local function formatTransform(transform)
    return string.format(
        "X=%s Y=%s Z=%s Pitch=%s Yaw=%s Roll=%s",
        fieldOrUnknown(transform.position, "X"),
        fieldOrUnknown(transform.position, "Y"),
        fieldOrUnknown(transform.position, "Z"),
        fieldOrUnknown(transform.rotation, "Pitch"),
        fieldOrUnknown(transform.rotation, "Yaw"),
        fieldOrUnknown(transform.rotation, "Roll")
    )
end

local function getDefaultObject(path)
    local object = safe("StaticFindObject " .. path, function()
        return StaticFindObject(path)
    end)

    if not isValidObject(object) then
        return nil
    end

    return object
end

local function getGameplayStatics()
    if UEHelpers ~= nil then
        local gameplayStatics = safe("UEHelpers.GetGameplayStatics", function()
            return UEHelpers.GetGameplayStatics()
        end)

        if isValidObject(gameplayStatics) then
            return gameplayStatics
        end
    end

    return getDefaultObject("/Script/Engine.Default__GameplayStatics")
end

local function controllerHasPlayerPawn(controller)
    local pawn = safe("Read PlayerController.Pawn", function()
        return controller.Pawn
    end)

    if not isValidObject(pawn) then
        return false
    end

    local ok, isPlayerControlled = pcall(function()
        return pawn:IsPlayerControlled()
    end)

    return ok and isPlayerControlled == true
end

local function findPlayerController()
    if isValidObject(cachedPlayerController) then
        return cachedPlayerController
    end

    if UEHelpers ~= nil then
        local controller = safe("UEHelpers.GetPlayerController", function()
            return UEHelpers.GetPlayerController()
        end)

        if isValidObject(controller) then
            cachedPlayerController = controller
            return controller
        end
    end

    local controllers = safe("FindAllOf PlayerController", function()
        return FindAllOf("PlayerController")
    end) or {}

    local firstValidController = nil

    for _, controller in pairs(controllers) do
        if isValidObject(controller) then
            if firstValidController == nil then
                firstValidController = controller
            end

            if controllerHasPlayerPawn(controller) then
                cachedPlayerController = controller
                return controller
            end
        end
    end

    cachedPlayerController = firstValidController
    return cachedPlayerController
end

local function getWorld()
    if UEHelpers ~= nil then
        local world = safe("UEHelpers.GetWorld", function()
            return UEHelpers.GetWorld()
        end)

        if isValidObject(world) then
            return world
        end
    end

    local controller = findPlayerController()
    if controller == nil then
        return nil
    end

    local world = safe("PlayerController.GetWorld", function()
        return controller:GetWorld()
    end)

    if not isValidObject(world) then
        return nil
    end

    return world
end

local function getPlayerActor()
    local gameplayStatics = getGameplayStatics()
    local world = getWorld()

    if gameplayStatics ~= nil and world ~= nil then
        local character = safe("GetPlayerCharacter", function()
            return gameplayStatics:GetPlayerCharacter(world, 0)
        end)

        if isValidObject(character) then
            return character
        end

        local pawn = safe("GetPlayerPawn", function()
            return gameplayStatics:GetPlayerPawn(world, 0)
        end)

        if isValidObject(pawn) then
            return pawn
        end
    end

    local controller = findPlayerController()
    if controller == nil then
        return nil
    end

    local pawn = safe("Read PlayerController.Pawn", function()
        return controller.Pawn
    end)

    if not isValidObject(pawn) then
        return nil
    end

    return pawn
end

local function runOnGameThread(label, callback)
    if type(ExecuteInGameThread) == "function" then
        safe(label, function()
            ExecuteInGameThread(function()
                safe(label, callback)
            end)
        end)
        return
    end

    safe(label, callback)
end

local function savePosition()
    runOnGameThread("SavePosition", function()
        local playerActor = getPlayerActor()
        if playerActor == nil then
            log("could not save; no valid player actor")
            return
        end

        local position = safe("K2_GetActorLocation", function()
            return playerActor:K2_GetActorLocation()
        end)
        local rotation = safe("K2_GetActorRotation", function()
            return playerActor:K2_GetActorRotation()
        end)

        local nextTransform = {
            position = copyVector(position),
            rotation = copyRotator(rotation),
            controlRotation = nil,
        }

        if nextTransform.position == nil or nextTransform.rotation == nil then
            log("could not save; failed to read current transform")
            return
        end

        local controller = findPlayerController()
        if controller ~= nil then
            local controlRotation = safe("GetControlRotation", function()
                return controller:GetControlRotation()
            end)
            nextTransform.controlRotation = copyRotator(controlRotation)
        end

        savedTransform = nextTransform
        log("saved position " .. formatTransform(savedTransform))
    end)
end

local function loadPosition()
    if savedTransform == nil then
        log("no saved position")
        return
    end

    runOnGameThread("LoadPosition", function()
        local playerActor = getPlayerActor()
        if playerActor == nil then
            log("could not load; no valid player actor")
            return
        end

        safe("K2_SetActorLocationAndRotation", function()
            playerActor:K2_SetActorLocationAndRotation(
                savedTransform.position,
                savedTransform.rotation,
                false,
                {},
                true
            )
        end)

        if savedTransform.controlRotation ~= nil then
            local controller = findPlayerController()
            if controller ~= nil then
                safe("SetControlRotation", function()
                    controller:SetControlRotation(savedTransform.controlRotation)
                end)
            end
        end

        log("loaded position " .. formatTransform(savedTransform))
    end)
end

local function registerKey(keyName, key, callback)
    safe("RegisterKeyBind " .. keyName, function()
        RegisterKeyBind(key, function()
            safe("Key " .. keyName, callback)
        end)
    end)
end

registerKey("F6 SavePosition", Key.F6, savePosition)
registerKey("F7 LoadPosition", Key.F7, loadPosition)

log("loaded; F6 saves position, F7 loads position")
