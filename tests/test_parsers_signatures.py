from __future__ import annotations

from pathlib import Path

from sei_cli.client import SEIClient
from sei_cli.parsers import parse_expanded_folder, parse_tree_signatures


FIXTURE = Path("tests/fixtures/arvore_with_signatures.js").read_text()
BASE = "https://sei.rn.gov.br/sei/"


def test_parse_assinatura() -> None:
    sigs = parse_tree_signatures(FIXTURE)

    assert "48849154" in sigs
    entry = sigs["48849154"][0]
    assert entry.kind == "assinatura"
    assert entry.signer == "LEO ZENON TASSI"
    assert entry.role == "2º Tenente QOEM BM"


def test_parse_autenticacao() -> None:
    sigs = parse_tree_signatures(FIXTURE)

    assert "48849394" in sigs
    entry = sigs["48849394"][0]
    assert entry.kind == "autenticacao"
    assert entry.signer == "LEO ZENON TASSI"


def test_multiple_signers() -> None:
    content = """
    NosAcoes[20] = new infraArvoreAcao("ASSINATURA","A48788412","48788412","javascript:alert('Assinado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT\\n\\nGEORGE WAGNER GUEDES BEZERRA\\nCabo QPBM\\nCBM - DAT - SEC  - 1°SAT/1°CAT');",null,"Assinado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT\\n\\nGEORGE WAGNER GUEDES BEZERRA\\nCabo QPBM\\nCBM - DAT - SEC  - 1°SAT/1°CAT","svg/assinatura2.svg?18",true);
    """

    sigs = parse_tree_signatures(content)

    assert len(sigs["48788412"]) == 2
    assert sigs["48788412"][0].signer == "LEO ZENON TASSI"
    assert sigs["48788412"][1].signer == "GEORGE WAGNER GUEDES BEZERRA"


def test_no_signatures() -> None:
    content = 'Nos[1] = new infraArvoreNo("DOCUMENTO","1","P","url","t","Doc sem assinatura","Doc sem assinatura","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,true,null,null,"noVisitado","123");'

    sigs = parse_tree_signatures(content)

    assert sigs == {}


def test_integration_tree_document() -> None:
    docs = parse_expanded_folder(FIXTURE, BASE)
    doc = next(d for d in docs if d.id_documento == "48849154")
    pdf = next(d for d in docs if d.id_documento == "48849394")
    unsigned = next(d for d in docs if d.id_documento == "48849195")

    assert doc.assinado is True
    assert doc.autenticado is False
    assert len(doc.assinaturas) == 1
    assert pdf.assinado is False
    assert pdf.autenticado is True
    assert len(pdf.assinaturas) == 1
    assert unsigned.assinado is False
    assert unsigned.autenticado is False
    assert unsigned.assinaturas == []


def test_mixed_process_lazy_loaded_folder_merge() -> None:
    root = """
    Pastas[1]['link'] = 'controlador.php?acao=expandir';
    Pastas[1]['protocolos'] = '48788412,48788413';
    Nos[10] = new infraArvoreNo("PASTA","PASTA1","48849146","#","ifrArvore","Pasta I (10)","Pasta I (10)","svg/pasta_fechada.svg?18","svg/pasta_fechada.svg?18","svg/pasta_fechada.svg?18",true,true,null,null,"noVisitado","");
    Nos[10].carregado = false;
    Nos[1] = new infraArvoreNo("DOCUMENTO","48849154","48849146","controlador.php?acao=arvore_visualizar&id_documento=48849154","ifrConteudoVisualizacao","Exposição de Motivos 191 (40442155)","Exposição de Motivos 191 (40442155)","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,true,null,null,"noVisitado","40442155");
    Nos[2] = new infraArvoreNo("DOCUMENTO","48849394","48849146","controlador.php?acao=arvore_visualizar&id_documento=48849394","ifrConteudoVisualizacao","Escala Ordinária Março (40442376)","Escala Ordinária Março (40442376)","svg/documento_pdf.svg?18","svg/documento_pdf.svg?18","svg/documento_pdf.svg?18",true,true,null,null,"noVisitado","40442376");
    NosAcoes[1] = new infraArvoreAcao("ASSINATURA","A48849154","48849154","javascript:alert('Assinado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT');",null,"Assinado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT","svg/assinatura2.svg?18",true);
    NosAcoes[2] = new infraArvoreAcao("ASSINATURA","A48849394","48849394","javascript:alert('Autenticado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT');",null,"Autenticado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT","svg/autenticacao2.svg?18",true);
    """
    expansion = """OK
    Nos[3] = new infraArvoreNo("DOCUMENTO","48788412","PASTA1","controlador.php?acao=arvore_visualizar&id_documento=48788412","ifrConteudoVisualizacao","Encaminhamento 232 (40381240)","Encaminhamento 232 (40381240)","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,true,null,null,"noVisitado","40381240");
    Nos[4] = new infraArvoreNo("DOCUMENTO","48788413","PASTA1","controlador.php?acao=arvore_visualizar&id_documento=48788413","ifrConteudoVisualizacao","Informação 10 (40381241)","Informação 10 (40381241)","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,true,null,null,"noVisitado","40381241");
    NosAcoes[20] = new infraArvoreAcao("ASSINATURA","A48788412","48788412","javascript:alert('Assinado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT\\n\\nGEORGE WAGNER GUEDES BEZERRA\\nCabo QPBM\\nCBM - DAT - SEC  - 1°SAT/1°CAT');",null,"Assinado por:\\nLEO ZENON TASSI\\n2º Tenente QOEM BM\\nCBM - DAT - SEC  - 1°SAT/1°CAT\\n\\nGEORGE WAGNER GUEDES BEZERRA\\nCabo QPBM\\nCBM - DAT - SEC  - 1°SAT/1°CAT","svg/assinatura2.svg?18",true);
    """

    client = SEIClient.__new__(SEIClient)
    client._sei_url = lambda path="": BASE + path.lstrip("/")
    client._navigate_to_arvore = lambda _id: root

    class Resp:
        def __init__(self, text: str) -> None:
            self.text = text

    client._post = lambda *_args, **_kwargs: Resp(expansion)

    docs = client.get_full_document_tree("48849146", expand_all=True)

    assert len(docs) == 4
    root_signed = next(d for d in docs if d.id_documento == "48849154")
    root_pdf = next(d for d in docs if d.id_documento == "48849394")
    lazy_signed = next(d for d in docs if d.id_documento == "48788412")
    lazy_unsigned = next(d for d in docs if d.id_documento == "48788413")

    assert root_signed.assinado is True
    assert root_pdf.autenticado is True
    assert lazy_signed.assinado is True
    assert len(lazy_signed.assinaturas) == 2
    assert lazy_unsigned.assinado is False
