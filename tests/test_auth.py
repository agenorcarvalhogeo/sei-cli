from __future__ import annotations

from dataclasses import dataclass

from sei_cli.auth import build_login_payload, login
from sei_cli.models import Credentials
from sei_cli.parsers import parse_login_form


@dataclass
class _Response:
    text: str
    url: str


class _SessionStub:
    def __init__(self, login_page: str, post_response: str) -> None:
        self.login_page = login_page
        self.post_response = post_response
        self.last_post: dict[str, str] | None = None

    def get(self, url: str, **kwargs: object) -> _Response:
        return _Response(text=self.login_page, url=url)

    def post(self, url: str, data: dict[str, str], **kwargs: object) -> _Response:
        self.last_post = data
        return _Response(text=self.post_response, url=url)


def test_parse_login_form_extracts_action(login_html: str) -> None:
    parsed = parse_login_form(login_html, "https://sei.rn.gov.br/sip/login.php")
    assert "login.php?sigla_orgao_sistema=SEAD" in parsed.action


def test_build_login_payload_uses_hdnacao_2() -> None:
    creds = Credentials(usuario="u", senha="s", orgao="CBM", login_url="https://sei.rn.gov.br")
    payload = build_login_payload(creds)
    assert payload.hdnAcao == "2"
    assert payload.selOrgao == "28"


def test_login_success_detected(login_html: str, controle_html: str) -> None:
    creds = Credentials(
        usuario="111",
        senha="secret",
        orgao="CBM",
        login_url="https://sei.rn.gov.br/sei/controlador.php?acao=usuario_login",
    )
    session = _SessionStub(login_page=login_html, post_response=controle_html)

    status = login(session, creds)

    assert status.success is True
    assert session.last_post is not None
    assert session.last_post["hdnAcao"] == "2"
    assert session.last_post["selOrgao"] == "28"
