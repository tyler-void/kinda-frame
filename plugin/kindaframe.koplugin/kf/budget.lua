--[[--
Fetch budget maths (spec FR-007, data-model "Device settings").

Effective budget = min(configured budget, measured window - margin), with the configured
budget clamped to [MIN_BUDGET, MAX_BUDGET]. Returns nil when there is no usable window:
the plugin then shows the saved frame only and doesn't fetch.

Pure: no KOReader imports (unit-tested in spec/budget_spec.lua).
--]]

local M = {
    MIN_BUDGET = 3,
    MAX_BUDGET = 60,
    MIN_USEFUL = 2, -- below this, a fetch can't realistically finish: don't start one
    DEFAULT_BUDGET = 25,
    DEFAULT_WINDOW = 60, -- measured SCREEN SAVER dwell (docs/device-probe.md)
    DEFAULT_MARGIN = 5,
}

function M.clamp(budget_s)
    budget_s = tonumber(budget_s) or M.DEFAULT_BUDGET
    if budget_s < M.MIN_BUDGET then return M.MIN_BUDGET end
    if budget_s > M.MAX_BUDGET then return M.MAX_BUDGET end
    return budget_s
end

--- @return number|nil seconds the whole attempt (Wi-Fi up + download) may take
function M.effective(budget_s, window_s, margin_s)
    window_s = tonumber(window_s)
    if not window_s then return nil end
    margin_s = tonumber(margin_s) or M.DEFAULT_MARGIN
    local eff = math.min(M.clamp(budget_s), window_s - margin_s)
    if eff <= M.MIN_USEFUL then return nil end
    return eff
end

return M
