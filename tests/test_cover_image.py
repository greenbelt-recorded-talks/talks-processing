"""Cover art upload: whatever you hand in becomes the square PNG the tagger wants."""

import io

import pytest
from PIL import Image

from gbtalks.libgbtalks import normalise_cover_image


def make_image(width, height, fmt="PNG", colour=(200, 30, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format=fmt)
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize(
    "width, height, fmt",
    [
        (2000, 2000, "JPEG"),   # the square case
        (2000, 1200, "JPEG"),   # the one this was written for
        (1200, 2000, "JPEG"),   # taller than wide
        (300, 300, "PNG"),      # already correct - must still come back a PNG
        (64, 64, "PNG"),        # smaller than the target
    ],
)
def test_output_is_always_a_square_png_of_the_target_size(width, height, fmt):
    result = normalise_cover_image(make_image(width, height, fmt), 300)

    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "PNG"
        assert img.size == (300, 300)


def test_a_wide_source_is_padded_not_cropped():
    """The full width has to survive, because the icon is a logo."""
    source = make_image(2000, 1000, "JPEG", colour=(255, 0, 0))

    with Image.open(io.BytesIO(normalise_cover_image(source, 300))) as img:
        img = img.convert("RGBA")
        # Full width used, so the middle row is red edge to edge.
        assert img.getpixel((0, 150))[:3] == pytest.approx((255, 0, 0), abs=8)
        assert img.getpixel((299, 150))[:3] == pytest.approx((255, 0, 0), abs=8)
        # Height padded, so the top and bottom rows are transparent.
        assert img.getpixel((150, 0))[3] == 0
        assert img.getpixel((150, 299))[3] == 0


def test_the_target_size_is_configurable():
    result = normalise_cover_image(make_image(2000, 2000, "JPEG"), 500)

    with Image.open(io.BytesIO(result)) as img:
        assert img.size == (500, 500)


def test_a_non_image_is_rejected_rather_than_written():
    with pytest.raises(ValueError):
        normalise_cover_image(io.BytesIO(b"this is not an image"), 300)


class TestUploadRoute:
    def test_a_jpeg_upload_is_stored_as_a_square_png(self, auth_client, tmp_path):
        icon = auth_client.application.config["IMG_DIR"] + "/alltalksicon.png"

        response = auth_client.post(
            "/upload_cover_image",
            data={"file": (make_image(2000, 1200, "JPEG"), "cover.jpg")},
            content_type="multipart/form-data",
            headers={"Referer": "http://localhost/setup"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        with Image.open(icon) as img:
            assert img.format == "PNG"
            assert img.size == (
                auth_client.application.config["COVER_ART_SIZE"],
            ) * 2

    def test_an_unreadable_file_is_refused(self, auth_client):
        response = auth_client.post(
            "/upload_cover_image",
            data={"file": (io.BytesIO(b"not an image at all"), "cover.txt")},
            content_type="multipart/form-data",
            headers={"Referer": "http://localhost/setup"},
            follow_redirects=True,
        )

        # filetype.guess returns None here, which used to raise AttributeError
        # and 500 rather than telling the user what was wrong.
        assert response.status_code == 200
        assert "Must be a PNG or a JPEG" in response.get_data(as_text=True)
