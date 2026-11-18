--[[--
Minimal busted-style test runner (no dependencies): `luajit spec/run.lua` from the plugin root.

Supports describe / it / before_each and assert_eq / assert_true / assert_false / assert_nil.
Specs are the files spec/*_spec.lua listed below: pure kf/ modules, plus main_spec (main.lua against stubbed KOReader).
--]]

package.path = "./?.lua;" .. package.path

local SPECS = { "budget", "pngcheck", "session", "fetchlog", "request", "main" }

local passed, failed, current, befores = 0, 0, {}, {}

local function name() return table.concat(current, " › ") end

function describe(label, fn)
    current[#current + 1] = label
    local saved = #befores
    fn()
    for i = #befores, saved + 1, -1 do befores[i] = nil end
    current[#current] = nil
end

function before_each(fn) befores[#befores + 1] = fn end

function it(label, fn)
    current[#current + 1] = label
    for _, b in ipairs(befores) do b() end
    local ok, err = xpcall(fn, debug.traceback)
    if ok then
        passed = passed + 1
    else
        failed = failed + 1
        io.stderr:write("FAIL ", name(), "\n  ", tostring(err), "\n")
    end
    current[#current] = nil
end

local function fmt(v) return type(v) == "string" and string.format("%q", v) or tostring(v) end

function assert_eq(actual, expected, msg)
    if actual ~= expected then
        error(string.format("%sexpected %s, got %s", msg and (msg .. ": ") or "", fmt(expected), fmt(actual)), 2)
    end
end
function assert_true(v, msg) if v ~= true then error((msg or "expected true") .. ", got " .. fmt(v), 2) end end
function assert_false(v, msg) if v ~= false then error((msg or "expected false") .. ", got " .. fmt(v), 2) end end
function assert_nil(v, msg) if v ~= nil then error((msg or "expected nil") .. ", got " .. fmt(v), 2) end end

for _, s in ipairs(SPECS) do
    dofile("spec/" .. s .. "_spec.lua")
end

print(string.format("%d passed, %d failed", passed, failed))
os.exit(failed == 0 and 0 or 1)
