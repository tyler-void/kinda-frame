--[[--
One line per attempt, rotated at 64 KiB with one old generation kept (FR-013, data-model "Fetch attempt").

Line format (space-separated key=value after the timestamp, easy to grep):
  2026-11-20T21:14:03 outcome=new_frame ms=4210 wifi_before=on wifi_after=on bytes=30293 kind=sleep

Pure apart from file I/O (unit-tested in spec/fetchlog_spec.lua with a temp dir).
--]]

local M = { MAX_BYTES = 64 * 1024 }

local ORDER = { "outcome", "ms", "wifi_before", "wifi_after", "bytes", "kind", "detail" }

local function onoff(v)
    if v == true then return "on" elseif v == false then return "off" end
    return v
end

function M.format(ts, fields)
    local parts = { ts }
    for _i, k in ipairs(ORDER) do
        local v = fields[k]
        if v ~= nil then
            if k == "wifi_before" or k == "wifi_after" then v = onoff(v) end
            v = tostring(v):gsub("%s+", "_")
            parts[#parts + 1] = k .. "=" .. v
        end
    end
    return table.concat(parts, " ")
end

local function size_of(path)
    local f = io.open(path, "rb")
    if not f then return 0 end
    local n = f:seek("end") or 0
    f:close()
    return n
end

function M.append(path, line, max_bytes)
    max_bytes = max_bytes or M.MAX_BYTES
    if size_of(path) + #line + 1 > max_bytes then
        os.remove(path .. ".1")
        os.rename(path, path .. ".1")
    end
    local f = io.open(path, "a")
    if not f then return false end
    f:write(line, "\n")
    f:close()
    return true
end

--- Last n lines (for the "Last fetch status" menu entry).
function M.tail(path, n)
    local lines = {}
    local f = io.open(path, "r")
    if not f then return lines end
    for line in f:lines() do
        lines[#lines + 1] = line
        if #lines > n then table.remove(lines, 1) end
    end
    f:close()
    return lines
end

return M
