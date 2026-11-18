--[[--
Per-sleep bookkeeping (data-model "Fetch state machine").

* A generation counter bumped on every suspend AND resume. Async steps capture the generation
  when scheduled and drop out if it changed: that's how "woke up mid-fetch" cancels pending
  work and, above all, any late redraw (FR-011).
* At most one attempt at a time. `finish` is idempotent, so the Wi-Fi restore + log line
  happens exactly once per attempt, whichever path ends it (FR-012, FR-013).
* powerd's own RTC self-wakes (`WakeupFromSuspend`) are NOT fed in here: only onSuspend/onResume.

Pure: time is injected (unit-tested in spec/session_spec.lua).
--]]

local Session = {}
Session.__index = Session

--- @param now function returning seconds (float)
function Session.new(now)
    return setmetatable({ gen = 0, attempt = nil, now = now or os.time }, Session)
end

function Session:on_suspend()
    self.gen = self.gen + 1
    return self.gen
end

function Session:on_resume()
    self.gen = self.gen + 1
    return self.gen
end

function Session:is_current(gen)
    return gen == self.gen
end

--- Start an attempt. Returns nil if one is already running.
-- @param budget seconds
-- @param fields table merged into the attempt (e.g. wifi_before, kind)
function Session:begin(gen, budget, fields)
    if self.attempt then return nil end
    local t = self.now()
    local a = { gen = gen, started = t, deadline = t + budget, state = "starting" }
    for k, v in pairs(fields or {}) do a[k] = v end
    self.attempt = a
    return a
end

function Session:active()
    return self.attempt
end

function Session:remaining()
    if not self.attempt then return 0 end
    return self.attempt.deadline - self.now()
end

function Session:expired()
    return self.attempt ~= nil and self.now() >= self.attempt.deadline
end

--- End the current attempt exactly once.
-- @return the finished attempt (with outcome, ms) or nil if nothing was running
function Session:finish(outcome)
    local a = self.attempt
    if not a then return nil end
    self.attempt = nil
    a.outcome = outcome
    a.ms = math.floor((self.now() - a.started) * 1000 + 0.5)
    return a
end

return Session
