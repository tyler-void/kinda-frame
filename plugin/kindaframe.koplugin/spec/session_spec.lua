local Session = require("kf/session")

describe("session", function()
    local t, s
    before_each(function()
        t = 100
        s = Session.new(function() return t end)
    end)

    it("bumps the generation on suspend and resume", function()
        local g = s:on_suspend()
        assert_true(s:is_current(g))
        s:on_resume()
        assert_false(s:is_current(g), "a pending step from before the wake must see a stale generation")
    end)

    it("allows only one attempt at a time", function()
        local g = s:on_suspend()
        assert_true(s:begin(g, 25) ~= nil)
        assert_nil(s:begin(g, 25))
    end)

    it("tracks the deadline", function()
        local g = s:on_suspend()
        s:begin(g, 25)
        t = 120; assert_false(s:expired()); assert_eq(s:remaining(), 5)
        t = 125; assert_true(s:expired())
    end)

    it("finishes exactly once (single Wi-Fi restore / log line)", function()
        local g = s:on_suspend()
        s:begin(g, 25, { wifi_before = false })
        t = 103.5
        local a = s:finish("new_frame")
        assert_eq(a.outcome, "new_frame"); assert_eq(a.ms, 3500); assert_false(a.wifi_before)
        assert_nil(s:finish("timeout"), "second finish must be a no-op")
        assert_nil(s:active())
    end)

    it("a new attempt can start after the previous one finished", function()
        local g = s:on_suspend(); s:begin(g, 25); s:finish("timeout")
        s:on_resume(); g = s:on_suspend()
        assert_true(s:begin(g, 25) ~= nil)
    end)
end)
