"""Parser tests using HTML fixtures (no network calls)."""
from __future__ import annotations

from sei_cli.parsers import (
    parse_marcador_form,
    parse_marcadores_list,
    parse_menu_links,
    parse_block_documents,
    parse_blocks,
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


def test_parse_blocks_extracts_div_based_destination_units() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrClara">
          <td><input type="checkbox"/></td>
          <td><a href="controlador.php?acao=rel_bloco_protocolo_listar&id_bloco=773617">773617</a></td>
          <td></td>
          <td></td>
          <td>Disponibilizado</td>
          <td>CBM - COBM - GAB CMDO</td>
          <td class="d-none d-md-table-cell" align="center">
            <div class="divUnidade"><div class="divUnidadeIcone"><img src="svg/bloco_aguardando_devolucao.svg?18" height="16" width="16" title="Aguardando Devolução"></div><div class="divUnidadeRotulo"><a href="javascript:void(0);" class="ancoraSigla">CBM - COBM - CMDO PABM APODI</a></div></div>
            <div class="divUnidade"><div class="divUnidadeIcone"><img src="svg/bloco_aguardando_devolucao.svg?18" height="16" width="16" title="Aguardando Devolução"></div><div class="divUnidadeRotulo"><a href="javascript:void(0);" class="ancoraSigla">CBM - COBM - CMDO 2ºSGB/3ºGBM</a></div></div>
          </td>
          <td></td>
          <td>Bloco de teste</td>
          <td></td>
        </tr>
      </table>
    </body></html>
    """

    blocks = parse_blocks(html, BASE)

    assert len(blocks) == 1
    assert blocks[0].numero == "773617"
    assert blocks[0].unidades_destino == [
        "CBM - COBM - CMDO PABM APODI",
        "CBM - COBM - CMDO 2ºSGB/3ºGBM",
    ]
    assert blocks[0].unidade_destino == (
        "CBM - COBM - CMDO PABM APODI; CBM - COBM - CMDO 2ºSGB/3ºGBM"
    )


def test_parse_block_documents_extracts_div_based_signers() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrClara">
          <td><input type="checkbox"/></td>
          <td>1</td>
          <td>08810058.000128/2026-69</td>
          <td>48568466</td>
          <td>Relatório do Fiscal</td>
          <td align="justified">
            <div class="divItemCelula"><div class="divIconeItemCelula"><img src="svg/tabela_item_celula.svg?18" height="16" width="16" title="Assinatura"></div><div class="divRotuloItemCelula">EDUARDO DOS SANTOS PEDROSA / Soldado QPBM</div></div>
            <div class="divItemCelula"><div class="divIconeItemCelula"><img src="svg/tabela_item_celula.svg?18" height="16" width="16" title="Assinatura"></div><div class="divRotuloItemCelula">LEO ZENON TASSI / 2º Tenente QOEM BM</div></div>
            <div class="divItemCelula"><div class="divIconeItemCelula"><img src="svg/tabela_item_celula.svg?18" height="16" width="16" title="Assinatura"></div><div class="divRotuloItemCelula">JEDSON RAFAEL ALMEIDA MENEZES / Soldado QPBM</div></div>
            <div class="divItemCelula"><div class="divIconeItemCelula"><img src="svg/tabela_item_celula.svg?18" height="16" width="16" title="Assinatura"></div><div class="divRotuloItemCelula">RENATO MATOS LEONARDO / Soldado QPBM</div></div>
          </td>
          <td><img title="Assinatura"/></td>
        </tr>
      </table>
    </body></html>
    """

    docs = parse_block_documents(html, BASE)

    assert len(docs) == 1
    assert docs[0].assinantes == [
        "EDUARDO DOS SANTOS PEDROSA / Soldado QPBM",
        "LEO ZENON TASSI / 2º Tenente QOEM BM",
        "JEDSON RAFAEL ALMEIDA MENEZES / Soldado QPBM",
        "RENATO MATOS LEONARDO / Soldado QPBM",
    ]
    assert docs[0].assinante == (
        "EDUARDO DOS SANTOS PEDROSA / Soldado QPBM; "
        "LEO ZENON TASSI / 2º Tenente QOEM BM; "
        "JEDSON RAFAEL ALMEIDA MENEZES / Soldado QPBM; "
        "RENATO MATOS LEONARDO / Soldado QPBM"
    )
    assert docs[0].assinado is True


def test_parse_block_documents_unsigned_row_keeps_empty_signers() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrEscura">
          <td><input type="checkbox"/></td>
          <td>1</td>
          <td>08810058.000128/2026-69</td>
          <td>48568466</td>
          <td>Relatório do Fiscal</td>
          <td align="justified"></td>
          <td><img title="Pendente"/></td>
        </tr>
      </table>
    </body></html>
    """

    docs = parse_block_documents(html, BASE)

    assert len(docs) == 1
    assert docs[0].assinantes == []
    assert docs[0].assinante == ""
    assert docs[0].assinado is False


def test_parse_block_documents_extracts_div_based_document_metadata() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrClara">
          <td><input type="checkbox"/></td>
          <td>1</td>
          <td>08810058.000128/2026-69</td>
          <td>
            <div class="divItemCelula"><div class="divRotuloItemCelula">40365904</div></div>
            <div class="divItemCelula"><div class="divRotuloItemCelula">33920087</div></div>
            <div class="divItemCelula"><div class="divRotuloItemCelula">30/03/2026</div></div>
          </td>
          <td>Despacho</td>
          <td align="justified"><div class="divItemCelula"><div class="divRotuloItemCelula">Fulano / 2º Ten BM</div></div></td>
          <td><img title="Assinatura"/></td>
        </tr>
      </table>
    </body></html>
    """

    docs = parse_block_documents(html, BASE)

    assert len(docs) == 1
    assert docs[0].documento_id == "40365904"
    assert docs[0].numero_documento == "33920087"
    assert docs[0].numero_sei == "33920087"
    assert docs[0].data_documento == "30/03/2026"


def test_parse_block_documents_extracts_metadata_from_attributes() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrClara">
          <td><input type="checkbox"/></td>
          <td>1</td>
          <td>08810058.000128/2026-69</td>
          <td>
            <a
              href="controlador.php?acao=documento_visualizar&id_documento=40365904"
              title="Documento SEI 33920087 elaborado em 30/03/2026"
            >40365904</a>
          </td>
          <td>Despacho</td>
          <td align="justified"><div class="divItemCelula"><div class="divRotuloItemCelula">Fulano / 2º Ten BM</div></div></td>
          <td><img title="Assinatura"/></td>
        </tr>
      </table>
    </body></html>
    """

    docs = parse_block_documents(html, BASE)

    assert len(docs) == 1
    assert docs[0].documento_id == "40365904"
    assert docs[0].numero_documento == "33920087"
    assert docs[0].numero_sei == "33920087"
    assert docs[0].data_documento == "30/03/2026"


def test_parse_block_documents_ignores_infra_sistema_false_positive() -> None:
    html = """
    <html><body>
      <table>
        <tr class="infraTrClara">
          <td><input type="checkbox"/></td>
          <td>1</td>
          <td>08810058.000128/2026-69</td>
          <td>
            <a
              href="controlador.php?acao=documento_visualizar&id_documento=40365904&infra_sistema=100000100"
              title="Abrir documento"
            >40365904</a>
          </td>
          <td>Despacho</td>
          <td align="justified"><div class="divItemCelula"><div class="divRotuloItemCelula">Fulano / 2º Ten BM</div></div></td>
          <td><img title="Assinatura"/></td>
        </tr>
      </table>
    </body></html>
    """

    docs = parse_block_documents(html, BASE)

    assert len(docs) == 1
    assert docs[0].documento_id == "40365904"
    assert docs[0].numero_documento is None
    assert docs[0].numero_sei is None
