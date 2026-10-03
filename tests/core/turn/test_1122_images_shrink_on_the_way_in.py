"""#1122: an attached image is shrunk before it reaches a model.

A VLM pays per pixel. Qwen3.5 spends one token on every 32×32 square and takes
up to 16.7 MP, so the photo Jordi attached on 02/10 reached MLX as 16,113
tokens and took 75 s before the first word; he stopped it twice. Nothing on the
way in made it smaller.

The `validate` step now shrinks it once, for both doors, to `MAX_IMAGE_SIDE`
on its longest side — the recipe of interzone's heic2jpg (upright, never
enlarged, JPEG 85, no metadata), in Pillow — and puts the smaller image back
into `image_b64`, which is what every reader downstream takes: the engine, the
session the message is stored in, a Continue that re-attaches it.
"""
from __future__ import annotations

import base64
import io
import logging

import pytest
from PIL import Image

from core.turn.validate import MAX_IMAGE_SIDE, SHRUNK_IMAGE_TYPE, shrink_image

from .test_1035_fallback_keeps_its_model import _Mlx
from .test_continue_is_a_turn import _on_disk


def _image(size, *, fmt="JPEG", mode="RGB", color=(200, 30, 30), orientation=None) -> bytes:
    img = Image.new(mode, size, color)
    out = io.BytesIO()
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(out, format=fmt, exif=exif)
    else:
        img.save(out, format=fmt)
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ── shrink_image: the recipe ────────────────────────────────────────────────

class TestShrinkImage:

    def test_a_phone_photo_comes_out_with_its_longest_side_at_the_limit(self):
        shrunk = shrink_image(_image((4032, 3024)))
        assert shrunk is not None
        out = _open(shrunk)
        assert out.format == "JPEG"
        assert out.size == (MAX_IMAGE_SIDE, 1152)

    def test_an_image_that_fits_is_left_alone(self):
        """Exactly at the limit: re-encoding would only lose quality."""
        assert shrink_image(_image((MAX_IMAGE_SIDE, 900), fmt="PNG")) is None

    def test_one_pixel_over_the_limit_is_shrunk(self):
        shrunk = shrink_image(_image((MAX_IMAGE_SIDE + 1, 900), fmt="PNG"))
        assert shrunk is not None
        assert max(_open(shrunk).size) == MAX_IMAGE_SIDE

    def test_a_photo_taken_upright_stays_upright(self):
        """EXIF orientation 6: stored landscape, shown portrait. The re-encode
        drops the tag, so the pixels have to be turned before it."""
        out = _open(shrink_image(_image((4032, 3024), orientation=6)))
        assert out.size == (1152, MAX_IMAGE_SIDE)
        assert out.getexif().get(0x0112) is None

    def test_no_metadata_survives(self):
        img = Image.new("RGB", (4032, 3024), (200, 30, 30))
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # Make
        exif[0x0112] = 1
        src = io.BytesIO()
        img.save(src, format="JPEG", exif=exif)
        assert _open(src.getvalue()).getexif().get(0x010F) == "PhoneMaker"
        out = _open(shrink_image(src.getvalue()))
        assert len(out.getexif()) == 0

    def test_a_damaged_exif_block_still_shrinks_the_photo(self):
        """Common in phone and app output: Pillow's EXIF reader raises
        SyntaxError on it. The photo is shrunk unturned, not refused with a 500."""
        img = Image.new("RGB", (3000, 2000), (10, 120, 200))
        src = io.BytesIO()
        img.save(src, format="WEBP", exif=b"ZZZZ" + b"\0" * 20)
        shrunk = shrink_image(src.getvalue())
        assert shrunk is not None
        assert _open(shrunk).size == (MAX_IMAGE_SIDE, 1024)

    def test_a_broken_png_goes_as_it_came(self):
        """A corrupt chunk makes Pillow raise SyntaxError while decoding: the
        image goes to the engine untouched, as it did before #1122."""
        raw = bytearray(_image((3000, 2000), fmt="PNG"))
        idat = raw.index(b"IDAT")
        raw[idat:idat + 4] = b"IDXT"
        assert shrink_image(bytes(raw)) is None

    def test_sixteen_bit_grey_stays_grey(self):
        img = Image.new("I;16", (3000, 2000), 32768)
        src = io.BytesIO()
        img.save(src, format="PNG")
        r, g, b = _open(shrink_image(src.getvalue())).convert("RGB").getpixel((100, 100))
        assert 110 <= r <= 145 and r == g == b

    def test_fine_detail_on_a_palette_image_is_averaged_not_dropped(self):
        """One-pixel stripes on a palette PNG (a quantised screenshot): resized
        in palette mode they collapse to one colour."""
        img = Image.new("L", (3000, 2000), 0)
        for x in range(0, 3000, 2):
            img.paste(255, (x, 0, x + 1, 2000))
        src = io.BytesIO()
        img.convert("P").save(src, format="PNG")
        r, _g, _b = _open(shrink_image(src.getvalue())).convert("RGB").getpixel((500, 500))
        assert 60 <= r <= 195

    def test_a_transparent_png_goes_onto_white(self):
        shrunk = shrink_image(_image((3000, 2000), fmt="PNG", mode="RGBA", color=(0, 0, 0, 0)))
        assert _open(shrunk).convert("RGB").getpixel((10, 10)) == (255, 255, 255)

    def test_bytes_that_are_not_an_image_go_as_they_came(self, caplog):
        with caplog.at_level(logging.WARNING, logger="core.turn.validate"):
            assert shrink_image(b"hello") is None
        assert "could not be read to shrink" in caplog.text

    def test_a_bug_inside_is_not_taken_for_an_unreadable_image(self, monkeypatch):
        """Only what Pillow raises for bad bytes sends the image on as it came.
        Anything else is a bug and fails the turn: swallowed, it would quietly
        send every photo at full size again."""
        from PIL import ImageOps

        def broken(_img):
            raise RuntimeError("bug")

        monkeypatch.setattr(ImageOps, "exif_transpose", broken)
        with pytest.raises(RuntimeError):
            shrink_image(_image((4032, 3024)))

    def test_only_the_allowed_formats_are_decoded(self):
        """A big BMP sent as a "PNG" is not opened by a decoder this door
        never meant to reach."""
        assert shrink_image(_image((3000, 2000), fmt="BMP")) is None


