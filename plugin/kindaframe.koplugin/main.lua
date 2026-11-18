--[[--
kinda-frame: show a fresh server-rendered frame on KOReader's sleep screen.

Sleep path (specs/001-sleep-screen-frame/plan.md "Design Notes", data-model state machine):
  onSuspend  KOReader has already queued the saved frame (current.png), so sleep looks instant.
             We bump the generation, snapshot Wi-Fi, bring it up quietly if needed (no UI),
             and poll until connected.
  fetch      A forked child downloads to current.png.part (KOReader's UI loop never blocks);
             the parent polls it and kills it at the deadline.
  accept     Validate (HTTP 200, PNG signature, IHDR == screen size); identical bytes -> "unchanged".
             Otherwise fsync + rename over current.png.
  redraw     Only if still asleep (generation unchanged and Device.screen_saver_mode): swap the
             ImageWidget inside KOReader's own ScreenSaverWidget (never close it; proven in M1b),
             repaint, wait for the EPDC, hold ~1 s.
  finish     Exactly once per attempt: kill the child if alive, restore Wi-Fi, write one log line.
  onResume   Bump the generation (cancels pending steps and any late redraw) and finish("cancelled_wake").

The device suspends on powerd's own schedule (about 60 s SCREEN SAVER + READY TO SUSPEND).
We never ask for more time; we only guarantee nothing is in flight after the effective budget.
--]]

local Device = require("device")
local InfoMessage = require("ui/widget/infomessage")
local InputDialog = require("ui/widget/inputdialog")
local NetworkMgr = require("ui/network/manager")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local ffi = require("ffi")
local ffiutil = require("ffi/util")
local logger = require("logger")
local time = require("ui/time")
local _ = require("gettext")
local T = ffiutil.template
local Screen = Device.screen

local budget = require("kf/budget")
local fetchlog = require("kf/fetchlog")
local pngcheck = require("kf/pngcheck")
local req = require("kf/request")
local Session = require("kf/session")

-- Paths are module-level upvalues so the dev-machine harness (spec/main_spec.lua) can redirect them.
local BASE, CURRENT, PART, LOGFILE
local function set_base(dir)
    BASE = dir
    CURRENT = BASE .. "/current.png"
    PART = CURRENT .. ".part"
    LOGFILE = BASE .. "/kindaframe.log"
end
set_base("/mnt/us/kinda-frame")
local POLL_S = 0.25
local SETTLE_S = 1 -- hold after a redraw so we never suspend mid-refresh (R5)

local function setting(key, default)
    local v = G_reader_settings:readSetting("kindaframe_" .. key)
    if v == nil then return default end
    return v
end

local function save(key, value) G_reader_settings:saveSetting("kindaframe_" .. key, value) end

local function safe(fn, ...)
    local ok, v = pcall(fn, ...)
    return ok and v or nil
end

local function wifi_is_on() return safe(NetworkMgr.isWifiOn, NetworkMgr) and true or false end
local function wifi_connected() return safe(NetworkMgr.isConnected, NetworkMgr) and true or false end

local function battery()
    return safe(function() return Device:getPowerDevice():getCapacity() end)
end

local function read_all(path)
    local f = io.open(path, "rb")
    if not f then return nil end
    local d = f:read("*a")
    f:close()
    return d
end

local function close_fd(fd)
    pcall(function() ffi.C.close(fd) end)
end

local KindaFrame = WidgetContainer:extend{
    name = "kindaframe",
    is_doc_only = false,
}
KindaFrame._set_base = set_base -- test hook only

function KindaFrame:init()
    self.session = Session.new(function() return time.to_s(time.monotonic()) end)
    os.remove(PART) -- leftover from an interrupted attempt
    self.ui.menu:registerToMainMenu(self)
end

-- ---------------------------------------------------------------------------
-- Logging
-- ---------------------------------------------------------------------------

function KindaFrame:log(fields)
    local line = fetchlog.format(os.date("%Y-%m-%dT%H:%M:%S"), fields)
    logger.info("kindaframe:", line)
    pcall(fetchlog.append, LOGFILE, line)
end

-- ---------------------------------------------------------------------------
-- Sleep / wake events
-- ---------------------------------------------------------------------------

function KindaFrame:onSuspend()
    -- A manual "Fetch now" still running when the device sleeps is abandoned first.
    local a = self.session:active()
    if a then self:finish("cancelled_sleep") end
    local gen = self.session:on_suspend()
    local ok, err = pcall(self.startAttempt, self, gen, "sleep")
    if not ok then
        logger.warn("kindaframe: startAttempt failed:", err)
        self:finish("error", { detail = err })
    end
end

function KindaFrame:onResume()
    self.session:on_resume()
    local a = self.session:active()
    if a and a.kind == "sleep" then
        -- detail = how far it got (connecting / fetching / settling: a frame may already be saved)
        self:finish("cancelled_wake", { detail = a.state })
        os.remove(PART)
    end
end

function KindaFrame:onCloseWidget()
    -- Plugin instance torn down (e.g. switching file browser <-> reader): never leave a child or Wi-Fi behind.
    if self.session and self.session:active() then self:finish("cancelled_close") end
end

-- ---------------------------------------------------------------------------
-- Attempt lifecycle
-- ---------------------------------------------------------------------------

function KindaFrame:startAttempt(gen, kind)
    local url = setting("server_url")
    if kind == "sleep" and not setting("enabled", false) then
        return -- disabled: the saved frame is shown, nothing else happens (no log spam on every sleep)
    end
    if not req.valid_base(url) then
        return self:log{ outcome = "skipped_no_url", kind = kind }
    end

    local eff
    if kind == "sleep" then
        eff = budget.effective(setting("budget_s"), setting("window_s", budget.DEFAULT_WINDOW),
            setting("margin_s", budget.DEFAULT_MARGIN))
        if not eff then return self:log{ outcome = "skipped_no_window", kind = kind } end
    else
        eff = budget.clamp(setting("budget_s"))
    end

    local before = wifi_is_on()
    local a = self.session:begin(gen, eff, { kind = kind, wifi_before = before, turned_on = false, url = url })
    if not a then return end
    if not before then
        -- Quiet path: on Kindle this is just `wifid enable 1`, no "Scanning..." pop-ups over the sleep screen (R3).
        NetworkMgr:restoreWifiAsync()
        a.turned_on = true
    end
    a.state = "connecting"
    self:pollConnect(gen)
end

function KindaFrame:stale(gen)
    local a = self.session:active()
    return not a or a.gen ~= gen or (a.kind == "sleep" and not self.session:is_current(gen))
end

function KindaFrame:pollConnect(gen)
    if self:stale(gen) then return end
    if self.session:expired() then return self:finish("timeout", { detail = "wifi" }) end
    if wifi_connected() then
        local ok, err = pcall(self.startFetch, self, gen)
        if not ok then self:finish("error", { detail = err }) end
        return
    end
    UIManager:scheduleIn(POLL_S, self.pollConnect, self, gen)
end

function KindaFrame:startFetch(gen)
    local a = self.session:active()
    os.remove(PART)
    a.w, a.h = Screen:getWidth(), Screen:getHeight()
    local url = req.build_url(a.url, a.w, a.h, battery(), setting("orient", "portrait"))
    local limit = math.max(1, math.floor(self.session:remaining()))

    local pid, fd = ffiutil.runInSubProcess(function(_pid, wfd)
        -- Child process: blocking I/O is fine here. Everything it needs is captured above.
        local http = require("socket.http")
        local socketutil = require("socketutil") -- also patches socket.tcp to honour the timeouts
        socketutil:set_timeout(limit, limit)
        local line
        local fh = io.open(PART, "wb")
        if not fh then
            line = req.encode_result(nil, "cannot open " .. PART)
        else
            local r, code = http.request{
                url = url, method = "GET", redirect = false,
                sink = socketutil.file_sink(fh),
            }
            line = (r == nil) and req.encode_result(nil, code) or req.encode_result(code)
        end
        ffiutil.writeToFD(wfd, line, true)
    end, true)

    if not pid then return self:finish("error", { detail = fd }) end
    a.pid, a.fd, a.state = pid, fd, "fetching"
    self:pollFetch(gen)
end

function KindaFrame:pollFetch(gen)
    if self:stale(gen) then return end
    local a = self.session:active()
    if a.pid and ffiutil.isSubProcessDone(a.pid) then
        local line = ffiutil.readAllFromFD(a.fd) -- child exited: EOF is immediate; closes fd
        a.pid, a.fd = nil, nil
        local ok, err = pcall(self.accept, self, gen, line)
        if not ok then
            os.remove(PART)
            self:finish("error", { detail = err })
        end
        return
    end
    if self.session:expired() then
        os.remove(PART)
        return self:finish("timeout", { detail = "download" })
    end
    UIManager:scheduleIn(POLL_S, self.pollFetch, self, gen)
end

function KindaFrame:accept(gen, line)
    local a = self.session:active()
    local outcome, detail = req.classify(line)
    if outcome ~= "ok" then
        os.remove(PART)
        return self:finish(outcome, { detail = detail })
    end
    local ok, why = pngcheck.check_file(PART, a.w, a.h)
    if not ok then
        os.remove(PART)
        return self:finish("invalid", { detail = why })
    end
    local data = read_all(PART) or ""
    a.bytes = #data
    if data == read_all(CURRENT) then
        os.remove(PART)
        return self:finish("unchanged") -- same frame: no second flash
    end

    local f = io.open(PART, "rb")
    if f then ffiutil.fsyncOpenedFile(f); f:close() end
    local renamed, err = os.rename(PART, CURRENT)
    if not renamed then
        os.remove(PART)
        return self:finish("error", { detail = err })
    end

    if a.kind ~= "sleep" then return self:finish("new_frame") end
    if not (self.session:is_current(gen) and Device.screen_saver_mode) then
        return self:finish("new_frame", { detail = "saved; awake, no redraw" })
    end
    local redrawn, rwhy = self:redraw()
    a.state = "settling"
    UIManager:scheduleIn(SETTLE_S, function()
        if self.session:active() == a then
            -- NB: not `redrawn and nil or ...` (that idiom always yields the right-hand side when the middle is nil)
            local detail
            if not redrawn then detail = "no redraw: " .. tostring(rwhy) end
            self:finish("new_frame", { detail = detail })
        end
    end)
end

--- Swap the image inside KOReader's own sleep-screen widget (research R5, M1b).
-- Never closes the widget: ScreenSaverWidget:onCloseWidget would run Screensaver:cleanup()
-- and repaint the whole screen (the book) mid-sleep.
function KindaFrame:redraw()
    local Screensaver = require("ui/screensaver")
    local ssw = Screensaver.screensaver_widget
    local frame = ssw and ssw[1]
    local old = frame and frame[1]
    if not (old and old.file) then
        return false, "sleep screen is not a plain image (" .. tostring(old and old.name) .. ")"
    end
    local ImageWidget = require("ui/widget/imagewidget")
    frame[1] = ImageWidget:new{
        file = CURRENT, file_do_cache = false,
        width = Screen:getWidth(), height = Screen:getHeight(),
        scale_factor = 0, alpha = true,
    }
    ssw.widget = frame[1]
    old:free()
    UIManager:setDirty(ssw, function() return "full", frame.dimen end)
    UIManager:forceRePaint()
    UIManager:waitForVSync()
    return true
end

function KindaFrame:killChild(a)
    if a.pid then
        local pid = a.pid
        ffiutil.terminateSubProcess(pid)
        -- Reap the zombie a bit later (SIGKILL is asynchronous).
        UIManager:scheduleIn(1, function() ffiutil.isSubProcessDone(pid) end)
        a.pid = nil
    end
    if a.fd then
        close_fd(a.fd)
        a.fd = nil
    end
end

function KindaFrame:finish(outcome, extra)
    local a = self.session:finish(outcome)
    if not a then return end
    self:killChild(a)
    if a.turned_on then
        pcall(NetworkMgr.turnOffWifi, NetworkMgr) -- we switched it on, so switch it off again (D7)
    end
    local fields = {
        kind = a.kind, outcome = outcome, ms = a.ms, bytes = a.bytes,
        wifi_before = a.wifi_before,
        -- What we left it as: off if we had to turn it on, otherwise untouched.
        wifi_after = (not a.turned_on) and wifi_is_on() or false,
        detail = extra and extra.detail,
    }
    self:log(fields)
    save("last", fields.outcome .. (fields.detail and (" (" .. tostring(fields.detail) .. ")") or "")
        .. " @ " .. os.date("%H:%M:%S"))
    if a.kind == "manual" then
        UIManager:show(InfoMessage:new{
            text = T(_("Kinda Frame: %1"), outcome == "new_frame" and _("new frame saved")
                or outcome == "unchanged" and _("frame unchanged") or outcome),
            timeout = 3,
        })
    end
end

-- ---------------------------------------------------------------------------
-- Menu (FR-020)
-- ---------------------------------------------------------------------------

function KindaFrame:fetchNow()
    if self.session:active() then
        UIManager:show(InfoMessage:new{ text = _("Kinda Frame: a fetch is already running."), timeout = 2 })
        return
    end
    local ok, err = pcall(self.startAttempt, self, self.session.gen, "manual")
    if not ok then self:finish("error", { detail = err }) end
end

function KindaFrame:editUrl(touchmenu_instance)
    local dialog
    dialog = InputDialog:new{
        title = _("Kinda Frame server URL"),
        input = setting("server_url", "http://"),
        description = _("Plain http on your LAN. Use an IP address, not a hostname, e.g. http://192.168.1.50:8787/frame.png"),
        buttons = { {
            { text = _("Cancel"), id = "close", callback = function() UIManager:close(dialog) end },
            { text = _("Save"), is_enter_default = true, callback = function()
                local v = dialog:getInputText():gsub("^%s+", ""):gsub("%s+$", "")
                if not req.valid_base(v) then
                    UIManager:show(InfoMessage:new{ text = _("The URL must start with http://"), timeout = 3 })
                    return
                end
                save("server_url", v)
                UIManager:close(dialog)
                if touchmenu_instance then touchmenu_instance:updateItems() end
            end },
        } },
    }
    UIManager:show(dialog)
    dialog:onShowKeyboard()
end

local ORIENT_LABELS = {
    { "portrait", _("Portrait (upright)") },
    { "left", _("Landscape, resting on left edge") },
    { "right", _("Landscape, resting on right edge") },
}

function KindaFrame:orientMenu()
    local items = {}
    for _i, o in ipairs(ORIENT_LABELS) do
        local key, label = o[1], o[2]
        items[#items + 1] = {
            text = label,
            radio = true,
            checked_func = function() return setting("orient", "portrait") == key end,
            callback = function()
                if setting("orient", "portrait") == key then return end
                save("orient", key)
                -- Fetch right away so the very next sleep already opens in the new orientation.
                if req.valid_base(setting("server_url")) then self:fetchNow() end
            end,
        }
    end
    return items
end

function KindaFrame:addToMainMenu(menu_items)
    menu_items.kinda_frame = {
        text = _("Kinda Frame"),
        sorting_hint = "more_tools",
        sub_item_table = {
            {
                text = _("Refresh on sleep"),
                checked_func = function() return setting("enabled", false) end,
                callback = function() save("enabled", not setting("enabled", false)) end,
            },
            {
                text_func = function() return T(_("Server URL: %1"), setting("server_url") or _("not set")) end,
                keep_menu_open = true,
                callback = function(touchmenu_instance) self:editUrl(touchmenu_instance) end,
            },
            {
                text_func = function()
                    local cur = setting("orient", "portrait")
                    for _i, o in ipairs(ORIENT_LABELS) do
                        if o[1] == cur then return T(_("Frame orientation: %1"), o[2]) end
                    end
                    return _("Frame orientation")
                end,
                sub_item_table = self:orientMenu(),
            },
            {
                text_func = function() return T(_("Fetch budget: %1 s (tap to change)"), budget.clamp(setting("budget_s"))) end,
                keep_menu_open = true,
                callback = function(touchmenu_instance)
                    local nxt = { [15] = 25, [25] = 40, [40] = 15 }
                    save("budget_s", nxt[budget.clamp(setting("budget_s"))] or budget.DEFAULT_BUDGET)
                    touchmenu_instance:updateItems()
                end,
            },
            {
                text_func = function()
                    return T(_("Sleep window: %1 s, margin %2 s (measured)"),
                        setting("window_s", budget.DEFAULT_WINDOW), setting("margin_s", budget.DEFAULT_MARGIN))
                end,
                enabled_func = function() return false end,
                separator = true,
            },
            {
                text = _("Fetch now"),
                callback = function() self:fetchNow() end,
            },
            {
                text = _("Last fetch status"),
                keep_menu_open = true,
                callback = function()
                    local lines = fetchlog.tail(LOGFILE, 8)
                    UIManager:show(InfoMessage:new{
                        text = #lines > 0 and table.concat(lines, "\n") or _("No fetch yet."),
                    })
                end,
            },
        },
    }
end

return KindaFrame
