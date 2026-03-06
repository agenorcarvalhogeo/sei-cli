"""Parser tests using HTML fixtures (no network calls)."""
from __future__ import annotations

from sei_cli.parsers import (
    parse_marcador_form,
    parse_marcadores_list,
    parse_menu_links,
    parse_processes,
    parse_system_status,
    parse_tramitar_form,
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
    assert "marcadores" in links


def test_parse_tramitar_form() -> None:
    html = """
    <html><body>
      <form id="frmProcedimentoEnviar" action="controlador.php?acao=procedimento_enviar_executar">
        <input type="hidden" name="infra_hash" value="abc"/>
        <select name="selUnidades">
          <option value="">Selecione</option>
          <option value="110006929">PAD - PDF</option>
          <option value="110008367" selected>CMDO PABM APODI</option>
        </select>
        <input type="checkbox" name="chkSinManterAberto" value="S" />
      </form>
    </body></html>
    """
    form = parse_tramitar_form(html, BASE, BASE + "controlador.php?acao=procedimento_enviar")
    assert form.destino_field == "selUnidades"
    assert form.manter_aberto_field == "chkSinManterAberto"
    assert len(form.destinos) == 2
    assert any(d.id_unidade == "110008367" for d in form.destinos)


def test_parse_marcadores_list() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrClara">
          <td><input type="radio" name="chkInfraItem" value="12"/></td>
          <td>LIVROS</td>
          <td>Livro Fiscal</td>
          <td><img src="svg/marcador_preto.svg?18"/></td>
        </tr>
      </table>
    </body></html>
    """
    marcadores = parse_marcadores_list(html, BASE)
    assert len(marcadores) == 1
    assert marcadores[0].marcador_id == "12"
    assert marcadores[0].nome == "LIVROS"
    assert marcadores[0].cor == "marcador_preto"


def test_parse_marcador_form() -> None:
    html = """
    <html><body>
      <form id="frmAndamentoMarcadorCadastro" action="controlador.php?acao=andamento_marcador_salvar">
        <input type="hidden" name="infra_hash" value="xyz"/>
        <select name="selMarcador">
          <option value="">Selecione</option>
          <option value="1" selected>LIVROS</option>
          <option value="2">ALMOX</option>
        </select>
        <textarea name="txaTexto"></textarea>
      </form>
    </body></html>
    """
    form = parse_marcador_form(html, BASE, BASE + "controlador.php?acao=andamento_marcador_cadastrar")
    assert form.marcador_field == "selMarcador"
    assert form.texto_field == "txaTexto"
    assert len(form.marcadores) == 2