# ── both doors, through the real pipeline ───────────────────────────────────

class TestBothDoorsCarryTheSmallerImage:

    async def test_the_web_door_hands_the_engine_and_the_session_the_small_one(
        self, turn_lab, session_manager, app_state,
    ):
        mlx = _Mlx(sees=True)
        app_state.modules = {"mlx_module": mlx}
        big = _image((4032, 3024))
        ctx = await turn_lab.ui(
            streaming=True, session_id="r1122-ui", message="què hi ha?",
            body_extra={"image_b64": _b64(big), "image_type": "image/jpeg"},
        )
        sent = ctx.attachments["image_b64"]
        assert ctx.attachments["image_type"] == SHRUNK_IMAGE_TYPE
        assert max(_open(base64.b64decode(sent)).size) == MAX_IMAGE_SIDE
        assert ctx.attachments["image_bytes"] == base64.b64decode(sent)
        assert mlx.calls and mlx.calls[0].get("images") == [sent]
        stored = [m for m in _on_disk(session_manager, "r1122-ui")["messages"] if m["role"] == "user"][-1]
        assert stored["image_b64"] == sent
        assert stored["image_type"] == SHRUNK_IMAGE_TYPE

    async def test_the_v1_door_shrinks_it_the_same_way(self, turn_lab):
        big = _image((3000, 4000), fmt="PNG")
        ctx = await turn_lab.api(
            session_id="r1122-v1",
            content=[
                {"type": "text", "text": "què hi ha?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(big)}"}},
            ],
        )
        assert ctx.attachments["image_type"] == SHRUNK_IMAGE_TYPE
        assert _open(base64.b64decode(ctx.attachments["image_b64"])).size == (1152, MAX_IMAGE_SIDE)

    async def test_a_small_image_reaches_the_engine_byte_for_byte(self, turn_lab, app_state):
        mlx = _Mlx(sees=True)
        app_state.modules = {"mlx_module": mlx}
        small = _b64(_image((800, 600), fmt="PNG"))
        ctx = await turn_lab.ui(
            streaming=True, session_id="r1122-small", message="què hi ha?",
            body_extra={"image_b64": small, "image_type": "image/png"},
        )
        assert ctx.attachments["image_b64"] == small
        assert ctx.attachments["image_type"] == "image/png"
        assert mlx.calls[0].get("images") == [small]


async def test_the_shrink_runs_off_the_event_loop(monkeypatch):
    """About 100 ms for a phone photo: on the loop it would stall every other
    stream the server is sending."""
    import threading

    from core.turn import validate
    from core.turn.context import TurnContext

    seen = {}

    def record(data):
        seen["thread"] = threading.current_thread()
        return None

    monkeypatch.setattr(validate, "shrink_image", record)
    ctx = TurnContext(turn_id="t", entry="ui", streaming=False, principal=None, body={}, request=None, app_state=None)
    ctx.attachments = {"image_b64": _b64(_image((10, 10))), "image_type": "image/jpeg"}
    ctx.message = "hola"
    await validate.validate_turn(ctx)
    assert seen["thread"] is not threading.main_thread()

