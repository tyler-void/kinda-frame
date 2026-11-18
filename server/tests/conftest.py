from __future__ import annotations

import io

import pytest
from PIL import Image

W, H = 1072, 1448  # the Kindle PW4, as KOReader reports it


def decode(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


@pytest.fixture
def photo_dir(tmp_path):
    d = tmp_path / "photos"
    d.mkdir()
    # A landscape gradient with an EXIF-free orientation, and a small portrait one.
    Image.linear_gradient("L").resize((800, 500)).convert("RGB").save(d / "b_landscape.jpg")
    Image.radial_gradient("L").resize((300, 600)).save(d / "a_portrait.png")
    (d / "notes.txt").write_text("not an image")
    (d / ".hidden.jpg").write_bytes(b"")
    return d
