from PIL import Image

from kindaframe.imaging import fit, grey16

from .conftest import H, W


def test_levels_are_the_16_device_greys():
    assert grey16.LEVELS == tuple(range(0, 256, 17))


def test_quantize_dithered_and_plain_stay_on_palette():
    grad = Image.linear_gradient("L").resize((W, H))
    for dither in (True, False):
        q = grey16.quantize(grad, dither=dither)
        assert q.mode == "L" and q.size == (W, H)
        assert grey16.levels_used(q) <= set(grey16.LEVELS)
    assert len(grey16.levels_used(grey16.quantize(grad, dither=False))) == 16


def test_quantize_is_identity_on_palette_images():
    q = grey16.quantize(Image.linear_gradient("L").resize((64, 64)), dither=True)
    assert grey16.quantize(q, dither=False).tobytes() == q.tobytes()


def test_fit_crop_and_pad_hit_exact_size():
    src = Image.new("RGB", (1600, 900), "gray")
    for mode in ("crop", "pad"):
        out = fit.fit(src, W, H, mode)
        assert out.size == (W, H) and out.mode == "L"


def test_pad_letterboxes_on_white():
    out = fit.fit(Image.new("L", (1600, 900), 0), W, H, "pad")
    assert out.getpixel((W // 2, 5)) == 255  # top band is paper, not ink


def test_png_roundtrip():
    img = grey16.quantize(Image.new("L", (10, 10), 120))
    assert grey16.to_png(img).startswith(b"\x89PNG\r\n\x1a\n")
