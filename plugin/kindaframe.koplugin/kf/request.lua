--[[--
Request URL building and child-process result protocol (contracts/frame-api.md).

The download runs in a forked child; it reports back over a pipe with one short line:
  "HTTP <code>"   the request completed with that status (body is in the .part file)
  "ERR <message>" the request failed (DNS, connect, timeout, ...)

Pure: no KOReader imports (unit-tested in spec/request_spec.lua).
--]]

local M = {}

function M.valid_base(url)
    return type(url) == "string" and url:match("^http://[^/%s]+") ~= nil
end

M.ORIENTS = { portrait = true, left = true, right = true }

--- Append w, h, (optionally) batt and orient to the configured URL, keeping any existing query.
-- orient: "portrait" (default, not sent), "left" (resting on its left edge), "right".
function M.build_url(base, w, h, batt, orient)
    local q = string.format("w=%d&h=%d", w, h)
    if batt then q = q .. string.format("&batt=%d", math.max(0, math.min(100, math.floor(batt)))) end
    if orient and orient ~= "portrait" and M.ORIENTS[orient] then q = q .. "&orient=" .. orient end
    local sep = base:find("?", 1, true) and "&" or "?"
    return base .. sep .. q
end

function M.encode_result(code, err)
    if code then return "HTTP " .. tostring(code) end
    return "ERR " .. tostring(err or "unknown"):gsub("[\r\n]", " ")
end

--- @return outcome, detail   where outcome is "ok" | "http_<code>" | "unreachable" | "timeout"
function M.classify(line)
    if type(line) ~= "string" or line == "" then return "unreachable", "no result from child" end
    local code = line:match("^HTTP (%d+)")
    if code then
        if code == "200" then return "ok" end
        return "http_" .. code
    end
    local err = line:match("^ERR (.*)$") or line
    if err:lower():find("timeout", 1, true) then return "timeout", err end
    return "unreachable", err
end

return M
