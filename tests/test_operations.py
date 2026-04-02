from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from click.testing import CliRunner

from sei_cli.cli import cli
from sei_cli.models import Block, BlockDocument, DocumentCreated, DocumentType, Process, ProcessList, SystemStatus, TramitarDestino, TramitarForm, TreeDocument
from sei_cli.models import EditorSection
from sei_cli.operations import (
    block_review,
    document_create_confirm,
    document_create_preview,
    document_edit_confirm,
    document_edit_preview,
    document_pdf_confirm,
    document_pdf_preview,
    document_quality_check,
    document_read,
    environment_triage_apply,
    environment_triage_preview,
    inbox_snapshot,
    marker_catalog,
    process_finalize_confirm,
    process_finalize_preview,
    process_conclude_confirm,
    process_conclude_preview,
    process_forward_confirm,
    process_forward_preview,
    process_marker_history,
    process_create_confirm,
    process_create_preview,
    process_pdf_confirm,
    process_pdf_preview,
    process_marker_preview,
    process_marker_read,
    process_marker_remove_confirm,
    process_marker_remove_preview,
    process_marker_set_confirm,
    process_marker_set_preview,
    process_marker_update_confirm,
    process_marker_update_preview,
    process_open,
    process_reopen_confirm,
    process_reopen_preview,
    process_report,
    process_read,
    process_summary,
    relatorio_read,
    signature_block_add_document_confirm,
    signature_block_add_document_preview,
    signature_block_list,
    signature_block_recall_confirm,
    signature_block_recall_preview,
    signature_block_refresh_confirm,
    signature_block_refresh_preview,
    signature_block_read,
    signature_block_sign_confirm,
    signature_block_sign_preview,
    signature_block_review,
)
from sei_cli.relatorio_parser import Militar, RelatorioServico


