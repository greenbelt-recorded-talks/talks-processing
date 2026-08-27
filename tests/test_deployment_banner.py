"""The navbar badge that says which deployment you are looking at."""

import importlib

import pytest

from gbtalks import DEPLOYMENT_LABELS


@pytest.mark.parametrize(
    "env_vars, expected",
    [
        ({}, "onsite"),
        ({"PYTHONANYWHERE_DOMAIN": "pythonanywhere.com"}, "cloud"),
        ({"PYTHONANYWHERE_SITE": "www.pythonanywhere.com"}, "cloud"),
        # An explicit setting wins over the sniff, in both directions.
        ({"DEPLOYMENT_ENV": "cloud"}, "cloud"),
        (
            {"DEPLOYMENT_ENV": "onsite", "PYTHONANYWHERE_DOMAIN": "pythonanywhere.com"},
            "onsite",
        ),
    ],
)
def test_deployment_env_detection(monkeypatch, env_vars, expected):
    """config.Config reads os.environ as its class body runs, so reimport it."""
    for var in ("DEPLOYMENT_ENV", "PYTHONANYWHERE_DOMAIN", "PYTHONANYWHERE_SITE"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env_vars.items():
        monkeypatch.setenv(var, value)

    import config

    assert importlib.reload(config).Config.DEPLOYMENT_ENV == expected


def test_badge_is_in_the_navbar(auth_client):
    body = auth_client.get("/talks").get_data(as_text=True)

    label, css, hint = DEPLOYMENT_LABELS["onsite"]
    assert label in body
    assert css in body
    assert hint in body


def test_unknown_value_is_flagged_rather_than_hidden(auth_client, monkeypatch):
    monkeypatch.setitem(
        auth_client.application.config, "DEPLOYMENT_ENV", "somewhere-else"
    )
    body = auth_client.get("/talks").get_data(as_text=True)

    assert "somewhere-else" in body
    assert "uk-label-danger" in body


def test_the_standalone_rota_views_have_no_navbar(client):
    """A reminder, not a rule to defend.

    The three anonymous rota views are print-oriented and do not extend
    base.html, so they carry no badge. Every page that does extend it is behind
    a login, which is where the badge is wanted.
    """
    body = client.get("/rota_by_time").get_data(as_text=True)

    assert "uk-navbar" not in body
