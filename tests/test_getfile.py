"""/getfile, and the two ways it can serve a file.

The X-Accel-Redirect path is off in the test config, as it is everywhere but
the festival server, so the tests that want it turn it on for the duration.
"""

import os

import pytest

from gbtalks.libgbtalks import content_disposition, get_path_for_file, x_accel_uri


@pytest.fixture
def accel(app):
    """Turn X-Accel-Redirect on, as the festival server's systemd unit does."""
    app.config["X_ACCEL_REDIRECT"] = True
    yield
    app.config["X_ACCEL_REDIRECT"] = False


@pytest.fixture
def talk_with_raw(app, make_talk):
    """A talk whose raw file is on disk, with recognisable contents."""
    talk = make_talk(talk_id=7)
    with app.app_context():
        path = get_path_for_file(str(talk.id), "raw")
    with open(path, "wb") as handle:
        handle.write(b"not really an mp3")
    yield talk
    os.remove(path)


def test_getfile_serves_the_file_itself_by_default(auth_client, talk_with_raw):
    response = auth_client.get("/getfile?file_type=raw&talk_id=7")

    assert response.status_code == 200
    assert response.data == b"not really an mp3"
    assert "X-Accel-Redirect" not in response.headers


def test_getfile_hands_the_file_to_nginx_when_configured(
    auth_client, talk_with_raw, accel
):
    response = auth_client.get("/getfile?file_type=raw&talk_id=7")

    assert response.status_code == 200
    # No body: nginx discards this response and serves the named file instead.
    assert response.data == b""
    assert response.headers["X-Accel-Redirect"] == "/_storage/uploads/gb26-007_RAW.mp3"
    # The two headers that survive the internal redirect.
    assert response.headers["Content-Type"] == "audio/mpeg"
    assert "gb26-007_RAW.mp3" in response.headers["Content-Disposition"]


def test_getfile_still_404s_on_a_missing_file(auth_client, make_talk, accel):
    make_talk(talk_id=8)

    response = auth_client.get("/getfile?file_type=raw&talk_id=8")

    assert response.status_code == 404


def test_getfile_needs_a_login(client, talk_with_raw):
    response = client.get("/getfile?file_type=raw&talk_id=7")

    assert response.status_code == 302
    assert "/login/" in response.headers["Location"]


def test_processed_filename_survives_the_trip_through_a_url(app_ctx, make_talk):
    """The processed names carry spaces, ampersands and a full-width colon."""
    talk = make_talk(
        talk_id=9,
        title="Money: What Now?",
        speaker="Ann Pettifor, Sam Speaker",
    )
    path = get_path_for_file(str(talk.id), "processed", talk.title, talk.speaker)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    try:
        uri = x_accel_uri(path)
    finally:
        os.remove(path)

    assert uri.startswith("/_storage/processed/")
    # Everything nginx would otherwise read as syntax is encoded, and decoding
    # it has to give back exactly the name on disk.
    assert " " not in uri and "?" not in uri and "&" not in uri
    from urllib.parse import unquote

    assert unquote(uri[len("/_storage/processed/") :]) == os.path.basename(path)


def test_a_file_outside_the_storage_directories_is_not_handed_over(app_ctx, tmp_path):
    stray = tmp_path / "somewhere-else.mp3"
    stray.write_bytes(b"")

    assert x_accel_uri(str(stray)) is None


def test_an_ascii_filename_is_named_plainly():
    # Unquoted, because there is nothing in the name needing quotes - the same
    # header send_file produces for it on the other branch.
    assert (
        content_disposition("gb26-007_RAW.mp3", attachment=True)
        == "attachment; filename=gb26-007_RAW.mp3"
    )


def test_a_non_ascii_filename_is_encoded_not_sent_raw():
    """The bug this helper exists for.

    character_mapping puts a full-width colon in the filename of every
    processed talk whose title has a colon in it. Sent raw, it cannot be
    encoded latin-1 and takes the whole request down inside the WSGI server -
    so the header has to carry it percent-encoded, with an ASCII name
    alongside for clients that only understand that one.
    """
    header = content_disposition("Money： What Now?.mp3", attachment=True)

    header.encode("latin-1")  # the check the WSGI server does, and used to fail
    assert "：" not in header
    assert 'filename="Money: What Now?.mp3"' in header
    assert "filename*=UTF-8''Money%EF%BC%9A%20What%20Now%3F.mp3" in header


def test_the_route_survives_a_processed_talk_with_a_colon_in_its_title(
    app, auth_client, make_talk, accel
):
    talk = make_talk(talk_id=11, title="Money: What Now?", speaker="Ann Pettifor")
    with app.app_context():
        path = get_path_for_file(str(talk.id), "processed", talk.title, talk.speaker)
    open(path, "wb").close()
    try:
        response = auth_client.get("/getfile?file_type=processed&talk_id=11")
    finally:
        os.remove(path)

    assert response.status_code == 200
    for value in response.headers.values():
        value.encode("latin-1")
