"""Parser tests using HTML fixtures (no network calls)."""
from __future__ import annotations

from sei_cli.parsers import (
    parse_menu_links,
    parse_processes,
    parse_system_status,
)


BASE = "https://sei.rn.gov.br/sei/"


def test_parse_status(controle_html: str) -> None:
    status = parse_system_status(controle_html)
    assert status.valid is True
    assert status.unidade_sigla is not None
    assert "CBM" in status.unidade_sigla
    assert status.usuario is not None
    assert "11199338702" in status.usuario


def test_parse_processes_counts(controle_html: str) -> None:
    result = parse_processes(controle_html, BASE)
    assert len(result.recebidos) == 33
    assert len(result.gerados) == 15


def test_process_has_id(controle_html: str) -> None:
    result = parse_processes(controle_html, BASE)
    assert result.recebidos[0].id_procedimento is not None
    assert result.recebidos[0].numero != ""


def test_parse_menu_links(controle_html: str) -> None:
    links = parse_menu_links(controle_html, BASE)
    assert "blocos_assinatura" in links
