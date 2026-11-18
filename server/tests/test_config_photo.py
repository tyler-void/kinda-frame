import random

import pytest

from kindaframe import config, photo
from kindaframe.imaging import grey16

from .conftest import H, W


def test_defaults_are_art_with_all_generators(tmp_path):
    cfg = config.load(tmp_path / "missing.toml")
    assert cfg.mode == "art" and cfg.art.generators == config.ALL_GENERATORS


def test_load_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('mode = "photo"\n[art]\ngenerators = ["chladni"]\norder = "cycle"\n'
                 '[photo]\ndir = "/x"\norder = "sequential"\nfit = "pad"\n')
    cfg = config.load(p)
    assert cfg.mode == "photo" and cfg.art.generators == ("chladni",) and cfg.art.order == "cycle"
    assert str(cfg.photo.dir) == "/x" and cfg.photo.order == "sequential" and cfg.photo.fit == "pad"


@pytest.mark.parametrize("data", [
    {"mode": "dashboard"},
    {"art": {"generators": ["nope"]}},
    {"art": {"generators": []}},
    {"art": {"order": "shuffle"}},
    {"photo": {"fit": "stretch"}},
])
def test_invalid_config_is_rejected(data):
    with pytest.raises(config.ConfigError):
        config.parse(data)


def test_list_photos_skips_non_images_and_hidden(photo_dir):
    assert [p.name for p in photo.list_photos(photo_dir)] == ["a_portrait.png", "b_landscape.jpg"]


def test_sequential_order_cycles_and_persists(photo_dir, tmp_path):
    cfg = config.PhotoConfig(dir=photo_dir, order="sequential")
    state = tmp_path / "state"
    seen = [photo.pick(cfg, state, random.Random(0))[1] for _ in range(5)]
    assert seen == [0, 1, 0, 1, 0]
    assert (state / "photo_cursor.json").is_file()


def test_empty_folder_raises(tmp_path):
    with pytest.raises(photo.NoPhotos):
        photo.pick(config.PhotoConfig(dir=tmp_path / "none"), tmp_path, random.Random(0))


def test_photo_render_exact_size_on_palette(photo_dir):
    for p in photo.list_photos(photo_dir):
        for mode in ("crop", "pad"):
            img = photo.render(p, W, H, mode)
            assert img.size == (W, H) and grey16.levels_used(img) <= set(grey16.LEVELS)
