from __future__ import annotations

from sei_cli.parsers import (
    parse_menu_links,
    parse_process_table,
    parse_processes,
    parse_quick_search_form,
    parse_system_status,
    parse_units_from_login,
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


def test_parse_process_table_from_fragment(recebidos_html: str, gerados_html: str) -> None:
    recebidos = parse_process_table(recebidos_html, BASE, "tblProcessosRecebidos", "recebidos")
    gerados = parse_process_table(gerados_html, BASE, "tblProcessosGerados", "gerados")

    assert len(recebidos) > 10
    assert len(gerados) > 5
    assert recebidos[0].id_procedimento == "47731219"
    assert gerados[0].id_procedimento == "41104331"


def test_parse_menu_and_search_action(controle_html: str) -> None:
    links = parse_menu_links(controle_html, BASE)
    assert "bloco_assinatura_listar" in links
    assert "protocolo_pesquisar" in links

    search_action = parse_quick_search_form(controle_html, BASE)
    assert search_action is not None
    assert "protocolo_pesquisa_rapida" in search_action


def test_parse_units_from_login(login_html: str) -> None:
    units = parse_units_from_login(login_html)
    assert any(unit.sigla == "CBM" and unit.link == "28" for unit in units)
