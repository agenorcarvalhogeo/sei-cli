"""Auth tests using HTML fixtures (no network calls)."""
from __future__ import annotations

from sei_cli.config import orgao_to_value
from sei_cli.parsers import parse_login_form


def test_parse_login_form_extracts_action(login_html: str) -> None:
    parsed = parse_login_form(login_html, "https://sei.rn.gov.br/sip/login.php")
    assert "login.php" in parsed.action


def test_orgao_cbm_maps_to_28() -> None:
    assert orgao_to_value("CBM") == "28"
    assert orgao_to_value("cbm") == "28"


def test_orgao_unknown_returns_as_is() -> None:
    assert orgao_to_value("99") == "99"
