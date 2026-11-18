--[[--
Scenario tests for main.lua (the KOReader glue), run on the dev machine with stubbed KOReader modules:
a virtual clock driving UIManager:scheduleIn, a fake Wi-Fi radio, a fake forked child whose
"download" finishes after a configurable delay, and a fake HTTP response.

Covers spec Story 2/3 acceptance scenarios: new frame + redraw, Wi-Fi restore, unchanged, invalid,
HTTP error, unreachable, timeouts, wake mid-fetch (no late redraw), manual fetch, disabled, no URL.
--]]

local unpack = unpack or table.unpack

-- ---------------------------------------------------------------- harness state
local H

local function reset_harness()
    H = {
        clock = 0, tasks = {},
        wifi = { on = true, connected = true, connect_delay = 2, enable_calls = 0, off_calls = 0 },
        http = { code = 200, body = nil, err = nil, delay = 1, urls = {} },
        repaints = 0, shown = {}, kills = 0,
        settings = {},
        pipes = {}, children = {},
        screen_saver_mode = true,
    }
end
reset_harness()

local function schedule(at, fn, args) H.tasks[#H.tasks + 1] = { t = at, fn = fn, args = args, seq = #H.tasks } end

local function advance(dt)
    local target = H.clock + dt
    while true do
        table.sort(H.tasks, function(a, b) if a.t == b.t then return a.seq < b.seq end return a.t < b.t end)
        local task = H.tasks[1]
        if not task or task.t > target then break end
        table.remove(H.tasks, 1)
        H.clock = task.t
        task.fn(unpack(task.args))
    end
    H.clock = target
end

-- ---------------------------------------------------------------- KOReader stubs
local function stub(name, value) package.loaded[name] = value end

stub("gettext", setmetatable({}, { __call = function(_, s) return s end }))
stub("logger", { info = function() end, warn = function() end, dbg = function() end })
stub("ui/time", { monotonic = function() return H.clock end, to_s = function(t) return t end })
stub("ui/widget/infomessage", { new = function(_, o) o.kind = "InfoMessage"; return o end })
stub("ui/widget/inputdialog", { new = function(_, o) return o end })
stub("ui/widget/container/widgetcontainer", {
    extend = function(self, o) return setmetatable(o, { __index = self }) end,
})
stub("ui/uimanager", {
    scheduleIn = function(_, s, fn, ...) schedule(H.clock + s, fn, { ... }) end,
    unschedule = function() end,
    show = function(_, w) H.shown[#H.shown + 1] = w end,
    close = function() end,
    setDirty = function() end,
    forceRePaint = function() H.repaints = H.repaints + 1 end,
    waitForVSync = function() end,
})
stub("ui/network/manager", {
    isWifiOn = function() return H.wifi.on end,
    isConnected = function() return H.wifi.on and H.wifi.connected end,
    restoreWifiAsync = function()
        H.wifi.enable_calls = H.wifi.enable_calls + 1
        H.wifi.on = true
        if H.wifi.connect_delay then
            schedule(H.clock + H.wifi.connect_delay, function() H.wifi.connected = true end, {})
        end
    end,
    turnOffWifi = function()
        H.wifi.off_calls = H.wifi.off_calls + 1
        H.wifi.on, H.wifi.connected = false, false
    end,
})
stub("device", {
    screen = { getWidth = function() return 1072 end, getHeight = function() return 1448 end },
    getPowerDevice = function() return { getCapacity = function() return 84 end } end,
})
setmetatable(package.loaded["device"], {
    __index = function(_, k) if k == "screen_saver_mode" then return H.screen_saver_mode end end,
})
stub("ui/widget/imagewidget", {
    new = function(_, o) o.free = function() end; return o end,
})
stub("ui/screensaver", {})
stub("ffi/util", {
    template = function(s, ...)
        local args = { ... }
        return (s:gsub("%%(%d)", function(i) return tostring(args[tonumber(i)]) end))
    end,
    runInSubProcess = function(func)
        local pid = #H.children + 1
        local fd = 100 + pid
        H.children[pid] = { done_at = H.clock + H.http.delay }
        func(pid, fd) -- the "child" runs now; it only counts as finished at done_at
        return pid, fd
    end,
    isSubProcessDone = function(pid)
        local c = H.children[pid]
        return c.killed or H.clock >= c.done_at
    end,
    terminateSubProcess = function(pid) H.children[pid].killed = true; H.kills = H.kills + 1 end,
    writeToFD = function(fd, data) H.pipes[fd] = data; return true end,
    readAllFromFD = function(fd) return H.pipes[fd] or "" end,
    fsyncOpenedFile = function() end,
})
stub("socketutil", {
    set_timeout = function() end,
    file_sink = function(fh)
        return function(chunk) if chunk then fh:write(chunk) else fh:close() end return 1 end
    end,
})
stub("socket.http", {
    request = function(t)
        H.http.urls[#H.http.urls + 1] = t.url
        if H.http.err then return nil, H.http.err end
        if H.http.body then t.sink(H.http.body) end
        t.sink(nil)
        return 1, H.http.code
    end,
})

G_reader_settings = {
    readSetting = function(_, k) return H.settings[k] end,
    saveSetting = function(_, k, v) H.settings[k] = v end,
}

-- ---------------------------------------------------------------- helpers
local function be32(n)
    return string.char(math.floor(n / 16777216) % 256, math.floor(n / 65536) % 256, math.floor(n / 256) % 256, n % 256)
end
local function png(w, h, tag)
    return "\137PNG\r\n\026\n" .. be32(13) .. "IHDR" .. be32(w) .. be32(h) .. "\8\0\0\0\0" .. (tag or "")
end
local function read(path)
    local f = io.open(path, "rb"); if not f then return nil end
    local d = f:read("*a"); f:close(); return d
end
local function write(path, d) local f = io.open(path, "wb"); f:write(d); f:close() end
local function exists(path) local f = io.open(path, "rb"); if f then f:close() return true end return false end

local TMP = os.tmpname()
os.remove(TMP)
os.execute("mkdir -p " .. TMP)
local CURRENT, PART, LOG = TMP .. "/current.png", TMP .. "/current.png.part", TMP .. "/kindaframe.log"
local OLD = png(1072, 1448, "old-frame")
local NEW = png(1072, 1448, "new-frame")

local KindaFrame = dofile("main.lua")
KindaFrame._set_base(TMP)

local plugin
local function fresh()
    reset_harness()
    write(CURRENT, OLD)
    os.remove(PART); os.remove(LOG); os.remove(LOG .. ".1")
    H.settings.kindaframe_enabled = true
    H.settings.kindaframe_server_url = "http://192.168.1.60:8787/frame.png"
    H.http.body = NEW
    package.loaded["ui/screensaver"].screensaver_widget = { [1] = { [1] = { file = CURRENT, free = function() end }, dimen = {} } }
    plugin = setmetatable({ ui = { menu = { registerToMainMenu = function() end } } }, { __index = KindaFrame })
    plugin:init()
end

local function log_lines()
    local t = {}
    local f = io.open(LOG, "r"); if not f then return t end
    for l in f:lines() do t[#t + 1] = l end
    f:close(); return t
end
local function only_log() local l = log_lines(); assert_eq(#l, 1, "exactly one log line per attempt"); return l[1] end
local function has(line, s) assert_true(line:find(s, 1, true) ~= nil, "log line should contain " .. s .. ": " .. line) end

-- ---------------------------------------------------------------- scenarios
describe("main: sleep with Wi-Fi already connected", function()
    before_each(fresh)
    it("downloads, swaps current.png, redraws, logs once, leaves Wi-Fi alone", function()
        plugin:onSuspend()
        advance(5)
        assert_eq(read(CURRENT), NEW)
        assert_false(exists(PART))
        assert_eq(H.repaints, 1)
        assert_eq(H.wifi.enable_calls, 0); assert_eq(H.wifi.off_calls, 0)
        local l = only_log()
        has(l, "outcome=new_frame"); has(l, "wifi_before=on"); has(l, "wifi_after=on"); has(l, "kind=sleep")
        assert_true(l:find("detail=", 1, true) == nil, "a successful redraw has no detail: " .. l)
        assert_eq(H.http.urls[1], "http://192.168.1.60:8787/frame.png?w=1072&h=1448&batt=84")
    end)
    it("sleep screen that is not a plain image (e.g. message mode): saved, logged as no redraw", function()
        package.loaded["ui/screensaver"].screensaver_widget = { [1] = { [1] = { name = "OverlapGroup" }, dimen = {} } }
        plugin:onSuspend(); advance(5)
        assert_eq(read(CURRENT), NEW); assert_eq(H.repaints, 0)
        has(only_log(), "detail=no_redraw:_sleep_screen_is_not_a_plain_image_(OverlapGroup)")
    end)
    it("same bytes as the saved frame: no rename, no redraw (no second flash)", function()
        H.http.body = OLD
        plugin:onSuspend(); advance(5)
        assert_eq(H.repaints, 0)
        has(only_log(), "outcome=unchanged")
    end)
    it("rejects a wrong-size PNG and keeps the old frame", function()
        H.http.body = png(1448, 1072, "rotated")
        plugin:onSuspend(); advance(5)
        assert_eq(read(CURRENT), OLD); assert_false(exists(PART)); assert_eq(H.repaints, 0)
        local l = only_log(); has(l, "outcome=invalid"); has(l, "detail=size_1448x1072")
    end)
    it("rejects a non-PNG body", function()
        H.http.body = "<html>oops</html>" .. string.rep(" ", 40)
        plugin:onSuspend(); advance(5)
        assert_eq(read(CURRENT), OLD); has(only_log(), "outcome=invalid")
    end)
    it("HTTP 503 keeps the old frame", function()
        H.http.code = 503
        plugin:onSuspend(); advance(5)
        assert_eq(read(CURRENT), OLD); has(only_log(), "outcome=http_503")
    end)
    it("server unreachable keeps the old frame", function()
        H.http.err = "connection refused"
        plugin:onSuspend(); advance(5)
        assert_eq(read(CURRENT), OLD); has(only_log(), "outcome=unreachable")
    end)
    it("slow download is killed at the budget (25 s) and nothing is left running", function()
        H.http.delay = 100
        plugin:onSuspend(); advance(24)
        assert_eq(#log_lines(), 0, "still within budget")
        advance(2)
        assert_eq(H.kills, 1); assert_false(exists(PART)); assert_eq(read(CURRENT), OLD)
        local l = only_log(); has(l, "outcome=timeout"); has(l, "detail=download")
        advance(60); assert_eq(#log_lines(), 1, "no further activity after finish")
    end)
end)

describe("main: sleep with Wi-Fi off", function()
    before_each(function() fresh(); H.wifi.on, H.wifi.connected = false, false end)
    it("turns Wi-Fi on quietly, fetches, turns it off again exactly once", function()
        plugin:onSuspend(); advance(10)
        assert_eq(H.wifi.enable_calls, 1); assert_eq(H.wifi.off_calls, 1); assert_false(H.wifi.on)
        assert_eq(read(CURRENT), NEW)
        local l = only_log(); has(l, "outcome=new_frame"); has(l, "wifi_before=off"); has(l, "wifi_after=off")
        assert_eq(#H.shown, 0, "no pop-ups during sleep")
    end)
    it("network never comes up: timeout at the budget, Wi-Fi switched off again", function()
        H.wifi.connect_delay = nil
        plugin:onSuspend(); advance(30)
        assert_eq(H.wifi.off_calls, 1); assert_false(H.wifi.on)
        local l = only_log(); has(l, "outcome=timeout"); has(l, "detail=wifi")
    end)
end)

describe("main: waking up mid-attempt (FR-011)", function()
    before_each(fresh)
    it("cancels, deletes .part, never redraws over the book, restores Wi-Fi", function()
        H.wifi.on, H.wifi.connected = false, false
        H.http.delay = 5
        plugin:onSuspend(); advance(3) -- connected at t=2, download running
        H.screen_saver_mode = false
        plugin:onResume()
        advance(30)
        assert_eq(H.repaints, 0, "no late redraw")
        assert_eq(read(CURRENT), OLD)
        assert_false(exists(PART))
        assert_eq(H.wifi.off_calls, 1)
        local l = only_log(); has(l, "outcome=cancelled_wake"); has(l, "detail=fetching")
    end)
    it("sleep screen gone without a resume event: frame saved, but never redrawn (defense in depth)", function()
        H.http.delay = 3
        plugin:onSuspend(); advance(1)
        H.screen_saver_mode = false -- e.g. KOReader closed the screensaver some other way
        advance(10)
        assert_eq(H.repaints, 0, "must not paint over whatever is on screen now")
        assert_eq(read(CURRENT), NEW, "the frame is still saved for the next sleep")
        local l = only_log(); has(l, "outcome=new_frame"); has(l, "detail=saved;_awake,_no_redraw")
    end)
    it("a wake before Wi-Fi connects also cancels cleanly", function()
        H.wifi.on, H.wifi.connected = false, false
        plugin:onSuspend(); advance(1)
        plugin:onResume(); advance(30)
        assert_eq(#H.http.urls, 0, "never fetched")
        has(only_log(), "detail=connecting")
    end)
    it("next sleep after a cancelled one works normally", function()
        H.http.delay = 5
        plugin:onSuspend(); advance(1); plugin:onResume(); advance(1)
        H.http.delay = 1
        plugin:onSuspend(); advance(5)
        local l = log_lines()
        assert_eq(#l, 2); has(l[2], "outcome=new_frame")
        assert_eq(read(CURRENT), NEW)
    end)
end)

describe("main: settings and manual fetch", function()
    before_each(fresh)
    it("disabled: no fetch and no log line", function()
        H.settings.kindaframe_enabled = false
        plugin:onSuspend(); advance(30)
        assert_eq(#H.http.urls, 0); assert_eq(#log_lines(), 0)
    end)
    it("no valid URL: logged as skipped", function()
        H.settings.kindaframe_server_url = "https://example.org/x.png"
        plugin:onSuspend(); advance(5)
        has(only_log(), "outcome=skipped_no_url")
    end)
    it("window too small to be useful: skipped", function()
        H.settings.kindaframe_window_s = 6
        plugin:onSuspend(); advance(5)
        has(only_log(), "outcome=skipped_no_window")
    end)
    it("sends the orientation setting with every request", function()
        H.settings.kindaframe_orient = "left"
        plugin:onSuspend(); advance(5)
        assert_eq(H.http.urls[1], "http://192.168.1.60:8787/frame.png?w=1072&h=1448&batt=84&orient=left")
    end)
    it("changing the orientation in the menu saves it and fetches immediately", function()
        H.screen_saver_mode = false
        local items = plugin:orientMenu()
        items[3].callback() -- right edge
        advance(5)
        assert_eq(H.settings.kindaframe_orient, "right")
        assert_true(H.http.urls[1]:find("orient=right", 1, true) ~= nil)
        has(only_log(), "kind=manual")
        items[3].callback() -- same choice again: no extra fetch
        advance(5)
        assert_eq(#H.http.urls, 1)
    end)
    it("every menu entry renders: all text_func / checked_func / enabled_func run without error", function()
        -- Regression: a loop variable named `_` shadowed gettext and crashed KOReader when the menu opened.
        local items = {}
        plugin:addToMainMenu(items)
        local count = 0
        local function walk(list)
            for _i, item in ipairs(list) do
                if item.text_func then assert_eq(type(item.text_func()), "string"); count = count + 1 end
                if item.checked_func then item.checked_func() end
                if item.enabled_func then item.enabled_func() end
                if item.sub_item_table then walk(item.sub_item_table) end
            end
        end
        for _orient, o in ipairs({ "portrait", "left", "right" }) do
            H.settings.kindaframe_orient = o
            walk(items.kinda_frame.sub_item_table)
        end
        assert_true(count >= 9, "text_func entries exercised")
    end)
    it("no loop variable shadows gettext's `_` in the plugin sources", function()
        for _i, f in ipairs({ "main.lua", "kf/budget.lua", "kf/fetchlog.lua", "kf/pngcheck.lua", "kf/request.lua", "kf/session.lua" }) do
            local src = read(f)
            assert_true(src:find("for%s+_%s*,") == nil, f .. " uses `for _,` (shadows gettext)")
        end
    end)
    it("Fetch now (awake): saves the frame, no redraw, shows a short message", function()
        H.screen_saver_mode = false
        plugin:fetchNow(); advance(5)
        assert_eq(read(CURRENT), NEW); assert_eq(H.repaints, 0)
        assert_eq(H.shown[#H.shown].kind, "InfoMessage")
        has(only_log(), "kind=manual")
    end)
    it("sleeping during a manual fetch abandons it and starts a sleep attempt", function()
        H.http.delay = 10
        H.screen_saver_mode = false
        plugin:fetchNow(); advance(1)
        H.screen_saver_mode = true
        H.http.delay = 1
        plugin:onSuspend(); advance(5)
        local l = log_lines()
        assert_eq(#l, 2); has(l[1], "outcome=cancelled_sleep"); has(l[2], "outcome=new_frame")
    end)
end)

os.execute("rm -rf " .. TMP)
