--[[--
Cheap PNG validation without decoding (contracts/frame-api.md "Client obligations", FR-010).

A frame is accepted only if: non-empty, starts with the 8-byte PNG signature, the first chunk
is IHDR, and the IHDR width/height equal the size we asked for.

Pure: no KOReader imports (unit-tested in spec/pngcheck_spec.lua).
--]]

local M = {}

M.SIGNATURE = "\137PNG\r\n\026\n"

local function be32(s, i)
    local a, b, c, d = s:byte(i, i + 3)
    return ((a * 256 + b) * 256 + c) * 256 + d
end

--- Parse the first 24 bytes of a PNG.
-- @return width, height  or  nil, reason
function M.dimensions(head)
    if type(head) ~= "string" or #head == 0 then return nil, "empty" end
    if #head < 24 then return nil, "too short" end
    if head:sub(1, 8) ~= M.SIGNATURE then return nil, "not a PNG" end
    if head:sub(13, 16) ~= "IHDR" then return nil, "no IHDR" end
    return be32(head, 17), be32(head, 21)
end

--- @return true  or  false, reason
function M.check(head, want_w, want_h)
    local w, h = M.dimensions(head)
    if not w then return false, h end
    if w ~= want_w or h ~= want_h then
        return false, string.format("size %dx%d, expected %dx%d", w, h, want_w, want_h)
    end
    return true
end

--- File variant: reads only the first 24 bytes.
function M.check_file(path, want_w, want_h)
    local f = io.open(path, "rb")
    if not f then return false, "cannot open" end
    local head = f:read(24)
    f:close()
    return M.check(head or "", want_w, want_h)
end

return M