class FakeClient:
    UNIT_IDS = {
        "PAD-PDF": "110006929",
        "CMDO PABM APODI": "110008367",
    }
    PROC_TYPES = {
        "ferias": "100000182",
        "informacao": "100000595",
        "requerimento": "100000268",
    }
    DOC_TYPES = {
        "despacho": "5",
        "parte_generica": "292",
        "solicitacao": "178",
        "informacao": "92",
    }

    def __init__(self) -> None:
        self.switched_to: str | None = None
        self.last_block_add: dict[str, Any] | None = None
        self.last_block_recall: dict[str, Any] | None = None
        self.signed_documents: list[dict[str, Any]] = []
        self.authenticated_documents: list[dict[str, Any]] = []
        self.generated_pdf_paths: list[str] = []
        self.forwarded_processes: list[dict[str, Any]] = []
        self.concluded_processes: list[dict[str, Any]] = []
        self.reopened_processes: list[str] = []
        self.history_units: dict[str, list[str]] = {"47607237": ["CMDO PABM APODI", "PAD-PDF"]}
        self.marker_catalog = [
            {"id": "10", "nome": "LIVROS"},
            {"id": "11", "nome": "Férias / Dispensas"},
            {"id": "12", "nome": "Informações"},
            {"id": "13", "nome": "Materiais Quartel"},
        ]
        self.process_markers: dict[str, dict[str, str]] = {
            "47607237": {"id": "11", "nome": "Férias / Dispensas", "texto": "Sd José Junior 15/03 - 13/04"}
        }
        self.marker_history_map: dict[tuple[str, str], list[dict[str, str]]] = {
            ("47607237", "11"): [
                {
                    "data": "31/03/2026 11:00",
                    "usuario": "Fulano",
                    "acao": "Aplicado",
                    "detalhes": "Sd José Junior 15/03 - 13/04",
                }
            ]
        }
        self.blocks: list[Block] = [
            Block(
                numero="774681",
                estado="Recebido",
                unidade_origem="OP 3",
                unidade_destino="CMDO",
                descricao="Assinaturas pendentes",
            )
        ]
        self.block_documents_map: dict[str, list[BlockDocument]] = {
            "774681": [
                BlockDocument(
                    seq="1",
                processo="08810058.000128/2026-69",
                documento_id="48568466",
                tipo_documento="Relatório do Fiscal",
                assinante="Fulano",
                numero_sei="39860248",
                numero_documento="39860248",
                assinado=False,
            ),
                BlockDocument(
                    seq="2",
                    processo="08810071.000091/2025-10",
                    documento_id="48568467",
                    tipo_documento="Despacho",
                    assinante="Beltrano",
                    numero_sei="39860248",
                    numero_documento="39860248",
                    assinado=True,
                ),
            ]
        }

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def switch_unit(self, keyword: str) -> SystemStatus:
        self.switched_to = keyword
        return self.status()

    def list_units(self) -> list[Any]:
        return [
            type("UnitObj", (), {"sigla": "OP 3"})(),
            type("UnitObj", (), {"sigla": "CMDO PABM APODI"})(),
            type("UnitObj", (), {"sigla": "PAD-PDF"})(),
        ]

    def status(self) -> SystemStatus:
        unit_sigla = self.switched_to or "OP 3"
        return SystemStatus(
            valid=True,
            unidade_sigla=unit_sigla,
            unidade_descricao=unit_sigla,
            usuario="Fulano",
            ultimo_acesso="29/03/2026 10:00",
        )

    def list_processes(self, unit: str | None = None) -> ProcessList:
        recebidos = [
            Process(
                numero="08810058.000128/2026-69",
                tipo="Informações",
                especificacao="Requisição judicial",
                id_procedimento="47607237",
                link="",
                novo=True,
                atribuido="Fulano",
                marcador="LIVROS",
                caixa="recebidos",
            )
        ,
            Process(
                numero="08810254.000117/2026-62",
                tipo="Pessoal: Férias - Alteração",
                especificacao="Reaprazamento de férias",
                id_procedimento="48756457",
                link="",
                novo=False,
                recente=True,
                caixa="recebidos",
            )
        ]
        gerados = [
            Process(
                numero="08810071.000091/2025-10",
                tipo="Licitação",
                especificacao="Água mineral",
                id_procedimento="39613183",
                link="",
                novo=False,
                caixa="gerados",
            )
        ]
        return ProcessList(recebidos=recebidos, gerados=gerados)

    def list_blocks(self) -> list[Block]:
        return list(self.blocks)

    def list_marcadores(self) -> list[dict[str, str]]:
        return list(self.marker_catalog)

    def set_marcador(self, id_procedimento: str, marcador_id: str, texto: str = "") -> bool:
        marker = next((item for item in self.marker_catalog if item["id"] == marcador_id), None)
        if not marker:
            return False
        self.process_markers[id_procedimento] = {
            "id": marcador_id,
            "nome": marker["nome"],
            "texto": texto,
        }
        return True

    def remove_marcador(self, id_procedimento: str, marcador_id: str | None = None) -> bool:
        current = self.process_markers.get(id_procedimento)
        if marcador_id and current and current.get("id") != marcador_id:
            return False
        self.process_markers.pop(id_procedimento, None)
        return True

    def list_process_markers(self, id_procedimento: str) -> list[dict[str, str]]:
        current = self.process_markers.get(id_procedimento)
        if not current:
            return []
        return [
            {
                "id": current["id"],
                "marcador_id": current["id"],
                "nome": current["nome"],
                "texto": current["texto"],
            }
        ]

    def update_marcador(self, id_procedimento: str, marcador_id: str, texto: str) -> bool:
        current = self.process_markers.get(id_procedimento)
        if not current or current.get("id") != marcador_id:
            return False
        current["texto"] = texto
        self.marker_history_map.setdefault((id_procedimento, marcador_id), []).append(
            {
                "data": "31/03/2026 12:00",
                "usuario": "Fulano",
                "acao": "Alterado",
                "detalhes": texto,
            }
        )
        return True

    def marker_history(self, id_procedimento: str, marcador_id: str | None = None) -> list[dict[str, str]]:
        current = self.process_markers.get(id_procedimento)
        if marcador_id is None and current:
            marcador_id = current["id"]
        entries = list(self.marker_history_map.get((id_procedimento, marcador_id or ""), []))
        normalized: list[dict[str, str]] = []
        for item in entries:
            normalized.append(
                {
                    **item,
                    "data_only": item["data"].split()[0] if item.get("data") else "",
                    "hora": item["data"].split()[1] if len(item.get("data", "").split()) > 1 else "",
                    "marker_text": item.get("detalhes", ""),
                    "raw_columns": [item.get("data", ""), item.get("usuario", ""), item.get("acao", ""), item.get("detalhes", "")],
                }
            )
        return normalized

    def cancelar_disponibilizacao_block(self, block_numero: str) -> dict[str, Any]:
        self.last_block_recall = {"block_numero": block_numero, "action": "cancelar_disponibilizacao"}
        for block in self.blocks:
            if block.numero == block_numero:
                block.estado = "Gerado"
                return {"ok": True, "message": f"Bloco {block_numero} — estado: {block.estado}"}
        return {"ok": False, "message": f"Bloco {block_numero} não encontrado"}

    def devolver_block(self, block_numero: str) -> dict[str, Any]:
        self.last_block_recall = {"block_numero": block_numero, "action": "devolver"}
        self.blocks = [block for block in self.blocks if block.numero != block_numero]
        self.block_documents_map.pop(block_numero, None)
        return {"ok": True, "message": f"Bloco {block_numero} devolvido com sucesso"}

    def search(self, query: str) -> str:
        if query == "08810058.000128/2026-69":
            return '<html><iframe name="ifrArvore"></iframe><a href="x?id_procedimento=47607237"></a></html>'
        return "<html></html>"

    def get_full_document_tree(self, id_procedimento: str) -> list[TreeDocument]:
        if id_procedimento != "47607237":
            if id_procedimento == "48756457":
                return [
                    TreeDocument(
                        id_documento="48784646",
                        nome="Despacho 40382558",
                        tipo="interno",
                        sei_number="40382558",
                        parent_folder=None,
                        assinado=True,
                    ),
                    TreeDocument(
                        id_documento="48783191",
                        nome="Solicitação de Reaprazamento",
                        tipo="interno",
                        sei_number="40381240",
                        parent_folder=None,
                        assinado=False,
                    ),
                ]
            return []
        return [
            TreeDocument(
                id_documento="48568466",
                nome="Solicitação de Reaprazamento",
                tipo="interno",
                sei_number="39860248",
                parent_folder=None,
                assinado=False,
            ),
            TreeDocument(
                id_documento="48568461",
                nome="Parte Genérica 10/04/2026",
                tipo="interno",
                sei_number="39860241",
                parent_folder="PASTA1",
                assinado=False,
            ),
            TreeDocument(
                id_documento="48568462",
                nome="Despacho Inicial 11/04/2026",
                tipo="interno",
                sei_number="39860242",
                parent_folder="PASTA1",
                assinado=True,
            ),
            TreeDocument(
                id_documento="48568463",
                nome="Livro do Fiscal 15/04/2026",
                tipo="pdf",
                sei_number="39860243",
                parent_folder="PASTA1",
                assinado=False,
            ),
            TreeDocument(
                id_documento="48568467",
                nome="Despacho 20/04/2026",
                tipo="interno",
                sei_number="39860249",
                parent_folder="PASTA2",
                assinado=True,
            ),
            TreeDocument(
                id_documento="48568468",
                nome="Relatório do Fiscal 21/04/2026",
                tipo="interno",
                sei_number="39860250",
                parent_folder="PASTA2",
                assinado=False,
            ),
            TreeDocument(
                id_documento="48568469",
                nome="Ofício DPSGP 22/04/2026",
                tipo="pdf",
                sei_number="39860251",
                parent_folder="PASTA2",
                assinado=True,
            ),
            TreeDocument(
                id_documento="59999999",
                nome="Despacho recém-criado",
                tipo="interno",
                sei_number="39999999",
                parent_folder="PASTA2",
                assinado=False,
            ),
        ]

    def search_document(self, protocolo: str) -> tuple[str, str] | None:
        if protocolo == "39860248":
            return ("48568466", "47607237")
        if protocolo == "39860243":
            return ("48568463", "47607237")
        if protocolo == "39860250":
            return ("48568468", "47607237")
        if protocolo == "39999999":
            return ("59999999", "47607237")
        return None

    def read_document(self, id_documento: str, id_procedimento: str) -> str:
        if (id_documento, id_procedimento) == ("48568466", "47607237"):
            return (
                "3º SGT BM João Silva solicita reaprazamento de férias de 10/04/2026 para 20/04/2026.\n"
                "Encaminhar ao CMDO PABM APODI para despacho e posterior envio ao DPSGP.\n"
                "Justificativa: necessidade de adequação da escala operacional.\n"
                "Fulano - 2º Tenente QOEM BM\n"
            )
        if (id_documento, id_procedimento) == ("48568461", "47607237"):
            return (
                "Parte genérica referente ao reaprazamento de férias do 3º SGT BM João Silva.\n"
                "Para ciência do CMDO PABM APODI e registro preliminar.\n"
                "Jorge Wagner - Cabo QPBM\n"
            )
        if (id_documento, id_procedimento) == ("48568462", "47607237"):
            return (
                "Despacho inicial autorizando a continuidade da análise do pedido do 3º SGT BM João Silva.\n"
                "Encaminhar à secretaria competente para prosseguimento.\n"
            )
        if (id_documento, id_procedimento) == ("48568463", "47607237"):
            return (
                "Anexo com documentos complementares do pedido de férias.\n"
                "Sem necessidade de resposta imediata.\n"
            )
        if (id_documento, id_procedimento) == ("48568467", "47607237"):
            return (
                "Despacho autorizando o reaprazamento solicitado pelo 3º SGT BM João Silva.\n"
                "Encaminhar ao DPSGP e à Ajudância Geral para as providências cabíveis.\n"
            )
        if (id_documento, id_procedimento) == ("48568468", "47607237"):
            return (
                "Relatório do Fiscal sobre a conferência do processo de reaprazamento de férias.\n"
                "Sem óbices para continuidade do trâmite.\n"
            )
        if (id_documento, id_procedimento) == ("48568469", "47607237"):
            return (
                "Ofício DPSGP 22/04/2026.\n"
                "Para conhecimento e registro do reaprazamento de férias do 3º SGT BM João Silva.\n"
            )
        if (id_documento, id_procedimento) == ("59999999", "47607237"):
            return (
                "Despacho atualizado do 3º SGT BM João Silva.\n"
                "Encaminhar ao CMDO PABM APODI para providências.\n"
            )
        if (id_documento, id_procedimento) == ("48784646", "48756457"):
            return (
                "Despacho sobre o reaprazamento de férias.\n"
                "Aguardando despacho do comandante.\n"
            )
        if (id_documento, id_procedimento) == ("48783191", "48756457"):
            return (
                "Solicitação de reaprazamento de férias do militar.\n"
                "Necessita manifestação do comandante e posterior encaminhamento.\n"
            )
        raise RuntimeError("Documento não encontrado")

    def download_document(self, doc: TreeDocument, output_path: str | None = None) -> bytes | str:
        payloads: dict[str, str] = {
            "48568463": (
                "TEXT:Relatório do Fiscal de Serviço Operacional.\n"
                "2º SGT BM João Silva - Fiscal de Operações.\n"
                "Do dia 15 para o dia 16 de abril de 2026.\n"
                "Ao Comando do OP 3.\n"
                "SD BM Maria Souza atuou como condutora.\n"
            ),
            "48568469": (
                "TEXT:Ofício DPSGP 22/04/2026.\n"
                "Para conhecimento e registro do reaprazamento de férias do 3º SGT BM João Silva.\n"
            ),
        }
        if doc.id_documento not in payloads:
            raise RuntimeError("Download não encontrado")
        if output_path:
            raise RuntimeError("output_path não suportado no fake")
        return payloads[doc.id_documento].encode("utf-8")

    def read_document_content(self, doc: TreeDocument) -> str:
        payload = self.download_document(doc)
        if isinstance(payload, bytes):
            return payload[5:].decode("utf-8").strip()
        return payload

    def read_relatorio(self, id_documento: str, id_procedimento: str) -> RelatorioServico:
        if (id_documento, id_procedimento) != ("48568468", "47607237"):
            raise RuntimeError("Relatório não encontrado")
        return RelatorioServico(
            fiscal="João Silva",
            posto_fiscal="2º SGT BM",
            data_inicio="29/03/2026",
            data_fim="30/03/2026",
            unidade="OP 3",
            militares=[
                Militar(nome="João Silva", posto="2º SGT BM", funcao="Fiscal", status="ordinario"),
                Militar(nome="Maria Souza", posto="SD BM", funcao="Condutor", status="extraordinario"),
            ],
        )

    def download_pdf(self, id_procedimento: str, output_path: str | None = None, id_documento: str | None = None) -> str:
        path = output_path or tempfile.mktemp(prefix="sei_", suffix=".pdf")
        Path(path).write_bytes(b"%PDF-1.4 fake process pdf")
        self.generated_pdf_paths.append(path)
        return path

    def download_document_pdf(self, id_documento: str, id_procedimento: str, output_path: str | None = None) -> str:
        path = output_path or tempfile.mktemp(prefix="sei_doc_", suffix=".pdf")
        Path(path).write_bytes(b"%PDF-1.4 fake document pdf")
        self.generated_pdf_paths.append(path)
        return path

    def get_block_documents(self, block_numero: str) -> list[BlockDocument]:
        return list(self.block_documents_map.get(block_numero, []))

    def add_document_to_block(
        self,
        id_procedimento: str,
        id_documento: str,
        block_numero: str,
        *,
        disponibilizar: bool = False,
    ) -> dict[str, Any]:
        self.last_block_add = {
            "id_procedimento": id_procedimento,
            "id_documento": id_documento,
            "block_numero": block_numero,
            "disponibilizar": disponibilizar,
        }
        self.block_documents_map.setdefault(block_numero, []).append(
            BlockDocument(
                seq=str(len(self.block_documents_map.get(block_numero, [])) + 1),
                processo="08810058.000128/2026-69",
                documento_id=id_documento,
                tipo_documento="Solicitação de Reaprazamento",
                assinante="",
                numero_sei="39860248",
                numero_documento="39860248",
                assinado=False,
            )
        )
        return {
            "ok": True,
            "message": f"Documento {id_documento} incluído no bloco {block_numero}",
        }

    def remove_document_from_block(self, id_documento: str, block_numero: str) -> dict[str, Any]:
        docs = self.block_documents_map.get(block_numero, [])
        self.block_documents_map[block_numero] = [
            doc for doc in docs if doc.documento_id != id_documento and doc.numero_sei != id_documento
        ]
        return {"ok": True, "message": f"Documento {id_documento} removido do bloco {block_numero}"}

    def disponibilizar_block(self, block_numero: str) -> dict[str, Any]:
        for block in self.blocks:
            if block.numero == block_numero:
                block.estado = "Disponibilizado"
                return {"ok": True, "message": f"Bloco {block_numero} — estado: {block.estado}"}
        return {"ok": False, "message": f"Bloco {block_numero} não encontrado"}

    def sign_document(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
        self.signed_documents.append(
            {"id_documento": id_documento, "id_procedimento": id_procedimento}
        )
        for docs in self.block_documents_map.values():
            for doc in docs:
                if doc.documento_id == id_documento:
                    doc.assinado = True
        return {"doc_ids": [id_documento], "signed": [id_documento], "already_signed": [], "errors": []}

    def authenticate_document(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
        self.authenticated_documents.append(
            {"id_documento": id_documento, "id_procedimento": id_procedimento}
        )
        return {"doc_ids": [id_documento], "signed": [id_documento], "already_signed": [], "errors": []}

    def get_document_sign_form_info(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
        if id_procedimento != "47607237":
            return {"ok": False, "error": "processo nao suportado no fake"}
        usuario = self.status().usuario
        mapping = {
            "48568466": {
                "ok": True,
                "txtUsuario": usuario,
                "hdnIdUsuario": "123",
                "selCargoFuncao": "2º Tenente QOEM BM",
                "sign_url": "controlador.php?acao=documento_assinar&id_documento=48568466",
            },
            "48568461": {
                "ok": True,
                "txtUsuario": usuario,
                "hdnIdUsuario": "123",
                "selCargoFuncao": "2º Tenente QOEM BM",
                "sign_url": "controlador.php?acao=documento_assinar&id_documento=48568461",
            },
            "48568463": {
                "ok": False,
                "error": "documento externo sem formulario de assinatura",
            },
        }
        return mapping.get(id_documento, {"ok": False, "error": "formulario indisponivel"})

    def get_actions(self, id_procedimento: str, id_documento: str | None = None) -> dict[str, str]:
        if id_procedimento != "47607237":
            return {}
        if id_documento == "48568466":
            return {
                "linkEditarConteudo": "controlador.php?acao=editor_montar&id_documento=48568466",
                "linkAssinarDocumento": "controlador.php?acao=documento_assinar&id_documento=48568466",
            }
        if id_documento == "48568468":
            return {}
        if id_documento is not None:
            return {}
        return {
            "linkIncluirDocumento": "controlador.php?acao=documento_escolher_tipo&id_procedimento=47607237",
            "linkConsultarAlterarProcesso": "controlador.php?acao=procedimento_alterar&id_procedimento=47607237",
            "linkEnviarProcesso": "controlador.php?acao=procedimento_enviar&id_procedimento=47607237",
            "linkMarcador": "controlador.php?acao=andamento_marcador_gerenciar&id_procedimento=47607237",
        }

    def _open_process_page(self, id_procedimento: str) -> str:
        if id_procedimento == "47607237":
            return """
            <html><body>
              <a href="controlador.php?acao=procedimento_reabrir&id_procedimento=47607237">Reabrir</a>
              <a href="controlador.php?acao=procedimento_concluir&id_procedimento=47607237">Concluir</a>
              <a href="controlador.php?acao=procedimento_enviar&id_procedimento=47607237">Enviar</a>
            </body></html>
            """
        return "<html><body></body></html>"

    def _extract_action_url(self, html: str, token: str) -> str | None:
        if token == "procedimento_reabrir" and "procedimento_reabrir" in html:
            return "https://sei.rn.gov.br/sei/controlador.php?acao=procedimento_reabrir&id_procedimento=47607237"
        return None

    def get_tramitar_form(self, id_procedimento: str, _proc_html: str | None = None) -> TramitarForm:
        return TramitarForm(
            action="https://sei.rn.gov.br/sei/controlador.php?acao=procedimento_enviar_executar",
            hidden_fields={"infra_hash": "abc"},
            select_fields={},
            destino_field="selUnidades",
            manter_aberto_field="chkSinManterAberto",
            retorno_programado_fields={
                "radio": "rdoPrazoRetornoProgramado",
                "data": "txtPrazoRetornoProgramado",
                "dias": "txtDiasRetornoProgramado",
                "uteis": "chkSinDiasUteisRetornoProgramado",
            },
            reabertura_programada_fields={
                "radio": "rdoPrazoReaberturaProgramada",
                "data": "txtPrazoReaberturaProgramada",
                "dias": "txtDiasReaberturaProgramada",
                "uteis": "chkSinDiasUteisReaberturaProgramada",
            },
            destinos=[
                TramitarDestino(id_unidade="110006929", nome="PAD-PDF"),
                TramitarDestino(id_unidade="110008367", nome="CMDO PABM APODI"),
            ],
            ajax_url="https://sei.rn.gov.br/sei/controlador_ajax.php?acao_ajax=unidade_auto_completar_envio_processo",
        )

    def _resolve_unit_id(self, unidade: str) -> str:
        mapping = {
            "pad-pdf": "110006929",
            "cmdo pabm apodi": "110008367",
            "110006929": "110006929",
            "110008367": "110008367",
        }
        return mapping[unidade.lower()]

    def _resolve_unit_id_ajax(
        self,
        unidade: str,
        _ajax_url: str | None,
        descriptions: dict[str, str] | None = None,
    ) -> str:
        unit_id = self._resolve_unit_id(unidade)
        if descriptions is not None:
            reverse = {
                "110006929": "PAD-PDF",
                "110008367": "CMDO PABM APODI",
            }
            descriptions[unit_id] = reverse[unit_id]
        return unit_id

    def enviar_processo(
        self,
        id_procedimento: str,
        unidades_destino: str | list[str],
        manter_aberto: bool = True,
        retorno_em: str | None = None,
        retorno_dias: str | None = None,
        retorno_dias_uteis: bool = False,
        reabrir_em: str | None = None,
        reabrir_dias: str | None = None,
        reabrir_dias_uteis: bool = False,
    ) -> bool:
        if isinstance(unidades_destino, str):
            unidades_destino = [unidades_destino]
        self.forwarded_processes.append(
            {
                "id_procedimento": id_procedimento,
                "unidades_destino": list(unidades_destino),
                "manter_aberto": manter_aberto,
                "retorno_em": retorno_em,
                "retorno_dias": retorno_dias,
                "retorno_dias_uteis": retorno_dias_uteis,
                "reabrir_em": reabrir_em,
                "reabrir_dias": reabrir_dias,
                "reabrir_dias_uteis": reabrir_dias_uteis,
            }
        )
        return True

    def list_process_open_units(self, id_procedimento: str) -> list[str]:
        if not self.forwarded_processes:
            return ["OP 3"]
        last = self.forwarded_processes[-1]
        open_units = list(last["unidades_destino"])
        if last["manter_aberto"]:
            open_units.append("OP 3")
        return open_units

    def get_concluir_form(self, id_procedimento: str) -> dict[str, Any]:
        assert id_procedimento == "47607237"
        return {
            "action": "controlador.php?acao=procedimento_concluir_executar&id_procedimento=47607237",
            "hidden_fields": {"infra_hash": "abc"},
            "reabertura_programada_fields": {
                "radio": "rdoPrazoReaberturaProgramada",
                "data": "txtPrazoReaberturaProgramada",
                "dias": "txtDiasReaberturaProgramada",
                "uteis": "chkSinDiasUteisReaberturaProgramada",
            },
            "supports_reopen_schedule": True,
        }

    def concluir_processo(
        self,
        id_procedimento: str,
        *,
        reabrir_em: str | None = None,
        reabrir_dias: str | None = None,
        reabrir_dias_uteis: bool = False,
    ) -> bool:
        self.concluded_processes.append(
            {
                "id_procedimento": id_procedimento,
                "reabrir_em": reabrir_em,
                "reabrir_dias": reabrir_dias,
                "reabrir_dias_uteis": reabrir_dias_uteis,
            }
        )
        return True

    def reabrir_processo(self, id_procedimento: str) -> bool:
        self.reopened_processes.append(id_procedimento)
        return True

    def check_reopen_available(self, id_procedimento: str) -> bool:
        return id_procedimento == "47607237"

    def list_process_history_units(self, id_procedimento: str) -> list[str]:
        return list(self.history_units.get(id_procedimento, []))

    def create_process(
        self,
        tipo_processo_id: str,
        *,
        especificacao: str = "",
        interessados: str = "",
        observacoes: str = "",
        nivel_acesso: str = "0",
        extra_fields: dict[str, str] | None = None,
    ) -> dict[str, str]:
        return {
            "numero": "08810058.000999/2026-01",
            "id_procedimento": "49999999",
            "link": "https://sei.rn.gov.br/sei/controlador.php?id_procedimento=49999999",
            "tipo_processo_id": tipo_processo_id,
            "especificacao": especificacao,
            "interessados": interessados,
            "observacoes": observacoes,
            "nivel_acesso": nivel_acesso,
            "extra_fields": extra_fields or {},
        }

    def get_process_creation_metadata(self, tipo_processo_id: str, *, nivel_acesso: str = "0") -> dict[str, Any]:
        if nivel_acesso == "2":
            return {
                "tipo_processo_id": tipo_processo_id,
                "nivel_acesso_field": "rdoNivelAcesso",
                "access_hypotheses": [
                    {
                        "field_name": "selGrauSigilo",
                        "field_id": "selGrauSigilo",
                        "field_label": "Grau de Sigilo",
                        "hidden_field_name": None,
                        "options": [
                            {"value": "U", "label": "Ultrassecreto", "selected": False},
                            {"value": "S", "label": "Secreto", "selected": False},
                            {"value": "R", "label": "Reservado", "selected": False},
                        ],
                    },
                    {
                        "field_name": "selHipoteseLegal",
                        "field_id": "selHipoteseLegal",
                        "field_label": "Hipótese Legal",
                        "hidden_field_name": "hdnHipoteseLegal",
                        "options": [
                            {"value": "19", "label": "Segurança de Instituições ou de Altas Autoridades", "selected": False},
                            {"value": "23", "label": "Segredo de Procedimentos Disciplinares - Sigiloso", "selected": False},
                        ],
                    },
                ],
                "warnings": [],
            }
        return {
            "tipo_processo_id": tipo_processo_id,
            "nivel_acesso_field": "rdoNivelAcesso",
            "access_hypotheses": [
                {
                    "field_name": "selHipoteseLegal",
                    "field_id": "selHipoteseLegal",
                    "field_label": "Hipótese Legal",
                    "hidden_field_name": "hdnHipoteseLegal",
                    "options": [
                        {"value": "LGPD", "label": "Dados pessoais / LGPD", "selected": False},
                        {"value": "ADM", "label": "Processo administrativo", "selected": False},
                    ],
                }
            ] if nivel_acesso != "0" else [],
            "warnings": [],
        }

    def list_document_types(self, id_procedimento: str) -> list[DocumentType]:
        if id_procedimento != "47607237":
            return []
        return [
            DocumentType(id_serie="5", nome="Despacho"),
            DocumentType(id_serie="292", nome="Parte Genérica"),
            DocumentType(id_serie="178", nome="Solicitação"),
            DocumentType(id_serie="92", nome="Informação"),
        ]

    def get_document_creation_metadata(
        self,
        id_procedimento: str,
        tipo: str,
        *,
        nivel_acesso: str = "0",
    ) -> dict[str, Any]:
        tipo_id = self.DOC_TYPES.get(tipo.lower().replace(" ", "_"), tipo)
        base = {
            "id_procedimento": id_procedimento,
            "tipo_documento_id": tipo_id,
            "tipo_documento": tipo,
            "texto_inicial_options": [
                {"value": "N", "label": "Nenhum"},
                {"value": "T", "label": "Texto Padrão"},
                {"value": "D", "label": "Documento Modelo"},
            ],
            "nivel_acesso_field": "rdoNivelAcesso",
            "warnings": [],
        }
        if nivel_acesso == "2":
            base["access_hypotheses"] = [
                {
                    "field_name": "selGrauSigilo",
                    "field_id": "selGrauSigilo",
                    "field_label": "Grau de Sigilo",
                    "hidden_field_name": None,
                    "options": [
                        {"value": "U", "label": "Ultrassecreto", "selected": False},
                        {"value": "S", "label": "Secreto", "selected": False},
                        {"value": "R", "label": "Reservado", "selected": False},
                    ],
                },
                {
                    "field_name": "selHipoteseLegal",
                    "field_id": "selHipoteseLegal",
                    "field_label": "Hipótese Legal",
                    "hidden_field_name": "hdnHipoteseLegal",
                    "options": [
                        {"value": "19", "label": "Segurança de Instituições ou de Altas Autoridades", "selected": False},
                        {"value": "23", "label": "Segredo de Procedimentos Disciplinares - Sigiloso", "selected": False},
                    ],
                },
            ]
        elif nivel_acesso == "1":
            base["access_hypotheses"] = [
                {
                    "field_name": "selHipoteseLegal",
                    "field_id": "selHipoteseLegal",
                    "field_label": "Hipótese Legal",
                    "hidden_field_name": "hdnHipoteseLegal",
                    "options": [
                        {"value": "4", "label": "Informação Pessoal", "selected": False},
                        {"value": "33", "label": "Dados Pessoais e Dados Pessoais Sensíveis", "selected": False},
                    ],
                }
            ]
        else:
            base["access_hypotheses"] = []
        return base

    def get_process_access_metadata(self, id_procedimento: str) -> dict[str, Any]:
        assert id_procedimento == "47607237"
        return {
            "id_procedimento": id_procedimento,
            "nivel_acesso": "1",
            "available_hypotheses": [
                {
                    "field_name": "selHipoteseLegal",
                    "field_id": "selHipoteseLegal",
                    "field_label": "Hipótese Legal",
                    "hidden_field_name": "hdnHipoteseLegal",
                    "options": [
                        {"value": "4", "label": "Informação Pessoal", "selected": True},
                        {"value": "33", "label": "Dados Pessoais e Dados Pessoais Sensíveis", "selected": False},
                    ],
                }
            ],
            "selected_hypothesis": {
                "field_name": "selHipoteseLegal",
                "field_label": "Hipótese Legal",
                "hidden_field_name": "hdnHipoteseLegal",
                "value": "4",
                "label": "Informação Pessoal",
            },
            "selected_extra_fields": {
                "selHipoteseLegal": "4",
                "hdnHipoteseLegal": "4",
            },
            "warnings": [],
        }

    def create_document(
        self,
        id_procedimento: str,
        tipo: str,
        *,
        nivel_acesso: str = "0",
        texto_inicial: str = "N",
        descricao: str = "",
        interessados: str = "",
        extra_fields: dict[str, str] | None = None,
    ) -> DocumentCreated:
        self.last_created_document = {
            "id_procedimento": id_procedimento,
            "tipo": tipo,
            "nivel_acesso": nivel_acesso,
            "texto_inicial": texto_inicial,
            "descricao": descricao,
            "interessados": interessados,
            "extra_fields": extra_fields or {},
        }
        return DocumentCreated(
            id_documento="59999999",
            id_procedimento=id_procedimento,
            tipo=tipo,
            editor_url="https://sei.rn.gov.br/sei/controlador.php?acao=editor_montar&id_documento=59999999",
        )

    def get_editor_sections(self, id_documento: str, id_procedimento: str) -> tuple[str, list[EditorSection]]:
        return (
            "https://sei.rn.gov.br/sei/editor/editor_processar.php?acao=editor_salvar&id_documento=59999999",
            [
                EditorSection(name="txaEditor_101", content="<p>Cabecalho</p>", section_id="101", editable=False),
                EditorSection(name="txaEditor_422", content="<p>Conteudo atual do despacho</p>", section_id="422", editable=True),
            ],
        )

    def edit_document_section(
        self,
        id_documento: str,
        id_procedimento: str,
        section_id: str,
        new_raw_html: str,
    ) -> bool:
        self.last_edit = {
            "id_documento": id_documento,
            "id_procedimento": id_procedimento,
            "section_id": section_id,
            "content": new_raw_html,
        }
        return True


class FakeClientLegacySwitch(FakeClient):
    def switch_unit(self, keyword: str) -> bool:
        self.switched_to = keyword
        return True


class AmbiguousUnitClient(FakeClient):
    def _resolve_unit_id_ajax(
        self,
        unidade: str,
        _ajax_url: str | None,
        descriptions: dict[str, str] | None = None,
    ) -> str:
        raise RuntimeError(
            "Unidade 'CHEFIA SAT' é ambígua. Especifique uma destas: DAT-1CAT CHEFIA, DAT CHEFIA 1ºSAT/1ºCAT"
        )


class EmptyCreateDocumentClient(FakeClient):
    def create_document(
        self,
        id_procedimento: str,
        tipo: str,
        *,
        nivel_acesso: str = "0",
        texto_inicial: str = "N",
        descricao: str = "",
        interessados: str = "",
        extra_fields: dict[str, str] | None = None,
    ) -> DocumentCreated:
        self.last_created_document = {
            "id_procedimento": id_procedimento,
            "tipo": tipo,
            "nivel_acesso": nivel_acesso,
            "texto_inicial": texto_inicial,
            "descricao": descricao,
            "interessados": interessados,
            "extra_fields": extra_fields or {},
        }
        return DocumentCreated(
            id_documento="",
            id_procedimento=id_procedimento,
            tipo=tipo,
            editor_url=None,
        )


def test_inbox_snapshot_contract() -> None:
    result = inbox_snapshot(FakeClient())

    assert result["ok"] is True
    assert result["schema_version"] == "1"
    assert result["operation"] == "inbox-snapshot"
    assert result["context"]["unidade_sigla"] == "OP 3"
    assert result["data"]["recebidos_total"] == 2
    assert result["data"]["blocos_total"] == 1
    assert result["next_actions"][0]["action"] == "process-open"


def test_process_open_contract() -> None:
    result = process_open(FakeClient(), "08810058.000128/2026-69")

    assert result["ok"] is True
    assert result["resolved_ids"]["id_procedimento"] == "47607237"
    assert result["data"]["documents_total"] == 8
    assert result["data"]["documents"][0]["sei_number"] == "39860248"


def test_process_open_resolves_human_number_from_id() -> None:
    result = process_open(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["resolved_ids"]["numero_processo"] == "08810058.000128/2026-69"


def test_document_read_contract() -> None:
    result = document_read(FakeClient(), "39860248")

    assert result["ok"] is True
    assert result["resolved_ids"]["id_documento"] == "48568466"
    assert result["data"]["documento"]["nome"] == "Solicitação de Reaprazamento"
    assert result["data"]["line_count"] == 4
    assert result["data"]["ui_context"]["process_open_in_current_unit"] is True
    assert result["data"]["action_context"]["can_edit_document"] is True
    assert result["data"]["semantic_context"]["document_kind_guess"] == "reaprazamento"
    assert result["data"]["semantic_context"]["involved_military"][0]["display_name"] == "3º SGT BM João Silva"
    assert result["data"]["domain_context"]["fields"]["requested_date"] == "20/04/2026"
    assert result["next_actions"][0]["action"] == "process-open"


def test_document_read_pdf_supports_binary_extraction() -> None:
    result = document_read(FakeClient(), "48568469", id_procedimento="47607237")

    assert result["ok"] is True
    assert result["data"]["documento"]["tipo"] == "pdf"
    assert result["data"]["extraction_method"] in {"read_document_content", "download_document_pdf"}
    assert result["data"]["semantic_context"]["information_only"] is True


def test_document_read_pdf_resolves_sei_number_with_process_id() -> None:
    result = document_read(FakeClient(), "39860251", id_procedimento="47607237")

    assert result["ok"] is True
    assert result["resolved_ids"]["id_documento"] == "48568469"
    assert result["resolved_ids"]["numero_documento"] == "39860251"
    assert result["data"]["documento"]["tipo"] == "pdf"


def test_document_read_resolves_human_number_from_internal_ids() -> None:
    result = document_read(FakeClient(), "48568466", id_procedimento="47607237")

    assert result["ok"] is True
    assert result["resolved_ids"]["numero_documento"] == "39860248"


class SignedMarkerDocumentClient(FakeClient):
    def read_document(self, id_documento: str, id_procedimento: str) -> str:
        if (id_documento, id_procedimento) == ("48568466", "47607237"):
            return (
                "Despacho de teste.\n"
                "Assinado eletronicamente por LEO ZENON TASSI, 2º Tenente QOEM BM.\n"
            )
        return super().read_document(id_documento, id_procedimento)


def test_document_read_marks_document_signed_from_text_marker() -> None:
    result = document_read(SignedMarkerDocumentClient(), "48568466", id_procedimento="47607237")

    assert result["ok"] is True
    assert result["data"]["documento"]["assinado"] is True


def test_document_read_not_found() -> None:
    result = document_read(FakeClient(), "00000000")

    assert result["ok"] is False
    assert result["error"]["code"] == "document_not_found"


def test_process_read_contract() -> None:
    result = process_read(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["operation"] == "process-read"
    assert result["data"]["documents_total"] == 8
    assert result["data"]["signed_total"] == 3
    assert result["data"]["relatorios_total"] == 2
    assert result["data"]["selection"]["mode_requested"] == "summary"
    assert result["data"]["selection"]["documents_selected_total"] == 6
    assert len(result["data"]["documents_read"]) == 6
    assert result["data"]["read_summary"]["documents_succeeded_total"] == 6
    assert result["data"]["read_summary"]["documents_failed_total"] == 0
    assert result["data"]["read_summary"]["pdf_selected_total"] == 1
    assert result["data"]["process_context"]["process_kind_guess"] == "reaprazamento"
    assert result["data"]["process_context"]["action_required"] is True
    assert any(item["extraction_method"] in {"read_document_content", "download_document_pdf"} for item in result["data"]["documents_read"])
    assert result["next_actions"][0]["action"] == "document-read"


def test_process_read_date_filter_reads_only_matching_title_dates() -> None:
    result = process_read(
        FakeClient(),
        "47607237",
        mode="all",
        date_from="20/04/2026",
        date_to="22/04/2026",
    )

    assert result["ok"] is True
    assert result["data"]["selection"]["documents_matching_filter_total"] == 3
    assert result["data"]["selection"]["documents_selected_total"] == 3
    assert [item["documento"]["sei_number"] for item in result["data"]["documents_read"] if item["ok"]] == [
        "39860249",
        "39860250",
        "39860251",
    ]
    assert result["data"]["documents_read"][-1]["extraction_method"] in {"read_document_content", "download_document_pdf"}
    assert result["data"]["process_context"]["has_relatorio_operacional"] is True


def test_process_summary_contract() -> None:
    result = process_summary(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["operation"] == "process-summary"
    assert result["data"]["process_kind_guess"] == "reaprazamento"
    assert result["data"]["action_required"] is True
    assert result["data"]["read_summary"]["documents_failed_total"] == 0
    assert result["data"]["key_documents"]
    assert result["data"]["action_items"]


def test_marker_catalog_contract() -> None:
    result = marker_catalog(FakeClient())

    assert result["ok"] is True
    assert result["operation"] == "marker-catalog"
    assert result["data"]["markers_total"] == 4
    assert result["data"]["markers"][0]["marcador_id"] == "10"


def test_process_marker_preview_contract() -> None:
    result = process_marker_preview(FakeClient(), "47607237", marker="Férias / Dispensas")

    assert result["ok"] is True
    assert result["operation"] == "process-marker-preview"
    assert result["data"]["selected_marker"]["marcador_id"] == "11"
    assert result["data"]["suggested_marker_text"]
    assert "Leitura" not in result["data"]["suggested_marker_text"]


def test_process_marker_read_contract() -> None:
    result = process_marker_read(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["operation"] == "process-marker-read"
    assert result["data"]["current_markers_total"] == 1
    assert result["data"]["current_markers"][0]["texto"] == "Sd José Junior 15/03 - 13/04"


def test_process_marker_history_contract() -> None:
    result = process_marker_history(FakeClient(), "47607237", marker="11")

    assert result["ok"] is True
    assert result["operation"] == "process-marker-history"
    assert result["data"]["selected_marker"]["marcador_id"] == "11"
    assert result["data"]["history_total"] == 1
    assert result["data"]["history"][0]["acao"] == "Aplicado"
    assert result["data"]["history"][0]["data_only"] == "31/03/2026"
    assert result["data"]["history"][0]["hora"] == "11:00"
    assert result["data"]["history_summary"]["actions"] == ["Aplicado"]


def test_process_marker_set_preview_contract() -> None:
    result = process_marker_set_preview(FakeClient(), "47607237", marker="12")

    assert result["ok"] is True
    assert result["operation"] == "process-marker-set-preview"
    assert result["data"]["selected_marker"]["marcador_id"] == "12"
    assert result["data"]["confirmation_required"] is True


def test_process_marker_set_confirm_contract() -> None:
    client = FakeClient()
    result = process_marker_set_confirm(
        client,
        "47607237",
        marker="12",
        texto="Processo apenas informativo.",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "process-marker-set-confirm"
    assert client.process_markers["47607237"]["id"] == "12"
    assert client.process_markers["47607237"]["texto"] == "Processo apenas informativo."


def test_process_marker_remove_preview_contract() -> None:
    result = process_marker_remove_preview(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["operation"] == "process-marker-remove-preview"
    assert result["data"]["confirmation_required"] is True


def test_process_marker_remove_preview_selects_marker_by_name() -> None:
    result = process_marker_remove_preview(FakeClient(), "47607237", marker="Férias / Dispensas")

    assert result["ok"] is True
    assert result["data"]["selected_marker"]["marcador_id"] == "11"


def test_process_marker_remove_confirm_contract() -> None:
    client = FakeClient()
    result = process_marker_remove_confirm(client, "47607237", confirm=True)

    assert result["ok"] is True
    assert result["operation"] == "process-marker-remove-confirm"
    assert "47607237" not in client.process_markers


def test_process_marker_remove_confirm_uses_selected_marker() -> None:
    client = FakeClient()
    result = process_marker_remove_confirm(client, "47607237", marker="11", confirm=True)

    assert result["ok"] is True
    assert result["data"]["selected_marker"]["marcador_id"] == "11"


def test_process_marker_update_preview_contract() -> None:
    result = process_marker_update_preview(FakeClient(), "47607237", marker="11")

    assert result["ok"] is True
    assert result["operation"] == "process-marker-update-preview"
    assert result["data"]["selected_marker"]["marcador_id"] == "11"
    assert result["data"]["mutation_preview"]["current_text"] == "Sd José Junior 15/03 - 13/04"


def test_process_marker_update_confirm_contract() -> None:
    client = FakeClient()
    result = process_marker_update_confirm(
        client,
        "47607237",
        marker="11",
        texto="Aguardando manifestação até 15/04.",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "process-marker-update-confirm"
    assert client.process_markers["47607237"]["texto"] == "Aguardando manifestação até 15/04."


def test_process_create_preview_contract() -> None:
    result = process_create_preview(
        FakeClient(),
        "ferias",
        especificacao="Reaprazamento de férias do 3º SGT BM João Silva",
        nivel_acesso="privado",
        hipotese_acesso="LGPD",
    )

    assert result["ok"] is True
    assert result["operation"] == "process-create-preview"
    assert result["resolved_ids"]["tipo_processo_id"] == "100000182"
    assert result["data"]["preflight"]["will_create_in_current_unit"] is True
    assert result["data"]["access_policy"]["nivel_codigo"] == "1"
    assert result["data"]["access_policy"]["nivel_label"] == "restrito"
    assert result["data"]["access_policy"]["available_hypotheses"]
    assert result["data"]["access_policy"]["selected_hypothesis"]["value"] == "LGPD"
    assert result["warnings"]


def test_process_pdf_preview_contract(tmp_path) -> None:
    output = tmp_path / "processo.pdf"
    result = process_pdf_preview(FakeClient(), "47607237", output_path=str(output))

    assert result["ok"] is True
    assert result["operation"] == "process-pdf-preview"
    assert result["resolved_ids"]["id_procedimento"] == "47607237"
    assert result["data"]["download_preview"]["output_path"] == str(output)


def test_process_pdf_confirm_contract(tmp_path) -> None:
    client = FakeClient()
    output = tmp_path / "processo.pdf"
    result = process_pdf_confirm(client, "47607237", output_path=str(output), confirm=True)

    assert result["ok"] is True
    assert result["operation"] == "process-pdf-confirm"
    assert result["data"]["download"]["path"] == str(output)
    assert output.exists()


def test_document_pdf_preview_contract(tmp_path) -> None:
    output = tmp_path / "documento.pdf"
    result = document_pdf_preview(
        FakeClient(),
        "39860248",
        process_id="47607237",
        output_path=str(output),
    )

    assert result["ok"] is True
    assert result["operation"] == "document-pdf-preview"
    assert result["resolved_ids"]["id_documento"] == "48568466"
    assert result["resolved_ids"]["id_procedimento"] == "47607237"
    assert result["resolved_ids"]["numero_documento"] == "39860248"
    assert result["data"]["download_preview"]["output_path"] == str(output)


def test_document_pdf_confirm_contract(tmp_path) -> None:
    client = FakeClient()
    output = tmp_path / "documento.pdf"
    result = document_pdf_confirm(
        client,
        "39860248",
        process_id="47607237",
        output_path=str(output),
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "document-pdf-confirm"
    assert result["data"]["download"]["path"] == str(output)
    assert output.exists()


def test_environment_triage_preview_contract() -> None:
    result = environment_triage_preview(FakeClient(), limit=5)

    assert result["ok"] is True
    assert result["operation"] == "environment-triage-preview"
    assert result["data"]["filters"]["mode"] == "contextual"
    assert result["data"]["candidates_selected_total"] >= 2
    assert any("new" in item["triage_reason"] for item in result["data"]["candidates"])
    assert any("unmarked" in item["triage_reason"] for item in result["data"]["candidates"])
    assert any(item.get("context_document") for item in result["data"]["candidates"])


def test_environment_triage_preview_fast_mode_avoids_document_reads() -> None:
    class CountingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.read_calls = 0

        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            self.read_calls += 1
            return super().read_document(id_documento, id_procedimento)

    client = CountingClient()
    result = environment_triage_preview(client, limit=5, mode="fast")

    assert result["ok"] is True
    assert result["data"]["filters"]["mode"] == "fast"
    assert client.read_calls == 0


def test_environment_triage_preview_contextual_reads_at_most_one_doc_per_candidate() -> None:
    class CountingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.read_calls = 0

        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            self.read_calls += 1
            return super().read_document(id_documento, id_procedimento)

    client = CountingClient()
    result = environment_triage_preview(client, limit=3, mode="contextual")

    assert result["ok"] is True
    assert result["data"]["filters"]["mode"] == "contextual"
    assert client.read_calls <= result["data"]["candidates_selected_total"]
    assert all("summary" in item for item in result["data"]["candidates"])


def test_environment_triage_apply_contract() -> None:
    client = FakeClient()
    result = environment_triage_apply(client, only_unmarked=True, limit=5, confirm=True)

    assert result["ok"] is True
    assert result["operation"] == "environment-triage-apply"
    assert result["data"]["applied_total"] >= 1


def test_process_finalize_preview_separates_auth_and_sign_and_blocks_other_signer() -> None:
    result = process_finalize_preview(FakeClient(), "47607237", document_ids=["39860248", "39860241", "39860243"])

    assert result["ok"] is True
    assert result["operation"] == "process-finalize-preview"
    assert result["data"]["authenticate_document_ids"] == ["48568463"]
    assert result["data"]["sign_document_ids"] == ["48568466"]
    blocked = next(item for item in result["data"]["documents"] if item["id_documento"] == "48568461")
    assert blocked["recommended_action"] == "skip"
    assert blocked["reason"] == "tail_indicates_other_signer"
    assert blocked["override_allowed"] is True
    assert blocked["form_signer"]["txtUsuario"] == "Fulano"


def test_process_finalize_confirm_executes_only_safe_actions() -> None:
    client = FakeClient()
    result = process_finalize_confirm(
        client,
        "47607237",
        document_ids=["39860248", "39860241", "39860243"],
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "process-finalize-confirm"
    assert client.signed_documents == [{"id_documento": "48568466", "id_procedimento": "47607237"}]
    assert client.authenticated_documents == [{"id_documento": "48568463", "id_procedimento": "47607237"}]
    assert result["data"]["skipped_total"] == 1


def test_process_finalize_confirm_force_sign_allows_ambiguous_tail_when_form_matches() -> None:
    class AmbiguousTailClient(FakeClient):
        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            if (id_documento, id_procedimento) == ("48568461", "47607237"):
                return (
                    "Encaminhamento interno.\n"
                    "Providencias cabiveis.\n"
                    "2º TEN QOEM Chefe da 1ª Seção.\n"
                )
            return super().read_document(id_documento, id_procedimento)

    client = AmbiguousTailClient()
    preview = process_finalize_preview(client, "47607237", document_ids=["39860241"])

    assert preview["ok"] is True
    doc = preview["data"]["documents"][0]
    assert doc["recommended_action"] == "skip"
    assert doc["reason"] == "tail_ambiguous_review_required"
    assert doc["override_allowed"] is True

    result = process_finalize_confirm(
        client,
        "47607237",
        document_ids=["39860241"],
        force_sign_document_ids=["39860241"],
        confirm=True,
    )

    assert result["ok"] is True
    assert result["data"]["signed_total"] == 1
    assert client.signed_documents == [{"id_documento": "48568461", "id_procedimento": "47607237"}]


def test_process_finalize_confirm_force_sign_still_blocks_when_form_does_not_match() -> None:
    class WrongFormClient(FakeClient):
        def get_document_sign_form_info(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
            data = super().get_document_sign_form_info(id_documento, id_procedimento)
            if id_documento == "48568461":
                data["txtUsuario"] = "Jorge Wagner"
                data["selCargoFuncao"] = "Cabo QPBM"
            return data

        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            if (id_documento, id_procedimento) == ("48568461", "47607237"):
                return (
                    "Encaminhamento interno.\n"
                    "Providencias cabiveis.\n"
                    "2º TEN QOEM Chefe da 1ª Seção.\n"
                )
            return super().read_document(id_documento, id_procedimento)

    client = WrongFormClient()
    result = process_finalize_confirm(
        client,
        "47607237",
        document_ids=["39860241"],
        force_sign_document_ids=["39860241"],
        confirm=True,
    )

    assert result["ok"] is True
    assert result["data"]["signed_total"] == 0
    assert result["data"]["skipped_total"] == 1
    assert client.signed_documents == []


def test_process_finalize_preview_extracts_fragmented_footer_signer() -> None:
    class FragmentedFooterClient(FakeClient):
        def status(self) -> SystemStatus:
            return SystemStatus(
                valid=True,
                unidade_sigla="OP 3",
                unidade_descricao="Operacional 3",
                usuario="Leo Zenon Tassi",
                ultimo_acesso="29/03/2026 10:00",
            )

        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            if (id_documento, id_procedimento) == ("48568466", "47607237"):
                return (
                    "Despacho de teste.\n"
                    "Encaminhar para a secretaria.\n"
                    "Leo\n"
                    "Zenon\n"
                    "Tassi\n"
                    "-\n"
                    "2º TEN\n"
                    "QOEM\n"
                    "Referência:\n"
                    "Processo nº 08810198.000085/2026-17\n"
                    "SEI nº 40442193\n"
                    "Criado por\n"
                    "01664314431\n"
                    ", versão 2 por\n"
                    "01664314431\n"
                    "em 01/04/2026 15:51:48.\n"
                )
            return super().read_document(id_documento, id_procedimento)

    result = process_finalize_preview(FragmentedFooterClient(), "47607237", document_ids=["39860248"])

    assert result["ok"] is True
    doc = result["data"]["documents"][0]
    assert doc["recommended_action"] == "sign"
    assert doc["expected_signer"]["name"] == "Leo Zenon Tassi"


def test_process_finalize_preview_extracts_signer_without_referencia_footer() -> None:
    class NoReferenciaFooterClient(FakeClient):
        def status(self) -> SystemStatus:
            return SystemStatus(
                valid=True,
                unidade_sigla="OP 3",
                unidade_descricao="Operacional 3",
                usuario="Leo Zenon Tassi",
                ultimo_acesso="29/03/2026 10:00",
            )

        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            if (id_documento, id_procedimento) == ("48568466", "47607237"):
                return (
                    "Despacho de teste.\n"
                    "Encaminhar para a secretaria.\n"
                    "Leo\n"
                    "Zenon\n"
                    "Tassi\n"
                    "-\n"
                    "2º TEN\n"
                    "QOEM\n"
                )
            return super().read_document(id_documento, id_procedimento)

    result = process_finalize_preview(NoReferenciaFooterClient(), "47607237", document_ids=["39860248"])

    assert result["ok"] is True
    doc = result["data"]["documents"][0]
    assert doc["recommended_action"] == "sign"
    assert doc["expected_signer"]["name"] == "Leo Zenon Tassi"


def test_process_finalize_preview_strips_institutional_prefix_from_signer_name() -> None:
    class InstitutionalPrefixClient(FakeClient):
        def status(self) -> SystemStatus:
            return SystemStatus(
                valid=True,
                unidade_sigla="OP 3",
                unidade_descricao="Operacional 3",
                usuario="Leo Zenon Tassi",
                ultimo_acesso="29/03/2026 10:00",
            )

        def read_document(self, id_documento: str, id_procedimento: str) -> str:
            if (id_documento, id_procedimento) == ("48568466", "47607237"):
                return (
                    "Despacho de teste.\n"
                    "SEAD Leo Zenon Tassi\n"
                    "-\n"
                    "2º TEN\n"
                    "QOEM\n"
                    "Referência:\n"
                    "Processo nº 08810198.000085/2026-17\n"
                )
            return super().read_document(id_documento, id_procedimento)

    result = process_finalize_preview(InstitutionalPrefixClient(), "47607237", document_ids=["39860248"])

    assert result["ok"] is True
    doc = result["data"]["documents"][0]
    assert doc["expected_signer"]["name"] == "Leo Zenon Tassi"


def test_process_forward_preview_contract() -> None:
    result = process_forward_preview(
        FakeClient(),
        "47607237",
        destinos=["PAD-PDF", "CMDO PABM APODI"],
        manter_aberto=False,
        retorno_dias="7",
        retorno_dias_uteis=True,
        reabrir_em="05/04/2026",
        review_mode="summary",
    )

    assert result["ok"] is True
    assert result["operation"] == "process-forward-preview"
    assert result["resolved_ids"]["destination_unit_ids"] == ["110006929", "110008367"]
    assert result["data"]["forward_policy"]["fechar_na_unidade_atual"] is True
    assert result["data"]["forward_policy"]["retorno_dias"] == "7"
    assert result["data"]["forward_policy"]["retorno_dias_uteis"] is True
    assert result["data"]["forward_policy"]["scheduled_reopen_supported"] is True
    assert result["data"]["forward_policy"]["scheduled_return_supported"] is True
    assert result["data"]["destinations"][0]["nome"] == "PAD-PDF"


def test_process_forward_confirm_contract() -> None:
    client = FakeClient()
    result = process_forward_confirm(
        client,
        "47607237",
        destinos=["PAD-PDF"],
        manter_aberto=True,
        retorno_em="10/04/2026",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "process-forward-confirm"
    assert client.forwarded_processes == [
        {
            "id_procedimento": "47607237",
            "unidades_destino": ["110006929"],
            "manter_aberto": True,
            "retorno_em": "10/04/2026",
            "retorno_dias": None,
            "retorno_dias_uteis": False,
            "reabrir_em": None,
            "reabrir_dias": None,
            "reabrir_dias_uteis": False,
        }
    ]
    assert result["data"]["status_after"]["current_unit_still_open"] is True


def test_process_forward_preview_fails_closed_on_ambiguous_destination() -> None:
    result = process_forward_preview(
        AmbiguousUnitClient(),
        "47607237",
        destinos=["CHEFIA SAT"],
    )

    assert result["ok"] is False
    assert "ambígua" in result["error"]["message"]


def test_process_conclude_preview_contract() -> None:
    result = process_conclude_preview(
        FakeClient(),
        "47607237",
        reabrir_dias="5",
        reabrir_dias_uteis=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "process-conclude-preview"
    assert result["data"]["conclude_policy"]["reabrir_dias"] == "5"
    assert result["data"]["conclude_policy"]["reabrir_dias_uteis"] is True
    assert result["data"]["conclude_policy"]["scheduled_reopen_supported"] is True
    assert result["data"]["available_form_fields"]["rdoConcluir"] == "rdoConcluir"


def test_process_conclude_confirm_contract() -> None:
    client = FakeClient()
    result = process_conclude_confirm(
        client,
        "47607237",
        reabrir_em="05/04/2026",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "process-conclude-confirm"
    assert client.concluded_processes == [
        {
            "id_procedimento": "47607237",
            "reabrir_em": "05/04/2026",
            "reabrir_dias": None,
            "reabrir_dias_uteis": False,
        }
    ]


def test_process_reopen_preview_contract() -> None:
    result = process_reopen_preview(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["operation"] == "process-reopen-preview"
    assert result["data"]["reopen_available"] is True
    assert result["data"]["candidate_unit"] == "OP 3"
    assert result["data"]["confirmation_required"] is True


def test_process_reopen_confirm_contract() -> None:
    client = FakeClient()
    result = process_reopen_confirm(client, "47607237", confirm=True)

    assert result["ok"] is True
    assert result["operation"] == "process-reopen-confirm"
    assert client.reopened_processes == ["47607237"]


def test_process_create_preview_exposes_hypotheses_when_non_public_access_is_requested() -> None:
    result = process_create_preview(
        FakeClient(),
        "ferias",
        especificacao="Reaprazamento de férias do 3º SGT BM João Silva",
        nivel_acesso="restrito",
    )

    assert result["ok"] is True
    assert result["data"]["access_policy"]["available_hypotheses"]
    assert result["data"]["access_policy"]["selected_hypothesis"] is None


def test_process_create_preview_sigiloso_exposes_both_required_fields() -> None:
    result = process_create_preview(
        FakeClient(),
        "ferias",
        especificacao="Teste sigiloso",
        nivel_acesso="2",
    )

    assert result["ok"] is True
    fields = {item["field_name"] for item in result["data"]["access_policy"]["available_hypotheses"]}
    assert fields == {"selGrauSigilo", "selHipoteseLegal"}


def test_process_create_confirm_contract() -> None:
    logged: list[dict[str, Any]] = []
    import sei_cli.operations.writing as writing_ops

    original_append = writing_ops.append_created_process_log
    writing_ops.append_created_process_log = logged.append
    try:
        result = process_create_confirm(
            FakeClient(),
            "informacao",
            especificacao="Livro do fiscal do dia 30/03/2026",
            interessados="OP 3",
            observacoes="Criado para registro de serviço",
            nivel_acesso="0",
            confirm=True,
        )
    finally:
        writing_ops.append_created_process_log = original_append

    assert result["ok"] is True
    assert result["operation"] == "process-create-confirm"
    assert result["resolved_ids"]["id_procedimento"] == "49999999"
    assert result["data"]["created_process"]["numero"] == "08810058.000999/2026-01"
    assert result["next_actions"][0]["action"] == "process-open"
    assert logged[0]["id_procedimento"] == "49999999"


def test_process_create_confirm_requires_explicit_confirmation() -> None:
    result = process_create_confirm(
        FakeClient(),
        "informacao",
        especificacao="Livro do fiscal do dia 30/03/2026",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_process_create_confirm_requires_hypothesis_for_non_public_access() -> None:
    result = process_create_confirm(
        FakeClient(),
        "ferias",
        especificacao="Reaprazamento de férias do 3º SGT BM João Silva",
        nivel_acesso="restrito",
        confirm=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_process_create_confirm_applies_selected_hypothesis() -> None:
    logged: list[dict[str, Any]] = []
    import sei_cli.operations.writing as writing_ops

    original_append = writing_ops.append_created_process_log
    writing_ops.append_created_process_log = logged.append
    try:
        result = process_create_confirm(
            FakeClient(),
            "ferias",
            especificacao="Reaprazamento de férias do 3º SGT BM João Silva",
            nivel_acesso="restrito",
            hipotese_acesso="ADM",
            confirm=True,
        )
    finally:
        writing_ops.append_created_process_log = original_append

    assert result["ok"] is True
    assert result["data"]["access_policy"]["selected_hypothesis"]["value"] == "ADM"
    assert result["data"]["created_process"]["extra_fields"]["selHipoteseLegal"] == "ADM"
    assert result["data"]["created_process"]["extra_fields"]["hdnHipoteseLegal"] == "ADM"


def test_process_create_confirm_sigiloso_requires_both_fields() -> None:
    result = process_create_confirm(
        FakeClient(),
        "ferias",
        especificacao="Teste sigiloso",
        nivel_acesso="2",
        hipotese_acesso="selHipoteseLegal=23",
        confirm=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_process_create_confirm_sigiloso_applies_both_fields() -> None:
    logged: list[dict[str, Any]] = []
    import sei_cli.operations.writing as writing_ops

    original_append = writing_ops.append_created_process_log
    writing_ops.append_created_process_log = logged.append
    try:
        result = process_create_confirm(
            FakeClient(),
            "ferias",
            especificacao="Teste sigiloso",
            nivel_acesso="2",
            hipotese_acesso="selGrauSigilo=R,selHipoteseLegal=23",
            confirm=True,
        )
    finally:
        writing_ops.append_created_process_log = original_append

    assert result["ok"] is True
    selected = result["data"]["access_policy"]["selected_hypothesis"]
    assert isinstance(selected, list)
    assert {item["field_name"] for item in selected} == {"selGrauSigilo", "selHipoteseLegal"}
    assert result["data"]["created_process"]["extra_fields"]["selGrauSigilo"] == "R"
    assert result["data"]["created_process"]["extra_fields"]["selHipoteseLegal"] == "23"


def test_document_create_preview_contract() -> None:
    result = document_create_preview(
        FakeClient(),
        "47607237",
        "despacho",
        descricao="Despacho autorizando continuidade",
        nivel_acesso="1",
        hipotese_acesso="4",
        hipotese_campo="selHipoteseLegal",
    )

    assert result["ok"] is True
    assert result["operation"] == "document-create-preview"
    assert result["resolved_ids"]["tipo_documento_id"] == "5"
    assert result["data"]["document_type"]["nome"] == "Despacho"
    assert result["data"]["access_policy"]["selected_hypothesis"]["value"] == "4"


def test_document_create_preview_sigiloso_exposes_both_required_fields() -> None:
    result = document_create_preview(
        FakeClient(),
        "47607237",
        "despacho",
        nivel_acesso="2",
    )

    assert result["ok"] is True
    fields = {item["field_name"] for item in result["data"]["access_policy"]["available_hypotheses"]}
    assert fields == {"selGrauSigilo", "selHipoteseLegal"}


def test_document_create_confirm_contract() -> None:
    logged: list[dict[str, Any]] = []
    import sei_cli.operations.writing as writing_ops

    original_append = writing_ops.append_created_document_log
    client = FakeClient()
    writing_ops.append_created_document_log = logged.append
    try:
        result = document_create_confirm(
            client,
            "47607237",
            "despacho",
            descricao="Despacho autorizando continuidade",
            nivel_acesso="1",
            hipotese_acesso="4",
            hipotese_campo="selHipoteseLegal",
            confirm=True,
        )
    finally:
        writing_ops.append_created_document_log = original_append

    assert result["ok"] is True
    assert result["operation"] == "document-create-confirm"
    assert result["resolved_ids"]["id_documento"] == "59999999"
    assert result["data"]["created_document"]["editor_url"]
    assert client.last_created_document["nivel_acesso"] == "1"
    assert logged[0]["id_documento"] == "59999999"


def test_document_create_confirm_requires_confirmation() -> None:
    result = document_create_confirm(
        FakeClient(),
        "47607237",
        "despacho",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_document_create_confirm_fails_when_document_id_is_missing() -> None:
    result = document_create_confirm(
        EmptyCreateDocumentClient(),
        "47607237",
        "despacho",
        confirm=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"
    assert "não retornou id_documento" in result["error"]["message"]


def test_document_edit_preview_contract() -> None:
    result = document_edit_preview(FakeClient(), "59999999", process_id="47607237")

    assert result["ok"] is True
    assert result["operation"] == "document-edit-preview"
    assert result["data"]["editor"]["sections_total"] == 2
    assert result["data"]["editor"]["selected_section"]["section_id"] == "422"
    assert result["data"]["editor"]["editable_sections_count"] == 1
    assert result["data"]["editor"]["sections"][0]["editable"] is False
    assert result["data"]["editor"]["sections"][1]["editable"] is True


def test_document_edit_confirm_contract() -> None:
    client = FakeClient()
    result = document_edit_confirm(
        client,
        "59999999",
        process_id="47607237",
        section_id="422",
        content="<p>Despacho atualizado</p>",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "document-edit-confirm"
    assert result["resolved_ids"]["section_id"] == "422"
    assert client.last_edit["content"] == "<p>Despacho atualizado</p>"
    assert result["data"]["quality_check"]["line_count"] >= 1
    assert result["data"]["quality_check"]["editable_sections_count"] == 1
    assert result["data"]["quality_check"]["edited_sections"] == ["422"]


def test_document_quality_check_contract() -> None:
    result = document_quality_check(FakeClient(), "39860248", process_id="47607237")

    assert result["ok"] is True
    assert result["operation"] == "document-quality-check"
    assert "quality_check" in result["data"]
    assert result["data"]["quality_check"]["editable_sections_count"] == 1
    assert "document_profile" in result["data"]["quality_check"]
    assert "template_variables_remaining" in result["data"]["quality_check"]


def test_document_quality_check_dispatch_profile() -> None:
    result = document_quality_check(FakeClient(), "39999999", process_id="47607237")

    assert result["ok"] is True
    quality = result["data"]["quality_check"]
    assert quality["document_profile"]["kind"] == "despacho"
    assert quality["document_profile"]["dispatch_checks"]["applies"] is True
    assert quality["document_profile"]["dispatch_checks"]["has_action_verb"] is True
    assert quality["document_profile"]["dispatch_checks"]["has_destination_signal"] is True
    assert "sgt" in quality["suspicious_rank_terms"]


class BlankEditableSectionClient(FakeClient):
    def read_document(self, id_documento: str, id_procedimento: str) -> str:
        if (id_documento, id_procedimento) == ("59999999", "47607237"):
            return "Despacho\n@interessados_virgula_espaco@\n"
        return super().read_document(id_documento, id_procedimento)

    def get_editor_sections(self, id_documento: str, id_procedimento: str) -> tuple[str, list[EditorSection]]:
        save_url, sections = super().get_editor_sections(id_documento, id_procedimento)
        return (
            save_url,
            [
                EditorSection(name="txaEditor_101", content="<p>Cabecalho</p>", section_id="101", editable=False),
                EditorSection(name="txaEditor_220", content="<p>&nbsp;</p>", section_id="220", editable=True),
            ],
        )


class EscapedBlankEditableSectionClient(BlankEditableSectionClient):
    def get_editor_sections(self, id_documento: str, id_procedimento: str) -> tuple[str, list[EditorSection]]:
        save_url, _sections = super().get_editor_sections(id_documento, id_procedimento)
        return (
            save_url,
            [
                EditorSection(name="txaEditor_101", content="&lt;p&gt;Cabecalho&lt;/p&gt;", section_id="101", editable=False),
                EditorSection(name="txaEditor_220", content="&lt;p&gt;&nbsp;&lt;/p&gt;", section_id="220", editable=True),
            ],
        )


class TemplateVariableEditableSectionClient(BlankEditableSectionClient):
    def get_editor_sections(self, id_documento: str, id_procedimento: str) -> tuple[str, list[EditorSection]]:
        save_url, _sections = super().get_editor_sections(id_documento, id_procedimento)
        return (
            save_url,
            [
                EditorSection(name="txaEditor_101", content="<p>Cabecalho</p>", section_id="101", editable=False),
                EditorSection(name="txaEditor_220", content="<p>@interessados_virgula_espaco@</p><p>&nbsp;</p>", section_id="220", editable=True),
            ],
        )


class BoilerplateEditableSectionClient(BlankEditableSectionClient):
    def get_editor_sections(self, id_documento: str, id_procedimento: str) -> tuple[str, list[EditorSection]]:
        save_url, _sections = super().get_editor_sections(id_documento, id_procedimento)
        return (
            save_url,
            [
                EditorSection(name="txaEditor_101", content="<p>Cabecalho</p>", section_id="101", editable=False),
                EditorSection(
                    name="txaEditor_220",
                    content="<p>@interessados_virgula_espaco@</p><p>Natal/RN, data da assinatura eletrônica.</p><p>&nbsp;</p>",
                    section_id="220",
                    editable=True,
                ),
            ],
        )


def test_document_quality_check_ignores_standard_template_variables_and_detects_empty_editable_body() -> None:
    result = document_quality_check(BlankEditableSectionClient(), "59999999", process_id="47607237")

    assert result["ok"] is True
    quality = result["data"]["quality_check"]
    assert quality["empty_body_check"] is True
    assert quality["template_variables_remaining"] == []
    assert quality["standard_template_variables_remaining"] == ["@interessados_virgula_espaco@"]


def test_document_quality_check_detects_empty_body_with_escaped_editor_html() -> None:
    result = document_quality_check(EscapedBlankEditableSectionClient(), "59999999", process_id="47607237")

    assert result["ok"] is True
    assert result["data"]["quality_check"]["empty_body_check"] is True


def test_document_quality_check_detects_empty_body_with_only_template_variable_in_editable_section() -> None:
    result = document_quality_check(TemplateVariableEditableSectionClient(), "59999999", process_id="47607237")

    assert result["ok"] is True
    assert result["data"]["quality_check"]["empty_body_check"] is True


def test_document_quality_check_detects_empty_body_with_signature_boilerplate_only() -> None:
    result = document_quality_check(BoilerplateEditableSectionClient(), "59999999", process_id="47607237")

    assert result["ok"] is True
    assert result["data"]["quality_check"]["empty_body_check"] is True


def test_document_create_confirm_inherits_process_access_by_default() -> None:
    logged: list[dict[str, Any]] = []
    import sei_cli.operations.writing as writing_ops

    original_append = writing_ops.append_created_document_log
    client = FakeClient()
    writing_ops.append_created_document_log = logged.append
    try:
        result = document_create_confirm(
            client,
            "47607237",
            "despacho",
            descricao="Despacho herdando acesso",
            confirm=True,
        )
    finally:
        writing_ops.append_created_document_log = original_append

    assert result["ok"] is True
    assert result["data"]["access_policy"]["inherits_from_process"] is True
    assert result["data"]["access_policy"]["nivel_codigo"] == "1"
    assert result["data"]["access_policy"]["selected_hypothesis"]["value"] == "4"
    assert client.last_created_document["nivel_acesso"] == "1"
    assert client.last_created_document["extra_fields"]["selHipoteseLegal"] == "4"
    assert result["warnings"] == []
    assert logged[0]["access_policy"]["inherits_from_process"] is True


def test_document_edit_confirm_requires_confirmation() -> None:
    result = document_edit_confirm(
        FakeClient(),
        "59999999",
        process_id="47607237",
        content="<p>Teste</p>",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_process_report_contract() -> None:
    result = process_report(FakeClient(), "47607237")

    assert result["ok"] is True
    assert result["operation"] == "process-report"
    assert result["data"]["overview"]["documents_total"] == 8
    assert result["data"]["relatorios"]
    assert result["data"]["relatorios"][0]["signature_status"]["signed"] is False
    assert result["data"]["relatorios"][0]["signature_status"]["signature_pending"] is True
    assert result["data"]["relatorios"][0]["parsing_strategy"] in {"structured_editor", "text_fallback"}
    assert result["data"]["relatorios"][0]["relatorio"]["fiscal"] == "João Silva"
    assert "Relatório" in result["data"]["relatorios"][0]["summary"]


def test_signature_block_list_contract() -> None:
    result = signature_block_list(FakeClient())

    assert result["ok"] is True
    assert result["operation"] == "signature-block-list"
    assert result["data"]["blocks_total"] == 1
    assert result["data"]["pending_documents_total"] == 1


def test_signature_block_read_contract() -> None:
    result = signature_block_read(FakeClient(), "774681")

    assert result["ok"] is True
    assert result["operation"] == "signature-block-read"
    assert result["data"]["documents_total"] == 2
    assert result["data"]["pending_total"] == 1
    assert result["data"]["bloco"]["unidades_destino"] == ["CMDO"]
    assert result["data"]["documents"][0]["numero_sei"] == "39860248"


def test_signature_block_review_contract() -> None:
    result = signature_block_review(FakeClient(), "774681")

    assert result["ok"] is True
    assert result["operation"] == "signature-block-review"
    assert result["data"]["ready_to_sign"] is True
    assert result["data"]["signable_document_ids"] == ["48568466"]
    assert result["data"]["pending_documents"][0]["assinantes"] == ["Fulano"]


def test_signature_block_add_document_preview_contract() -> None:
    result = signature_block_add_document_preview(
        FakeClient(),
        "774681",
        "39860250",
    )

    assert result["ok"] is True
    assert result["operation"] == "signature-block-add-document-preview"
    assert result["resolved_ids"]["block_numero"] == "774681"
    assert result["resolved_ids"]["id_documento"] == "48568468"
    assert result["data"]["mutation_preview"]["disponibilizar"] is False
    assert result["data"]["mutation_preview"]["already_in_block"] is False
    assert result["data"]["bloco"]["numero"] == "774681"
    assert result["data"]["documento"]["id_documento"] == "48568468"
    assert any("Recebido" in warning for warning in result["warnings"])


class DisponibilizedBlockClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.blocks = [
            Block(
                numero="871299",
                estado="Disponibilizado",
                unidade_origem="PABM APODI",
                unidade_destino="PAD-PDF",
                descricao="Bloco em circulação",
            )
        ]
        self.block_documents_map = {
            "871299": [
                BlockDocument(
                    seq="1",
                    processo="08810254.000117/2026-62",
                    documento_id="48783191",
                    tipo_documento="Despacho",
                    assinante="LEO ZENON TASSI / 2º Tenente QOEM BM",
                    numero_sei="40381240",
                    numero_documento="40381240",
                    assinado=False,
                )
            ]
        }


class RefreshBlockClient(DisponibilizedBlockClient):
    def cancel_disponibilizacao_block(self, block_numero: str) -> dict[str, Any]:
        return self.cancelar_disponibilizacao_block(block_numero)


def test_signature_block_recall_preview_for_received_block() -> None:
    result = signature_block_recall_preview(FakeClient(), "774681")

    assert result["ok"] is True
    assert result["operation"] == "signature-block-recall-preview"
    assert result["data"]["mutation_preview"]["action"] == "devolver"
    assert any("Recebido" in warning for warning in result["warnings"])


def test_signature_block_recall_preview_for_disponibilized_block() -> None:
    result = signature_block_recall_preview(DisponibilizedBlockClient(), "871299")

    assert result["ok"] is True
    assert result["data"]["mutation_preview"]["action"] == "cancelar_disponibilizacao"
    assert result["warnings"] == []


def test_signature_block_recall_confirm_for_received_block() -> None:
    client = FakeClient()
    result = signature_block_recall_confirm(client, "774681", confirm=True)

    assert result["ok"] is True
    assert result["operation"] == "signature-block-recall-confirm"
    assert client.last_block_recall == {"block_numero": "774681", "action": "devolver"}
    assert result["data"]["mutation"]["action"] == "devolver"


def test_signature_block_recall_confirm_for_disponibilized_block() -> None:
    client = DisponibilizedBlockClient()
    result = signature_block_recall_confirm(client, "871299", confirm=True)

    assert result["ok"] is True
    assert client.last_block_recall == {"block_numero": "871299", "action": "cancelar_disponibilizacao"}
    assert result["data"]["verification"]["state_after"] == "Gerado"


def test_signature_block_recall_confirm_requires_confirmation() -> None:
    result = signature_block_recall_confirm(FakeClient(), "774681")

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_signature_block_refresh_preview_contract() -> None:
    result = signature_block_refresh_preview(
        DisponibilizedBlockClient(),
        "871299",
        add_document_ids=["39860250"],
        remove_document_ids=["40381240"],
    )

    assert result["ok"] is True
    assert result["operation"] == "signature-block-refresh-preview"
    assert result["data"]["mutation_preview"]["recall_required"] is True
    assert result["data"]["mutation_preview"]["documents_to_add"] == ["39860250"]
    assert result["data"]["mutation_preview"]["documents_to_remove"] == ["40381240"]


def test_signature_block_refresh_confirm_contract() -> None:
    client = RefreshBlockClient()
    result = signature_block_refresh_confirm(
        client,
        "871299",
        add_document_ids=["39860250"],
        remove_document_ids=["40381240"],
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "signature-block-refresh-confirm"
    assert result["data"]["mutation"]["recall"]["action"] == "cancelar_disponibilizacao"
    assert result["data"]["mutation"]["removed"]
    assert result["data"]["mutation"]["added"]
    assert result["data"]["mutation"]["redisponibilizacao"]["message"]


def test_signature_block_refresh_confirm_uses_created_document_log(monkeypatch) -> None:
    monkeypatch.setattr(
        "sei_cli.operations.writing.load_created_documents",
        lambda: [
            {
                "id_documento": "48784646",
                "id_procedimento": "48756457",
                "numero_documento": "48784646",
            }
        ],
    )
    client = RefreshBlockClient()
    result = signature_block_refresh_confirm(
        client,
        "871299",
        add_document_ids=["48784646"],
        confirm=True,
    )

    assert result["ok"] is True
    assert result["data"]["mutation"]["added"][0]["resolved_id_documento"] == "48784646"
    assert client.last_block_add is not None
    assert client.last_block_add["id_procedimento"] == "48756457"
    assert client.last_block_add["id_documento"] == "48784646"


def test_signature_block_refresh_confirm_requires_confirmation() -> None:
    result = signature_block_refresh_confirm(
        DisponibilizedBlockClient(),
        "871299",
        add_document_ids=["39860250"],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_signature_block_add_document_confirm_contract() -> None:
    client = FakeClient()
    result = signature_block_add_document_confirm(
        client,
        "774681",
        "39860250",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["operation"] == "signature-block-add-document-confirm"
    assert result["resolved_ids"]["id_documento"] == "48568468"
    assert client.last_block_add == {
        "id_procedimento": "47607237",
        "id_documento": "48568468",
        "block_numero": "774681",
        "disponibilizar": False,
    }


def test_signature_block_add_document_preview_detects_document_already_in_block_by_sei_number() -> None:
    result = signature_block_add_document_preview(
        FakeClient(),
        "774681",
        "39860248",
    )

    assert result["ok"] is True
    assert result["data"]["mutation_preview"]["already_in_block"] is True
    assert "Documento já consta neste bloco." in result["warnings"]


def test_signature_block_add_document_confirm_requires_confirmation() -> None:
    result = signature_block_add_document_confirm(
        FakeClient(),
        "774681",
        "39860250",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


class SilentBlockAddClient(FakeClient):
    def add_document_to_block(
        self,
        id_procedimento: str,
        id_documento: str,
        block_numero: str,
        *,
        disponibilizar: bool = False,
    ) -> dict[str, Any]:
        self.last_block_add = {
            "id_procedimento": id_procedimento,
            "id_documento": id_documento,
            "block_numero": block_numero,
            "disponibilizar": disponibilizar,
        }
        return {"ok": True, "message": "Documento incluído no bloco 774681"}


class SeiNumberBlockAddClient(FakeClient):
    def add_document_to_block(
        self,
        id_procedimento: str,
        id_documento: str,
        block_numero: str,
        *,
        disponibilizar: bool = False,
    ) -> dict[str, Any]:
        self.last_block_add = {
            "id_procedimento": id_procedimento,
            "id_documento": id_documento,
            "block_numero": block_numero,
            "disponibilizar": disponibilizar,
        }
        self.block_documents_map.setdefault(block_numero, []).append(
            BlockDocument(
                seq=str(len(self.block_documents_map.get(block_numero, [])) + 1),
                processo="08810058.000128/2026-69",
                documento_id="39860250",
                tipo_documento="Relatório do Fiscal",
                assinante="",
                numero_sei="39860250",
                numero_documento="39860250",
                assinado=False,
            )
        )
        return {"ok": True, "message": "Documento incluído no bloco 774681"}


def test_signature_block_add_document_confirm_detects_silent_failure() -> None:
    result = signature_block_add_document_confirm(
        SilentBlockAddClient(),
        "774681",
        "39860250",
        confirm=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_signature_block_add_document_confirm_accepts_verification_by_sei_number() -> None:
    client = SeiNumberBlockAddClient()
    result = signature_block_add_document_confirm(
        client,
        "774681",
        "39860250",
        confirm=True,
    )

    assert result["ok"] is True
    assert result["data"]["verification"]["included_in_block"] is True


def test_signature_block_add_document_confirm_fails_early_when_document_already_in_block() -> None:
    result = signature_block_add_document_confirm(
        FakeClient(),
        "774681",
        "39860248",
        confirm=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"
    assert "já consta no bloco" in result["error"]["message"]


def test_signature_block_sign_preview_contract() -> None:
    result = signature_block_sign_preview(FakeClient(), "774681")

    assert result["ok"] is True
    assert result["operation"] == "signature-block-sign-preview"
    assert result["data"]["pending_documents_total"] == 1
    assert result["data"]["selected_documents_total"] == 1
    assert result["data"]["signable_document_ids"] == ["48568466"]


def test_signature_block_sign_confirm_contract() -> None:
    client = FakeClient()
    result = signature_block_sign_confirm(client, "774681", confirm=True)

    assert result["ok"] is True
    assert result["operation"] == "signature-block-sign-confirm"
    assert result["resolved_ids"]["document_ids"] == ["48568466"]
    assert client.signed_documents == [{"id_documento": "48568466", "id_procedimento": "47607237"}]
    assert result["data"]["verification"]["remaining_pending_total"] == 0


def test_signature_block_sign_confirm_requires_confirmation() -> None:
    result = signature_block_sign_confirm(FakeClient(), "774681")

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


class SilentBlockSignClient(FakeClient):
    def sign_document(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
        self.signed_documents.append(
            {"id_documento": id_documento, "id_procedimento": id_procedimento}
        )
        return {"doc_ids": [id_documento], "signed": [id_documento], "already_signed": [], "errors": []}


class ExplicitSignErrorClient(FakeClient):
    def sign_document(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
        return {
            "doc_ids": [id_documento],
            "signed": [],
            "already_signed": [],
            "errors": ["SEI retornou ao formulário de assinatura sem confirmar a operação."],
        }


class SeiNumberBlockSignClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.block_documents_map["774681"] = [
            BlockDocument(
                seq="1",
                processo="08810058.000128/2026-69",
                documento_id="39860251",
                tipo_documento="Relatório do Fiscal",
                assinante="Fulano",
                numero_sei="39860251",
                numero_documento="39860251",
                assinado=False,
            )
        ]

    def search_document(self, protocolo: str) -> tuple[str, str] | None:
        if protocolo == "39860251":
            return ("48568469", "47607237")
        return super().search_document(protocolo)

    def sign_document(self, id_documento: str, id_procedimento: str) -> dict[str, Any]:
        self.signed_documents.append(
            {"id_documento": id_documento, "id_procedimento": id_procedimento}
        )
        for docs in self.block_documents_map.values():
            for doc in docs:
                if doc.documento_id in {id_documento, "39860251"}:
                    doc.assinado = True
        return {"doc_ids": [id_documento], "signed": [id_documento], "already_signed": [], "errors": []}


def test_signature_block_sign_confirm_detects_silent_failure() -> None:
    result = signature_block_sign_confirm(SilentBlockSignClient(), "774681", confirm=True)

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"


def test_signature_block_sign_confirm_propagates_sign_document_error() -> None:
    result = signature_block_sign_confirm(ExplicitSignErrorClient(), "774681", confirm=True)

    assert result["ok"] is False
    assert result["error"]["code"] == "workflow_violation"
    assert "formulário de assinatura" in result["error"]["message"]


def test_signature_block_sign_confirm_resolves_block_document_by_sei_number() -> None:
    client = SeiNumberBlockSignClient()
    result = signature_block_sign_confirm(client, "774681", confirm=True)

    assert result["ok"] is True
    assert result["resolved_ids"]["document_ids"] == ["48568469"]
    assert client.signed_documents == [{"id_documento": "48568469", "id_procedimento": "47607237"}]


def test_relatorio_read_contract() -> None:
    result = relatorio_read(FakeClient(), "39860250")

    assert result["ok"] is True
    assert result["operation"] == "relatorio-read"
    assert result["data"]["documento"]["nome"] == "Relatório do Fiscal 21/04/2026"
    assert result["data"]["signature_status"]["signed"] is False
    assert result["data"]["signature_status"]["signature_pending"] is True
    assert result["data"]["relatorio"]["fiscal"] == "João Silva"
    assert "Fiscal" in result["data"]["summary"]


def test_relatorio_read_pdf_fallback_contract() -> None:
    result = relatorio_read(FakeClient(), "39860243")

    assert result["ok"] is True
    assert result["operation"] == "relatorio-read"
    assert result["data"]["documento"]["tipo"] == "pdf"
    assert result["data"]["parsing_strategy"] == "text_fallback"
    assert result["data"]["extraction_method"] in {
        "read_document_content",
        "read_document_content_retry",
        "download_document_pdf",
        "download_document_pdf_retry",
    }
    assert result["data"]["relatorio"]["fiscal"] == "João Silva"
    assert result["data"]["signature_status"]["signed"] is False


def test_block_review_contract() -> None:
    result = block_review(FakeClient(), "774681")

    assert result["ok"] is True
    assert result["operation"] == "block-review"
    assert result["data"]["documents_total"] == 2
    assert result["data"]["pending_total"] == 1
    assert result["data"]["processos_total"] == 2
    assert result["next_actions"][0]["action"] == "process-open"


def test_block_review_not_found() -> None:
    result = block_review(FakeClient(), "999999")

    assert result["ok"] is False
    assert result["error"]["code"] == "block_not_found"


def test_inbox_snapshot_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["inbox-snapshot", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "inbox-snapshot"


def test_process_open_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-open", "08810058.000128/2026-69", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resolved_ids"]["id_procedimento"] == "47607237"


def test_document_read_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["document-read", "39860248", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["semantic_context"]["document_kind_guess"] == "reaprazamento"
    assert payload["data"]["action_context"]["can_forward_process"] is True
    assert payload["data"]["char_count"] == len(
        "3º SGT BM João Silva solicita reaprazamento de férias de 10/04/2026 para 20/04/2026.\n"
        "Encaminhar ao CMDO PABM APODI para despacho e posterior envio ao DPSGP.\n"
        "Justificativa: necessidade de adequação da escala operacional.\n"
        "Fulano - 2º Tenente QOEM BM\n"
    )


def test_document_read_cli_json_error_exit_code(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["document-read", "00000000", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "document_not_found"


def test_process_read_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-read", "47607237", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["selection"]["documents_selected_total"] == 6
    assert payload["data"]["process_context"]["process_kind_guess"] == "reaprazamento"
    assert payload["data"]["relatorios_total"] == 2


def test_process_summary_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-summary", "47607237", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-summary"
    assert payload["data"]["process_kind_guess"] == "reaprazamento"


def test_process_report_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-report", "47607237", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-report"
    assert payload["data"]["relatorios"][0]["signature_status"]["signed"] is False
    assert payload["data"]["relatorios"][0]["relatorio"]["fiscal"] == "João Silva"


def test_process_create_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-create-preview",
            "ferias",
            "--especificacao",
            "Reaprazamento de férias do 3º SGT BM João Silva",
            "--nivel",
            "privado",
            "--hipotese-acesso",
            "LGPD",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resolved_ids"]["tipo_processo_id"] == "100000182"
    assert payload["data"]["access_policy"]["nivel_codigo"] == "1"
    assert payload["data"]["access_policy"]["selected_hypothesis"]["value"] == "LGPD"


def test_process_create_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-create-confirm",
            "informacao",
            "--especificacao",
            "Livro do fiscal do dia 30/03/2026",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resolved_ids"]["id_procedimento"] == "49999999"


def test_process_create_confirm_cli_json_non_public_requires_hypothesis(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-create-confirm",
            "ferias",
            "--especificacao",
            "Reaprazamento de férias do 3º SGT BM João Silva",
            "--nivel",
            "restrito",
            "--hipotese-acesso",
            "ADM",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["access_policy"]["selected_hypothesis"]["value"] == "ADM"


def test_process_create_preview_cli_json_sigiloso(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-create-preview",
            "ferias",
            "--especificacao",
            "Teste sigiloso",
            "--nivel",
            "2",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    fields = {item["field_name"] for item in payload["data"]["access_policy"]["available_hypotheses"]}
    assert fields == {"selGrauSigilo", "selHipoteseLegal"}


def test_process_create_confirm_cli_json_sigiloso(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-create-confirm",
            "ferias",
            "--especificacao",
            "Teste sigiloso",
            "--nivel",
            "2",
            "--hipotese-acesso",
            "selGrauSigilo=R,selHipoteseLegal=23",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    selected = payload["data"]["access_policy"]["selected_hypothesis"]
    assert isinstance(selected, list)


def test_document_create_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "document-create-preview",
            "47607237",
            "despacho",
            "--descricao",
            "Despacho autorizando continuidade",
            "--nivel",
            "1",
            "--hipotese-acesso",
            "4",
            "--hipotese-campo",
            "selHipoteseLegal",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resolved_ids"]["tipo_documento_id"] == "5"


def test_document_create_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "document-create-confirm",
            "47607237",
            "despacho",
            "--descricao",
            "Despacho autorizando continuidade",
            "--nivel",
            "1",
            "--hipotese-acesso",
            "4",
            "--hipotese-campo",
            "selHipoteseLegal",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resolved_ids"]["id_documento"] == "59999999"


def test_document_edit_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["document-edit-preview", "59999999", "--process-id", "47607237", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["editor"]["sections_total"] == 2


def test_document_edit_confirm_cli_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    content_path = tmp_path / "doc.html"
    content_path.write_text("<p>Despacho atualizado</p>", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "document-edit-confirm",
            "59999999",
            "--process-id",
            "47607237",
            "--section-id",
            "422",
            "--content-file",
            str(content_path),
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["resolved_ids"]["section_id"] == "422"


def test_document_quality_check_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["document-quality-check", "39860248", "--process-id", "47607237", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert "quality_check" in payload["data"]
    assert "document_profile" in payload["data"]["quality_check"]


def test_process_pdf_confirm_cli_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    output = tmp_path / "processo-cli.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-pdf-confirm", "47607237", "--output", str(output), "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-pdf-confirm"
    assert payload["data"]["download"]["path"] == str(output)


def test_document_pdf_confirm_cli_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    output = tmp_path / "documento-cli.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "document-pdf-confirm",
            "39860248",
            "--process-id",
            "47607237",
            "--output",
            str(output),
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "document-pdf-confirm"
    assert payload["resolved_ids"]["id_documento"] == "48568466"


def test_environment_triage_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["environment-triage-preview", "--only-unmarked", "--mode", "fast", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "environment-triage-preview"
    assert payload["data"]["filters"]["mode"] == "fast"


def test_environment_triage_apply_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["environment-triage-apply", "--only-unmarked", "--mode", "contextual", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "environment-triage-apply"


def test_process_finalize_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-finalize-preview", "47607237", "39860248", "39860241", "39860243", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-finalize-preview"


def test_process_finalize_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-finalize-confirm", "47607237", "39860248", "39860241", "39860243", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-finalize-confirm"


def test_process_forward_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-forward-preview",
            "47607237",
            "PAD-PDF",
            "--fechar",
            "--retorno-dias",
            "7",
            "--retorno-dias-uteis",
            "--reabrir-em",
            "05/04/2026",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-forward-preview"
    assert payload["data"]["forward_policy"]["retorno_dias"] == "7"


def test_process_forward_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-forward-confirm",
            "47607237",
            "PAD-PDF",
            "--retorno-em",
            "10/04/2026",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-forward-confirm"
    assert payload["data"]["forward_policy"]["retorno_em"] == "10/04/2026"


def test_process_conclude_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-conclude-preview", "47607237", "--reabrir-dias", "5", "--reabrir-dias-uteis", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-conclude-preview"
    assert payload["data"]["conclude_policy"]["reabrir_dias"] == "5"


def test_process_conclude_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-conclude-confirm", "47607237", "--reabrir-em", "05/04/2026", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-conclude-confirm"


def test_process_reopen_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-reopen-preview", "47607237", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-reopen-preview"


def test_process_reopen_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-reopen-confirm", "47607237", "--confirm", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-reopen-confirm"


def test_relatorio_read_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["relatorio-read", "39860250", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["relatorio"]["fiscal"] == "João Silva"


def test_marker_catalog_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["marker-catalog", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "marker-catalog"


def test_process_marker_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-marker-preview", "47607237", "--marker", "12", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-marker-preview"


def test_process_marker_read_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["process-marker-read", "47607237", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-marker-read"
    assert payload["data"]["current_markers_total"] == 1


def test_process_marker_history_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-marker-history", "47607237", "--marker", "11", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-marker-history"
    assert payload["data"]["history_total"] == 1
    assert payload["data"]["history_summary"]["latest_entry"]["acao"] == "Aplicado"


def test_process_marker_set_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-marker-set-confirm",
            "47607237",
            "--marker",
            "12",
            "--texto",
            "Processo apenas informativo.",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-marker-set-confirm"


def test_process_marker_remove_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-marker-remove-confirm", "47607237", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-marker-remove-confirm"


def test_process_marker_remove_confirm_cli_json_with_marker(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process-marker-remove-confirm", "47607237", "--marker", "11", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["selected_marker"]["marcador_id"] == "11"


def test_process_marker_update_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process-marker-update-confirm",
            "47607237",
            "--marker",
            "11",
            "--texto",
            "Aguardando manifestação até 15/04.",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "process-marker-update-confirm"
    assert payload["data"]["mutation"]["new_text"] == "Aguardando manifestação até 15/04."


def test_signature_block_list_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["signature-block-list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-list"


def test_signature_block_read_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["signature-block-read", "774681", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-read"


def test_signature_block_review_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["signature-block-review", "774681", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-review"


def test_signature_block_add_document_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["signature-block-add-document-preview", "774681", "39860250", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-add-document-preview"
    assert payload["resolved_ids"]["id_documento"] == "48568468"


def test_signature_block_add_document_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "signature-block-add-document-confirm",
            "774681",
            "39860250",
            "--confirm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-add-document-confirm"
    assert payload["resolved_ids"]["id_documento"] == "48568468"


def test_signature_block_recall_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["signature-block-recall-preview", "774681", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-recall-preview"


def test_signature_block_recall_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["signature-block-recall-confirm", "774681", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-recall-confirm"


def test_signature_block_sign_preview_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["signature-block-sign-preview", "774681", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-sign-preview"
    assert payload["data"]["signable_document_ids"] == ["48568466"]


def test_signature_block_sign_confirm_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["signature-block-sign-confirm", "774681", "--confirm", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["operation"] == "signature-block-sign-confirm"
    assert payload["data"]["verification"]["remaining_pending_total"] == 0


def test_switch_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["switch", "OP 3", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert payload["unidade_sigla"] == "OP 3"


def test_switch_cli_json_normalizes_legacy_bool(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClientLegacySwitch)

    runner = CliRunner()
    result = runner.invoke(cli, ["switch", "OP 3", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert payload["unidade_sigla"] == "OP 3"


class FirstRelatorioCandidateFailsClient(FakeClient):
    def download_document(self, doc: TreeDocument, output_path: str | None = None) -> bytes | str:
        if doc.id_documento == "48568463":
            raise RuntimeError("Falha proposital no primeiro relatório candidato")
        return super().download_document(doc, output_path)


class HtmlViewFallbackRelatorioClient(FakeClient):
    def read_relatorio(self, id_documento: str, id_procedimento: str) -> RelatorioServico:
        raise RuntimeError("Editor indisponível")

    def view_document_html(self, id_documento: str, id_procedimento: str) -> str:
        if (id_documento, id_procedimento) != ("48568468", "47607237"):
            raise RuntimeError("HTML do relatório não encontrado")
        return Path("tests/fixtures/relatorio_body.html").read_text()


def test_process_report_tries_next_relatorio_candidate_when_first_fails() -> None:
    result = process_report(FirstRelatorioCandidateFailsClient(), "47607237", relatorio_limit=1)

    assert result["ok"] is True
    assert len(result["data"]["relatorios"]) == 1
    assert result["data"]["relatorios"][0]["documento"]["id_documento"] == "48568468"
    assert result["data"]["relatorios"][0]["parsing_strategy"] == "structured_editor"
    assert result["data"]["relatorio_failures"]


def test_relatorio_read_uses_html_view_before_text_fallback() -> None:
    result = relatorio_read(HtmlViewFallbackRelatorioClient(), "39860250")

    assert result["ok"] is True
    assert result["data"]["parsing_strategy"] == "structured_html_view"
    assert result["data"]["extraction_method"] == "view_document_html"
    assert result["data"]["relatorio"]["fiscal"] == "Vilson"
    assert result["data"]["relatorio"]["posto_fiscal"] == "2° SGT BM"
    assert len(result["data"]["relatorio"]["militares"]) == 8
    assert len(result["data"]["relatorio"]["viaturas"]) >= 4


def test_block_review_cli_json(monkeypatch) -> None:
    monkeypatch.setattr("sei_cli.cli.SEIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(cli, ["block-review", "774681", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["documents_total"] == 2
