from __future__ import annotations

from collections import Counter
import contextlib
from datetime import date, datetime
import io
import importlib
import re
from typing import Any
import unicodedata

from sei_cli.models import Block, BlockDocument, Process, TreeDocument
from sei_cli.relatorio_parser import (
    RelatorioServico,
    parse_relatorio,
    summarize as summarize_relatorio,
    to_dict as relatorio_to_dict,
)

from .contracts import NextAction, OperationResult
from .errors import (
    BlockNotFoundError,
    DocumentNotFoundError,
    ParseError,
    ProcessNotFoundError,
    error_from_exception,
)


def _context(client: Any) -> dict[str, Any]:
    status = client.status()
    return {
        "unidade_sigla": status.unidade_sigla,
        "unidade_descricao": status.unidade_descricao,
        "usuario": status.usuario,
        "valid": status.valid,
        "ultimo_acesso": status.ultimo_acesso,
    }


def _result(
    *,
    operation: str,
    context: dict[str, Any],
    resolved_ids: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    next_actions: list[NextAction] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return OperationResult(
        operation=operation,
        context=context,
        resolved_ids=resolved_ids or {},
        data=data or {},
        next_actions=next_actions or [],
        warnings=warnings or [],
    ).to_dict()


def _error_result(
    *,
    operation: str,
    context: dict[str, Any] | None = None,
    resolved_ids: dict[str, Any] | None = None,
    exc: Exception,
) -> dict[str, Any]:
    return OperationResult(
        ok=False,
        operation=operation,
        context=context or {},
        resolved_ids=resolved_ids or {},
        error=error_from_exception(exc),
    ).to_dict()


def _process_preview(process: Process) -> dict[str, Any]:
    return {
        "numero": process.numero,
        "tipo": process.tipo,
        "especificacao": process.especificacao,
        "id_procedimento": process.id_procedimento,
        "novo": process.novo,
        "recente": process.recente,
        "atribuido": process.atribuido,
        "marcador": process.marcador,
        "caixa": process.caixa,
    }


def _block_preview(block: Block) -> dict[str, Any]:
    return {
        "numero": block.numero,
        "estado": block.estado,
        "descricao": block.descricao,
        "unidade_origem": block.unidade_origem,
        "unidade_destino": block.unidade_destino,
        "unidades_destino": block.unidades_destino,
    }


def _tree_document(doc: TreeDocument) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id_documento": doc.id_documento,
        "nome": doc.nome,
        "tipo": doc.tipo,
        "parent_folder": doc.parent_folder,
        "sei_number": doc.sei_number,
        "assinado": doc.assinado,
        "autenticado": doc.autenticado,
    }
    if doc.assinaturas:
        d["assinaturas"] = [
            {"signer": s.signer, "role": s.role, "unit": s.unit, "kind": s.kind}
            for s in doc.assinaturas
        ]
    return d


def _block_document(doc: BlockDocument) -> dict[str, Any]:
    return {
        "seq": doc.seq,
        "processo": doc.processo,
        "documento_id": doc.documento_id,
        "numero_sei": doc.numero_sei or doc.numero_documento or doc.documento_id,
        "numero_documento": doc.numero_documento,
        "data_documento": doc.data_documento,
        "tipo_documento": doc.tipo_documento,
        "assinante": doc.assinante,
        "assinantes": doc.assinantes,
        "assinado": doc.assinado,
    }


def _relatorio_candidate(doc: TreeDocument) -> bool:
    haystack = f"{doc.nome} {doc.sei_number or ''}".upper()
    return any(token in haystack for token in ("RELAT", "LIVRO", "FISCAL"))


def _resolve_process_id(client: Any, numero_ou_id: str) -> tuple[str, str | None]:
    if "." not in numero_ou_id and "/" not in numero_ou_id:
        return numero_ou_id, None

    html = client.search(numero_ou_id)
    match = re.search(r"id_procedimento=(\d+)", html)
    if not match or "ifrArvore" not in html:
        raise ProcessNotFoundError(
            f"Processo {numero_ou_id} nao encontrado na unidade atual.",
            details={"numero_processo": numero_ou_id},
        )
    return match.group(1), numero_ou_id


def _resolve_document_ids(
    client: Any,
    numero_ou_id: str,
    *,
    id_procedimento: str | None = None,
) -> tuple[str, str, str | None]:
    if id_procedimento:
        return numero_ou_id, id_procedimento, None

    result = client.search_document(numero_ou_id)
    if not result:
        raise DocumentNotFoundError(
            f"Documento {numero_ou_id} nao encontrado na unidade atual.",
            details={"numero_documento": numero_ou_id},
        )
    id_documento, resolved_process_id = result
    return id_documento, resolved_process_id, numero_ou_id


def _resolve_document_id_with_process(
    client: Any,
    numero_ou_id: str,
    *,
    id_procedimento: str,
    docs: list[TreeDocument] | None = None,
) -> tuple[str, list[TreeDocument]]:
    docs = docs if docs is not None else client.get_full_document_tree(id_procedimento)
    if any(doc.id_documento == numero_ou_id for doc in docs):
        return numero_ou_id, docs

    matched = next((doc for doc in docs if doc.sei_number == numero_ou_id), None)
    if matched:
        return matched.id_documento, docs

    raise DocumentNotFoundError(
        f"Documento {numero_ou_id} nao encontrado no processo informado.",
        details={"numero_documento": numero_ou_id, "id_procedimento": id_procedimento},
    )


def _refresh_tree_document(
    client: Any,
    doc: TreeDocument | None,
    *,
    id_documento: str,
    id_procedimento: str,
) -> tuple[TreeDocument | None, str]:
    if doc and doc.sei_number:
        resolved = client.search_document(doc.sei_number)
        if resolved:
            refreshed_id_documento, refreshed_process_id = resolved
            refreshed_docs = client.get_full_document_tree(refreshed_process_id)
            refreshed_doc = next((item for item in refreshed_docs if item.id_documento == refreshed_id_documento), None)
            if refreshed_doc:
                return refreshed_doc, refreshed_process_id

    refreshed_docs = client.get_full_document_tree(id_procedimento)
    refreshed_doc = next((item for item in refreshed_docs if item.id_documento == id_documento), None)
    return refreshed_doc, id_procedimento


def _find_process_metadata(client: Any, id_procedimento: str, numero_processo: str | None) -> Process | None:
    processes = client.list_processes()
    for process in processes.recebidos + processes.gerados:
        if process.id_procedimento == id_procedimento:
            return process
        if numero_processo and process.numero == numero_processo:
            return process
    return None


def _process_unit_preflight(client: Any, id_procedimento: str) -> tuple[dict[str, Any], contextlib.AbstractContextManager[Any]]:
    status_before = client.status()
    navigate = getattr(client, "_navigate_to_arvore", None)
    auto_switch = getattr(client, "_auto_unit_switch", None)

    if not callable(navigate) or not callable(auto_switch):
        return (
            {
                "required": False,
                "current_unit": status_before.unidade_sigla,
                "target_unit": None,
                "switched": False,
                "restores_original_unit": False,
                "reason": "client_has_no_auto_unit_switch",
            },
            contextlib.nullcontext(None),
        )

    arvore_html = navigate(id_procedimento)
    if not arvore_html:
        return (
            {
                "required": False,
                "current_unit": status_before.unidade_sigla,
                "target_unit": None,
                "switched": False,
                "restores_original_unit": False,
                "reason": "arvore_not_available",
            },
            contextlib.nullcontext(None),
        )

    detect = getattr(client, "_detect_unit_restriction", None)
    find_accessible = getattr(client, "_find_accessible_unit", None)
    is_inaccessible = getattr(client, "_is_process_inaccessible", None)

    target_unit = None
    if callable(detect):
        target_unit = detect(arvore_html)
    if not target_unit and callable(is_inaccessible) and is_inaccessible(arvore_html) and callable(find_accessible):
        target_unit = find_accessible(arvore_html)

    return (
        {
            "required": bool(target_unit),
            "current_unit": status_before.unidade_sigla,
            "target_unit": target_unit,
            "switched": False,
            "restores_original_unit": bool(target_unit),
            "reason": "process_unit_preflight",
        },
        auto_switch(arvore_html, target_unit=target_unit),
    )


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _safe_get_actions(client: Any, id_procedimento: str, id_documento: str | None = None) -> dict[str, str]:
    getter = getattr(client, "get_actions", None)
    if not callable(getter):
        return {}
    try:
        actions = getter(id_procedimento, id_documento)
    except Exception:
        return {}
    return actions or {}


def _has_action(actions: dict[str, str], *, key: str | None = None, token: str | None = None) -> bool:
    if key and key in actions:
        return True
    if token and any(token in url for url in actions.values()):
        return True
    return False


def _action_context(process_actions: dict[str, str], document_actions: dict[str, str]) -> dict[str, Any]:
    can_act_on_process = bool(process_actions)
    can_act_on_document = bool(document_actions)
    return {
        "available_process_actions": sorted(process_actions.keys()),
        "available_document_actions": sorted(document_actions.keys()),
        "can_act_on_process": can_act_on_process,
        "can_act_on_document": can_act_on_document,
        "can_create_document": _has_action(process_actions, token="documento_escolher_tipo"),
        "can_change_process_metadata": _has_action(process_actions, token="procedimento_alterar"),
        "can_forward_process": _has_action(process_actions, token="procedimento_enviar"),
        "can_manage_marker": _has_action(process_actions, token="andamento_marcador_gerenciar"),
        "can_conclude_process": _has_action(process_actions, token="procedimento_concluir"),
        "can_edit_document": _has_action(document_actions, key="linkEditarConteudo", token="editor_montar"),
        "can_sign_document": _has_action(document_actions, key="linkAssinarDocumento", token="documento_assinar"),
        "can_delete_document": _has_action(document_actions, key="linkExcluirDocumento", token="documento_excluir"),
    }


def _ui_context(
    *,
    context: dict[str, Any],
    process: Process | None,
    docs: list[TreeDocument],
    doc_meta: TreeDocument | None,
    text: str,
    action_context: dict[str, Any],
    navigation_mode: str,
) -> dict[str, Any]:
    can_interact = action_context["can_act_on_process"] or action_context["can_act_on_document"]
    return {
        "navigation_mode": navigation_mode,
        "current_unit": context.get("unidade_sigla"),
        "current_user": context.get("usuario"),
        "process_visible_in_current_unit": bool(docs),
        "process_open_in_current_unit": bool(action_context["can_act_on_process"]),
        "document_selected_in_tree": doc_meta is not None,
        "can_interact_from_current_unit": can_interact,
        "can_only_read_from_current_unit": bool(text) and not can_interact,
        "process_box_category": process.caixa if process else None,
        "process_marker": process.marcador if process else None,
        "process_is_new": process.novo if process else None,
        "process_has_recent_change": process.recente if process else None,
    }


_DATE_PATTERN = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
_MILITARY_PATTERN = re.compile(
    r"\b(?P<rank>(?i:SD\s+BM|CB\s+BM|ST\s+BM|CAP(?:\s+BM)?|MAJ(?:\s+BM)?|TC(?:\s+BM)?|CEL(?:\s+BM)?|"
    r"[123][°º]?\s*SGT(?:\s+QP?BM|\s+BM)?|[12][°º]?\s*TEN(?:\s+QOEM)?(?:\s+BM)?))\s+"
    r"(?P<name>[A-ZÁ-Ú][A-Za-zÁ-Úá-ú']+(?:\s+[A-ZÁ-Ú][A-Za-zÁ-Úá-ú']+){0,5})",
)
_UNIT_PATTERN = re.compile(
    r"\b(?:CMDO|PABM|DPSGP|CRH|GBM|CAT|SAT|AJUD(?:ÂNCIA|ANCIA)\s+GERAL|SECRETARIA)\b[ A-Z0-9ºª/\-]*",
    re.IGNORECASE,
)


def _guess_document_kind(document: dict[str, Any], text: str) -> str:
    document_name = (document.get("nome") or "").upper()
    haystack = f"{document_name}\n{text}".upper()
    if "DESPACHO" in document_name:
        return "despacho"
    if any(token in haystack for token in ("RELAT", "LIVRO DO FISCAL", "RELATÓRIO DO FISCAL", "RELATORIO DO FISCAL")):
        return "relatorio_operacional"
    if "REAPRAZ" in haystack or ("FÉRIAS" in haystack or "FERIAS" in haystack):
        return "reaprazamento"
    if any(token in haystack for token in ("MATERIAL", "ALMOX", "SUPRIMENTO", "PATRIMÔNIO", "PATRIMONIO")):
        return "material"
    if any(token in haystack for token in ("DIÁRIA", "DIARIA", "PASSAGEM")):
        return "diarias"
    if "DESPACHO" in haystack:
        return "despacho"
    if any(token in haystack for token in ("INFORMAÇÃO", "INFORMACAO", "OFÍCIO", "OFICIO")):
        return "informacao"
    return "generic"


def _extract_military_people(text: str) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in _MILITARY_PATTERN.finditer(text):
        rank = " ".join(match.group("rank").split())
        name = " ".join(match.group("name").split())
        key = (rank.casefold(), name.casefold())
        if key in seen:
            continue
        seen.add(key)
        people.append(
            {
                "name": name,
                "display_name": f"{rank} {name}",
                "rank": rank,
                "role": None,
                "is_military": True,
            }
        )
    return people


def _extract_units(text: str) -> list[str]:
    matches = [match.group(0).strip(" .,:;") for match in _UNIT_PATTERN.finditer(text)]
    return _unique_strings(matches)


def _extract_dates(text: str) -> list[str]:
    return _unique_strings([match.group(0) for match in _DATE_PATTERN.finditer(text)])


def _extract_deadline(text: str) -> str | None:
    for line in text.splitlines():
        lower = line.lower()
        if any(token in lower for token in ("prazo", "até", "ate", "resposta", "manifestação", "manifestacao")):
            match = _DATE_PATTERN.search(line)
            if match:
                return match.group(0)
    return None


def _extract_material_items(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"\b(?P<quantity>\d+)\s+(?P<unit>unidades?|itens?|caixas?|metros?|litros?|rolos?|pares?)\s+de\s+(?P<item>[A-Za-zÀ-ú0-9 /-]+?)(?:[.,;]|$)",
        re.IGNORECASE,
    )
    items: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        items.append(
            {
                "quantity": int(match.group("quantity")),
                "unit": match.group("unit"),
                "item": match.group("item").strip(),
            }
        )
    return items


def _extract_reaprazamento_fields(text: str, involved_military: list[dict[str, Any]], dates: list[str]) -> dict[str, Any]:
    compact = " ".join(text.split())
    old_date = None
    new_date = None
    match = re.search(
        r"(?:de|do período|do periodo)\s+(\d{2}/\d{2}/\d{4}).{0,40}?(?:para|até|ate)\s+(\d{2}/\d{2}/\d{4})",
        compact,
        re.IGNORECASE,
    )
    if match:
        old_date, new_date = match.group(1), match.group(2)
    elif len(dates) >= 2:
        old_date, new_date = dates[0], dates[1]

    justification = None
    for line in text.splitlines():
        lower = line.lower()
        if any(token in lower for token in ("justific", "motivo", "razão", "razao")):
            justification = line.strip()
            break

    requester = involved_military[0]["display_name"] if involved_military else None
    return {
        "military_requester": requester,
        "original_date": old_date,
        "requested_date": new_date,
        "justification": justification,
        "requires_authorization": True,
    }


def _build_domain_context(kind: str, text: str, involved_military: list[dict[str, Any]], dates: list[str]) -> dict[str, Any]:
    if kind == "reaprazamento":
        return {
            "kind": kind,
            "fields": _extract_reaprazamento_fields(text, involved_military, dates),
        }
    if kind == "material":
        items = _extract_material_items(text)
        return {
            "kind": kind,
            "fields": {
                "material_items": items,
                "materials_total": len(items),
            },
        }
    if kind == "relatorio_operacional":
        return {
            "kind": kind,
            "fields": {
                "recommended_operation": "relatorio-read",
            },
        }
    return {"kind": kind, "fields": {}}


def _build_summary(kind: str, subject: str, domain_context: dict[str, Any], text: str) -> str:
    if kind == "reaprazamento":
        fields = domain_context["fields"]
        requester = fields.get("military_requester") or "militar não identificado"
        old_date = fields.get("original_date") or "data original não identificada"
        new_date = fields.get("requested_date") or "data pretendida não identificada"
        return f"Solicitação de reaprazamento de férias envolvendo {requester}, com mudança de {old_date} para {new_date}."
    if kind == "material":
        total = domain_context["fields"].get("materials_total", 0)
        return f"Documento relacionado a material, com {total} item(ns) identificado(s)." if total else subject
    first_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if first_lines:
        return " ".join(first_lines[:2])[:240]
    return subject


def _semantic_context(document: dict[str, Any], text: str) -> dict[str, Any]:
    involved_military = _extract_military_people(text)
    involved_units = _extract_units(text)
    mentioned_dates = _extract_dates(text)
    deadline = _extract_deadline(text)
    kind = _guess_document_kind(document, text)
    domain_context = _build_domain_context(kind, text, involved_military, mentioned_dates)

    lower = text.lower()
    requires_response = any(
        token in lower
        for token in (
            "solicita",
            "requer",
            "manifestação",
            "manifestacao",
            "providência",
            "providencia",
            "resposta",
            "despacho",
            "autoriz",
        )
    )
    information_only = (
        any(token in lower for token in ("para conhecimento", "para ciência", "para ciencia", "somente para conhecimento"))
        and not requires_response
    )
    action_required = requires_response and not information_only

    if "despacho" in lower or "autoriz" in lower:
        action_kind = "despacho"
    elif "encaminh" in lower:
        action_kind = "encaminhamento"
    elif information_only:
        action_kind = "ciencia"
    elif action_required:
        action_kind = "resposta"
    else:
        action_kind = None

    subject = document.get("nome") or "Documento sem título identificado"
    summary = _build_summary(kind, subject, domain_context, text)
    contextual_notes: list[str] = []
    if deadline:
        contextual_notes.append("O documento menciona prazo ou data-limite.")
    if involved_units:
        contextual_notes.append("Há unidades ou setores mencionados no texto.")
    if action_required:
        contextual_notes.append("O documento sugere necessidade de providência ou manifestação.")
    if kind == "relatorio_operacional":
        contextual_notes.append("Há uma canônica específica para leitura estruturada de relatório: relatorio-read.")

    return {
        "subject": subject,
        "summary": summary,
        "document_kind_guess": kind,
        "involved_people": involved_military,
        "involved_military": involved_military,
        "involved_units": involved_units,
        "mentioned_dates": mentioned_dates,
        "deadline": deadline,
        "requires_response": requires_response,
        "action_required": action_required,
        "action_kind": action_kind,
        "information_only": information_only,
        "contextual_notes": contextual_notes,
    }, domain_context


def _parse_br_date(value: str | None, *, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ParseError(
            f"{field_name} deve estar no formato DD/MM/AAAA.",
            details={"field": field_name, "value": value},
        ) from exc


def _document_title_dates(doc: TreeDocument) -> list[str]:
    haystack = " ".join(part for part in (doc.nome, doc.parent_folder or "") if part)
    return _extract_dates(haystack)


def _document_matches_title_date_range(
    doc: TreeDocument,
    *,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    if date_from is None and date_to is None:
        return True

    for title_date in _document_title_dates(doc):
        parsed = _parse_br_date(title_date, field_name="date do titulo")
        if date_from and parsed < date_from:
            continue
        if date_to and parsed > date_to:
            continue
        return True
    return False


def _dedupe_documents(docs: list[TreeDocument]) -> list[TreeDocument]:
    seen: set[str] = set()
    result: list[TreeDocument] = []
    for doc in docs:
        if doc.id_documento in seen:
            continue
        seen.add(doc.id_documento)
        result.append(doc)
    return result


def _select_process_documents(
    docs: list[TreeDocument],
    *,
    mode: str,
    sample_size: int,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[TreeDocument], dict[str, Any], list[str]]:
    normalized_mode = mode.lower()
    if normalized_mode not in {"summary", "all"}:
        raise ParseError(
            "mode deve ser 'summary' ou 'all'.",
            details={"mode": mode},
        )
    if sample_size < 1:
        raise ParseError(
            "sample_size deve ser maior ou igual a 1.",
            details={"sample_size": sample_size},
        )

    date_from_obj = _parse_br_date(date_from, field_name="date_from")
    date_to_obj = _parse_br_date(date_to, field_name="date_to")
    if date_from_obj and date_to_obj and date_from_obj > date_to_obj:
        raise ParseError(
            "date_from nao pode ser maior que date_to.",
            details={"date_from": date_from, "date_to": date_to},
        )

    filtered_docs = [
        doc
        for doc in docs
        if _document_matches_title_date_range(doc, date_from=date_from_obj, date_to=date_to_obj)
    ]
    warnings: list[str] = []

    if (date_from or date_to) and not filtered_docs:
        warnings.append("Nenhum documento com data no titulo corresponde ao recorte informado.")

    if normalized_mode == "all":
        selected_docs = filtered_docs
        strategy = "all-documents" if not (date_from or date_to) else "all-documents-date-filter"
    elif len(filtered_docs) <= sample_size * 2:
        selected_docs = filtered_docs
        strategy = "summary-all-documents" if not (date_from or date_to) else "summary-date-filter"
    else:
        selected_docs = _dedupe_documents(filtered_docs[:sample_size] + filtered_docs[-sample_size:])
        strategy = "summary-first-last-sample"

    selection = {
        "mode_requested": normalized_mode,
        "strategy": strategy,
        "sample_size": sample_size,
        "date_from": date_from,
        "date_to": date_to,
        "date_filter_applied": bool(date_from or date_to),
        "documents_matching_filter_total": len(filtered_docs),
        "documents_selected_total": len(selected_docs),
        "documents_skipped_total": max(len(filtered_docs) - len(selected_docs), 0),
    }
    return selected_docs, selection, warnings


def _selection_scope_label(selection: dict[str, Any], total_docs: int) -> str:
    selected_total = selection.get("documents_selected_total", 0)
    strategy = selection.get("strategy")
    if strategy == "summary-first-last-sample":
        return f"Leitura amostral de {selected_total} documento(s) entre os primeiros e os ultimos de um total de {total_docs}."
    if selection.get("date_filter_applied"):
        return f"Leitura do recorte filtrado de {selected_total} documento(s) a partir das datas do titulo."
    return f"Leitura integral de {selected_total} documento(s) do processo."


def _text_excerpt(text: str, *, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


def _extract_pdf_text_from_bytes(data: bytes) -> str:
    # Test fixtures can inject UTF-8 text with a simple sentinel instead of a real PDF.
    if data.startswith(b"TEXT:"):
        return data[5:].decode("utf-8").strip()

    try:
        fitz = importlib.import_module("fitz")
    except ImportError as exc:
        raise ParseError(
            "PyMuPDF (fitz) nao esta disponivel para extrair texto de PDF.",
            details={"dependency": "PyMuPDF"},
        ) from exc

    try:
        with fitz.open(stream=io.BytesIO(data), filetype="pdf") as document:
            pages = [page.get_text("text").strip() for page in document]
    except Exception as exc:
        raise ParseError(
            "Falha ao extrair texto do PDF.",
            details={"reason": str(exc)},
        ) from exc

    text = "\n".join(page for page in pages if page).strip()
    if not text:
        raise ParseError("O PDF nao contem texto extraivel.", details={})
    return text


def _read_tree_document_text(
    client: Any,
    doc: TreeDocument | None,
    *,
    id_documento: str,
    id_procedimento: str,
) -> tuple[str, str]:
    read_document_content = getattr(client, "read_document_content", None)

    if doc and doc.src_url and callable(read_document_content):
        try:
            return read_document_content(doc), "read_document_content"
        except Exception as exc:
            refreshed_doc, refreshed_process_id = _refresh_tree_document(
                client,
                doc,
                id_documento=id_documento,
                id_procedimento=id_procedimento,
            )
            if refreshed_doc and refreshed_doc.src_url and callable(read_document_content):
                try:
                    return read_document_content(refreshed_doc), "read_document_content_retry"
                except Exception:
                    pass
            last_error = exc
        else:
            last_error = None
    else:
        last_error = None

    if doc and doc.tipo.lower() == "interno":
        try:
            return client.read_document(id_documento, id_procedimento), "read_document"
        except Exception:
            refreshed_doc, refreshed_process_id = _refresh_tree_document(
                client,
                doc,
                id_documento=id_documento,
                id_procedimento=id_procedimento,
            )
            if refreshed_doc:
                try:
                    return client.read_document(refreshed_doc.id_documento, refreshed_process_id), "read_document_retry"
                except Exception:
                    if refreshed_doc.src_url and callable(read_document_content):
                        return read_document_content(refreshed_doc), "read_document_content_retry"
            raise

    if doc and doc.tipo.lower() in {"pdf", "documento", "externo"}:
        downloader = getattr(client, "download_document", None)
        if not callable(downloader):
            raise ParseError(
                "Cliente nao suporta download de documento para leitura binaria.",
                details={"id_documento": id_documento, "tipo": doc.tipo},
            )
        try:
            payload = downloader(doc)
        except Exception:
            refreshed_doc, refreshed_process_id = _refresh_tree_document(
                client,
                doc,
                id_documento=id_documento,
                id_procedimento=id_procedimento,
            )
            if not refreshed_doc:
                raise
            payload = downloader(refreshed_doc)
            id_procedimento = refreshed_process_id
            method_suffix = "_retry"
        else:
            method_suffix = ""

        if isinstance(payload, bytes):
            return _extract_pdf_text_from_bytes(payload), f"download_document_pdf{method_suffix}"
        if isinstance(payload, str):
            return payload, f"download_document_text{method_suffix}"
        raise ParseError(
            "Tipo de retorno inesperado ao baixar documento.",
            details={"id_documento": id_documento, "tipo": doc.tipo},
        )

    if last_error is not None:
        raise last_error

    return client.read_document(id_documento, id_procedimento), "read_document_fallback"


def _document_read_core(
    client: Any,
    *,
    context: dict[str, Any],
    id_documento: str,
    id_procedimento: str,
    numero_documento: str | None = None,
    docs: list[TreeDocument] | None = None,
    process: Process | None = None,
    navigation_mode: str,
) -> dict[str, Any]:
    docs = docs if docs is not None else client.get_full_document_tree(id_procedimento)
    doc_meta = next((doc for doc in docs if doc.id_documento == id_documento), None)
    process = process or _find_process_metadata(client, id_procedimento, None)
    text, extraction_method = _read_tree_document_text(
        client,
        doc_meta,
        id_documento=id_documento,
        id_procedimento=id_procedimento,
    )

    numero_documento_resolvido = (
        doc_meta.sei_number if doc_meta and doc_meta.sei_number else numero_documento or id_documento
    )
    metadata = _tree_document(doc_meta) if doc_meta else {
        "id_documento": id_documento,
        "sei_number": numero_documento_resolvido,
    }
    if "assinado eletronicamente" in text.casefold():
        metadata["assinado"] = True

    process_actions = _safe_get_actions(client, id_procedimento)
    document_actions = _safe_get_actions(client, id_procedimento, id_documento)
    action_context = _action_context(process_actions, document_actions)
    ui_context = _ui_context(
        context=context,
        process=process,
        docs=docs,
        doc_meta=doc_meta,
        text=text,
        action_context=action_context,
        navigation_mode=navigation_mode,
    )
    semantic_context, domain_context = _semantic_context(metadata, text)
    lines = [line for line in text.splitlines() if line.strip()]

    return {
        "resolved_ids": {
            "id_documento": id_documento,
            "id_procedimento": id_procedimento,
            "numero_documento": numero_documento_resolvido,
        },
        "data": {
            "documento": metadata,
            "text": text,
            "line_count": len(lines),
            "char_count": len(text),
            "extraction_method": extraction_method,
            "ui_context": ui_context,
            "action_context": action_context,
            "semantic_context": semantic_context,
            "domain_context": domain_context,
        },
    }


def _unique_people(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = (
            value.get("display_name")
            or value.get("name")
            or ""
        ).strip()
        if not key:
            continue
        normalized = key.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _guess_process_kind(semantic_contexts: list[dict[str, Any]]) -> str:
    counts: Counter[str] = Counter()
    priority = {
        "reaprazamento": 0,
        "material": 1,
        "diarias": 2,
        "informacao": 3,
        "relatorio_operacional": 4,
        "generic": 99,
    }
    for semantic in semantic_contexts:
        kind = semantic.get("document_kind_guess") or "generic"
        if kind == "generic":
            continue
        counts[kind] += 1 if kind == "relatorio_operacional" else 3
    if not counts:
        return "generic"
    return sorted(counts, key=lambda item: (-counts[item], priority.get(item, 50)))[0]


def _aggregate_process_domain_context(
    process_kind_guess: str,
    analyzed_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    domain_contexts = [item["domain_context"] for item in analyzed_documents if item.get("ok", True)]

    if process_kind_guess == "reaprazamento":
        requesters = _unique_strings(
            [
                ctx["fields"].get("military_requester")
                for ctx in domain_contexts
                if ctx.get("kind") == "reaprazamento" and ctx["fields"].get("military_requester")
            ]
        )
        original_dates = _unique_strings(
            [
                ctx["fields"].get("original_date")
                for ctx in domain_contexts
                if ctx.get("kind") == "reaprazamento" and ctx["fields"].get("original_date")
            ]
        )
        requested_dates = _unique_strings(
            [
                ctx["fields"].get("requested_date")
                for ctx in domain_contexts
                if ctx.get("kind") == "reaprazamento" and ctx["fields"].get("requested_date")
            ]
        )
        justifications = _unique_strings(
            [
                ctx["fields"].get("justification")
                for ctx in domain_contexts
                if ctx.get("kind") == "reaprazamento" and ctx["fields"].get("justification")
            ]
        )
        return {
            "kind": process_kind_guess,
            "fields": {
                "military_requesters": requesters,
                "original_dates": original_dates,
                "requested_dates": requested_dates,
                "justifications": justifications,
                "requires_authorization": any(
                    ctx["fields"].get("requires_authorization")
                    for ctx in domain_contexts
                    if ctx.get("kind") == "reaprazamento"
                ),
            },
        }

    if process_kind_guess == "material":
        material_items: list[dict[str, Any]] = []
        for ctx in domain_contexts:
            if ctx.get("kind") != "material":
                continue
            material_items.extend(ctx["fields"].get("material_items", []))
        return {
            "kind": process_kind_guess,
            "fields": {
                "material_items": material_items,
                "materials_total": len(material_items),
            },
        }

    return {"kind": process_kind_guess, "fields": {}}


def _build_process_summary(
    *,
    selection: dict[str, Any],
    total_docs: int,
    process_kind_guess: str,
    process_domain_context: dict[str, Any],
    involved_military: list[dict[str, Any]],
    involved_units: list[str],
    analyzed_documents: list[dict[str, Any]],
) -> str:
    parts = [_selection_scope_label(selection, total_docs)]

    if process_kind_guess == "reaprazamento":
        fields = process_domain_context.get("fields", {})
        requester = ", ".join(fields.get("military_requesters", [])[:2]) or (
            involved_military[0]["display_name"] if involved_military else "militar não identificado"
        )
        original_date = ", ".join(fields.get("original_dates", [])[:1]) or "data original não identificada"
        requested_date = ", ".join(fields.get("requested_dates", [])[:1]) or "data pretendida não identificada"
        parts.append(
            f"O processo parece tratar de reaprazamento de férias envolvendo {requester}, com mudança de {original_date} para {requested_date}."
        )
    elif process_kind_guess == "material":
        total = process_domain_context.get("fields", {}).get("materials_total", 0)
        parts.append(f"O processo parece tratar de demanda de material, com {total} item(ns) identificado(s).")
    else:
        key_summaries = [
            item["semantic_context"].get("summary")
            for item in analyzed_documents
            if item.get("ok", True) and item["semantic_context"].get("summary")
        ]
        if key_summaries:
            parts.append(key_summaries[0])

    if involved_units:
        parts.append(f"Unidades citadas: {', '.join(involved_units[:4])}.")
    return " ".join(parts)


def _aggregate_process_context(
    analyzed_documents: list[dict[str, Any]],
    *,
    selection: dict[str, Any],
    total_docs: int,
) -> dict[str, Any]:
    successful = [item for item in analyzed_documents if item.get("ok", True)]
    semantic_contexts = [item["semantic_context"] for item in successful]

    involved_people = _unique_people(
        [person for semantic in semantic_contexts for person in semantic.get("involved_people", [])]
    )
    involved_units = _unique_strings(
        [unit for semantic in semantic_contexts for unit in semantic.get("involved_units", [])]
    )
    mentioned_dates = _unique_strings(
        [value for semantic in semantic_contexts for value in semantic.get("mentioned_dates", [])]
    )
    deadlines = _unique_strings(
        [semantic.get("deadline") for semantic in semantic_contexts if semantic.get("deadline")]
    )
    document_kind_counts = dict(
        sorted(Counter(semantic.get("document_kind_guess") or "generic" for semantic in semantic_contexts).items())
    )
    action_kind_counts = Counter(
        semantic.get("action_kind") for semantic in semantic_contexts if semantic.get("action_kind")
    )
    process_kind_guess = _guess_process_kind(semantic_contexts)
    process_domain_context = _aggregate_process_domain_context(process_kind_guess, successful)
    requires_response = any(semantic.get("requires_response") for semantic in semantic_contexts)
    action_required = any(semantic.get("action_required") for semantic in semantic_contexts)
    information_only = bool(semantic_contexts) and not action_required and all(
        semantic.get("information_only") for semantic in semantic_contexts
    )

    key_documents = [
        {
            "documento": item["documento"],
            "summary": item["semantic_context"].get("summary"),
            "document_kind_guess": item["semantic_context"].get("document_kind_guess"),
            "action_required": item["semantic_context"].get("action_required"),
            "action_kind": item["semantic_context"].get("action_kind"),
        }
        for item in successful[:5]
    ]

    return {
        "summary": _build_process_summary(
            selection=selection,
            total_docs=total_docs,
            process_kind_guess=process_kind_guess,
            process_domain_context=process_domain_context,
            involved_military=involved_people,
            involved_units=involved_units,
            analyzed_documents=successful,
        ),
        "process_kind_guess": process_kind_guess,
        "document_kind_counts": document_kind_counts,
        "involved_people": involved_people,
        "involved_military": involved_people,
        "involved_units": involved_units,
        "mentioned_dates": mentioned_dates,
        "deadlines": deadlines,
        "requires_response": requires_response,
        "action_required": action_required,
        "dominant_action_kind": action_kind_counts.most_common(1)[0][0] if action_kind_counts else None,
        "information_only": information_only,
        "has_relatorio_operacional": any(
            semantic.get("document_kind_guess") == "relatorio_operacional" for semantic in semantic_contexts
        ),
        "domain_context": process_domain_context,
        "key_documents": key_documents,
    }


def inbox_snapshot(client: Any, *, block_limit: int = 5, process_limit: int = 5) -> dict[str, Any]:
    operation = "inbox-snapshot"
    try:
        context = _context(client)
        processes = client.list_processes()
        blocks = client.list_blocks()
        new_items = [process for process in processes.recebidos if process.novo]

        return _result(
            operation=operation,
            context=context,
            data={
                "recebidos_total": len(processes.recebidos),
                "gerados_total": len(processes.gerados),
                "novos_total": len(new_items),
                "blocos_total": len(blocks),
                "recebidos_preview": [_process_preview(p) for p in processes.recebidos[:process_limit]],
                "gerados_preview": [_process_preview(p) for p in processes.gerados[:process_limit]],
                "novos_preview": [_process_preview(p) for p in new_items[:process_limit]],
                "blocos_preview": [_block_preview(b) for b in blocks[:block_limit]],
            },
            next_actions=[
                NextAction(action="process-open", label="Abrir um processo"),
                NextAction(action="document-read", label="Ler um documento"),
            ],
        )
    except Exception as exc:
        return _error_result(operation=operation, exc=exc)


def process_open(client: Any, numero_ou_id: str) -> dict[str, Any]:
    operation = "process-open"
    resolved_ids: dict[str, Any] = {}
    try:
        context = _context(client)
        id_procedimento, numero_processo = _resolve_process_id(client, numero_ou_id)

        process = _find_process_metadata(client, id_procedimento, numero_processo)
        resolved_ids = {
            "id_procedimento": id_procedimento,
            "numero_processo": (process.numero if process and process.numero else numero_processo or numero_ou_id),
        }
        docs = client.get_full_document_tree(id_procedimento)
        warnings: list[str] = []
        if not docs:
            warnings.append("Nenhum documento foi encontrado ou a arvore nao estava acessivel.")

        process_data = _process_preview(process) if process else {
            "numero": numero_processo or numero_ou_id,
            "id_procedimento": id_procedimento,
        }

        next_actions = [NextAction(action="document-read", label="Ler documento do processo")]
        first_doc = next((doc for doc in docs if doc.sei_number), None)
        if first_doc and first_doc.sei_number:
            next_actions.append(
                NextAction(
                    action="document-read",
                    label="Ler primeiro documento listado",
                    params={"numero": first_doc.sei_number},
                )
            )

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "processo": process_data,
                "documents_total": len(docs),
                "documents": [_tree_document(doc) for doc in docs],
            },
            next_actions=next_actions,
            warnings=warnings,
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def process_read(
    client: Any,
    numero_ou_id: str,
    *,
    mode: str = "summary",
    date_from: str | None = None,
    date_to: str | None = None,
    sample_size: int = 3,
) -> dict[str, Any]:
    operation = "process-read"
    resolved_ids: dict[str, Any] = {}
    try:
        context = _context(client)
        id_procedimento, numero_processo = _resolve_process_id(client, numero_ou_id)
        preflight, unit_guard = _process_unit_preflight(client, id_procedimento)

        with unit_guard as switched_to:
            if switched_to:
                preflight["switched"] = True
                preflight["switched_to"] = switched_to
                context = _context(client)

            process = _find_process_metadata(client, id_procedimento, numero_processo)
            docs = client.get_full_document_tree(id_procedimento)
            resolved_ids = {
                "id_procedimento": id_procedimento,
                "numero_processo": (process.numero if process and process.numero else numero_processo or numero_ou_id),
            }

            signed_total = sum(1 for doc in docs if doc.assinado)
            folder_names = sorted({doc.parent_folder for doc in docs if doc.parent_folder})
            type_counts = dict(sorted(Counter(doc.tipo for doc in docs).items()))
            relatorio_docs = [doc for doc in docs if _relatorio_candidate(doc)]
            process_actions = _safe_get_actions(client, id_procedimento)
            action_context = _action_context(process_actions, {})
            ui_context = _ui_context(
                context=context,
                process=process,
                docs=docs,
                doc_meta=None,
                text="",
                action_context=action_context,
                navigation_mode="quick-search-process" if "." in numero_ou_id or "/" in numero_ou_id else "direct-process-id",
            )
            selected_docs, selection, warnings = _select_process_documents(
                docs,
                mode=mode,
                sample_size=sample_size,
                date_from=date_from,
                date_to=date_to,
            )

            analyzed_documents: list[dict[str, Any]] = []
            for doc in selected_docs:
                try:
                    doc_result = _document_read_core(
                        client,
                        context=context,
                        id_documento=doc.id_documento,
                        id_procedimento=id_procedimento,
                        numero_documento=doc.sei_number,
                        docs=docs,
                        process=process,
                        navigation_mode="process-tree-document-selection",
                    )
                    analyzed_documents.append(
                        {
                            "ok": True,
                            "resolved_ids": doc_result["resolved_ids"],
                            "documento": doc_result["data"]["documento"],
                            "line_count": doc_result["data"]["line_count"],
                            "char_count": doc_result["data"]["char_count"],
                            "extraction_method": doc_result["data"]["extraction_method"],
                            "text_excerpt": _text_excerpt(doc_result["data"]["text"]),
                            "ui_context": doc_result["data"]["ui_context"],
                            "action_context": doc_result["data"]["action_context"],
                            "semantic_context": doc_result["data"]["semantic_context"],
                            "domain_context": doc_result["data"]["domain_context"],
                        }
                    )
                except Exception as exc:
                    read_error = error_from_exception(exc)
                    analyzed_documents.append(
                        {
                            "ok": False,
                            "documento": _tree_document(doc),
                            "extraction_method": "failed",
                            "read_error": {
                                "code": read_error.code,
                                "message": read_error.message,
                                "retryable": read_error.retryable,
                                "details": read_error.details,
                            },
                        }
                    )
                    warnings.append(
                        f"Falha ao ler o documento {doc.sei_number or doc.id_documento}: {exc}"
                    )

            documents_succeeded_total = sum(1 for item in analyzed_documents if item.get("ok", True))
            documents_failed_total = len(analyzed_documents) - documents_succeeded_total
            pdf_selected_total = sum(1 for doc in selected_docs if doc.tipo.lower() in {"pdf", "documento", "externo"})
            internal_selected_total = sum(1 for doc in selected_docs if doc.tipo.lower() == "interno")
            process_context = _aggregate_process_context(
                analyzed_documents,
                selection=selection,
                total_docs=len(docs),
            )

        next_actions: list[NextAction] = []
        if selected_docs:
            first_doc = next((doc for doc in selected_docs if doc.sei_number), selected_docs[0])
            next_actions.append(
                NextAction(
                    action="document-read",
                    label="Ler um documento do processo",
                    params={"numero": first_doc.sei_number or first_doc.id_documento},
                )
            )
        if relatorio_docs:
            rel_doc = next((doc for doc in relatorio_docs if doc.sei_number), relatorio_docs[0])
            next_actions.append(
                NextAction(
                    action="relatorio-read",
                    label="Ler relatório do processo",
                    params={"numero": rel_doc.sei_number or rel_doc.id_documento},
                )
            )
        if selection["documents_selected_total"] < selection["documents_matching_filter_total"]:
            next_actions.append(
                NextAction(
                    action="process-read",
                    label="Ler todos os documentos do processo",
                    params={"numero_ou_id": id_procedimento, "mode": "all"},
                )
            )

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "processo": _process_preview(process) if process else {
                    "numero": numero_processo or numero_ou_id,
                    "id_procedimento": id_procedimento,
                },
                "documents_total": len(docs),
                "signed_total": signed_total,
                "unsigned_total": len(docs) - signed_total,
                "folders_total": len(folder_names),
                "folders": folder_names,
                "relatorios_total": len(relatorio_docs),
                "document_type_counts": type_counts,
                "ui_context": ui_context,
                "action_context": action_context,
                "preflight": preflight,
                "selection": selection,
                "process_context": process_context,
                "documents": [_tree_document(doc) for doc in docs],
                "documents_selected": [_tree_document(doc) for doc in selected_docs],
                "documents_read": analyzed_documents,
                "read_summary": {
                    "documents_selected_total": len(selected_docs),
                    "documents_succeeded_total": documents_succeeded_total,
                    "documents_failed_total": documents_failed_total,
                    "partial_read": documents_failed_total > 0,
                    "pdf_selected_total": pdf_selected_total,
                    "internal_selected_total": internal_selected_total,
                },
                "relatorio_candidates": [_tree_document(doc) for doc in relatorio_docs],
            },
            next_actions=next_actions,
            warnings=warnings if docs else warnings + ["Nenhum documento foi encontrado ou a arvore nao estava acessivel."],
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def _process_action_items(process_result: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in process_result["data"].get("documents_read", []):
        if not item.get("ok", True):
            items.append(
                {
                    "documento": item.get("documento", {}),
                    "status": "failed",
                    "action_kind": "review_failure",
                    "reason": (item.get("read_error") or {}).get("message"),
                }
            )
            continue

        semantic = item.get("semantic_context", {})
        if semantic.get("action_required"):
            items.append(
                {
                    "documento": item.get("documento", {}),
                    "status": "pending",
                    "action_kind": semantic.get("action_kind"),
                    "reason": semantic.get("summary"),
                }
            )
    return items


def _signature_status(documento: dict[str, Any]) -> dict[str, Any]:
    signed = bool(documento.get("assinado"))
    return {
        "signed": signed,
        "signature_required": True,
        "signature_pending": not signed,
        "compliance_status": "signed" if signed else "pending_signature",
    }


def _fallback_relatorio_from_text(text: str) -> RelatorioServico:
    relatorio = RelatorioServico()
    compact = " ".join(text.split())

    fiscal_match = re.search(
        r"(?P<posto>SD\s+BM|CB\s+BM|[123][°º]?\s*SGT(?:\s+(?:QP)?BM|\s+BM)?|ST\s+BM|"
        r"[12][°º]?\s*TEN(?:\s+QOEM)?(?:\s+BM)?|CAP(?:\s+BM)?|MAJ(?:\s+BM)?|TC(?:\s+BM)?|CEL(?:\s+BM)?)\s+"
        r"(?P<nome>[A-ZÁ-Ú][A-Za-zÁ-Úá-ú']+(?:\s+[A-ZÁ-Ú][A-Za-zÁ-Úá-ú']+){0,5})\s*-?\s*Fiscal de Opera",
        compact,
        re.IGNORECASE,
    )
    if fiscal_match:
        relatorio.posto_fiscal = " ".join(fiscal_match.group("posto").split())
        relatorio.fiscal = " ".join(fiscal_match.group("nome").split())

    date_window = re.search(
        r"do dia (\d{1,2})\s+para\s+o dia (\d{1,2})\s+de\s+([A-Za-zçÇãõáéíóú]+)\s+de\s+(\d{4})",
        compact,
        re.IGNORECASE,
    )
    if date_window:
        day_start, day_end, month_name, year = date_window.groups()
        month_number = {
            "janeiro": "01",
            "fevereiro": "02",
            "março": "03",
            "marco": "03",
            "abril": "04",
            "maio": "05",
            "junho": "06",
            "julho": "07",
            "agosto": "08",
            "setembro": "09",
            "outubro": "10",
            "novembro": "11",
            "dezembro": "12",
        }.get(month_name.lower(), "00")
        relatorio.data_inicio = f"{int(day_start):02d}/{month_number}/{year}"
        relatorio.data_fim = f"{int(day_end):02d}/{month_number}/{year}"
    else:
        dates = _extract_dates(text)
        if dates:
            relatorio.data_inicio = dates[0]
        if len(dates) > 1:
            relatorio.data_fim = dates[1]

    unit_match = re.search(r"Ao Comando do ([^\n,]+)", compact, re.IGNORECASE)
    if unit_match:
        relatorio.unidade = unit_match.group(1).strip()
    else:
        units = _extract_units(text)
        if units:
            relatorio.unidade = units[0]

    for person in _extract_military_people(text):
        relatorio.militares.append(
            relatorio_to_militar(person),
        )

    if not relatorio.assuntos_gerais:
        first_lines = [line.strip() for line in text.splitlines() if line.strip()]
        relatorio.assuntos_gerais = first_lines[:3]

    return relatorio


def relatorio_to_militar(person: dict[str, Any]) -> Any:
    from sei_cli.relatorio_parser import Militar

    return Militar(
        nome=person.get("name", ""),
        posto=person.get("rank", ""),
        funcao=person.get("role") or "Militar citado",
        status="ordinario",
    )


def process_summary(
    client: Any,
    numero_ou_id: str,
    *,
    mode: str = "summary",
    date_from: str | None = None,
    date_to: str | None = None,
    sample_size: int = 3,
) -> dict[str, Any]:
    operation = "process-summary"
    base_result = process_read(
        client,
        numero_ou_id,
        mode=mode,
        date_from=date_from,
        date_to=date_to,
        sample_size=sample_size,
    )
    if not base_result["ok"]:
        base_result["operation"] = operation
        return base_result

    data = base_result["data"]
    process_context = data.get("process_context", {})
    read_summary = data.get("read_summary", {})
    summary_data = {
        "processo": data.get("processo", {}),
        "summary": process_context.get("summary"),
        "process_kind_guess": process_context.get("process_kind_guess"),
        "preflight": data.get("preflight", {}),
        "selection": data.get("selection", {}),
        "read_summary": read_summary,
        "involved_military": process_context.get("involved_military", []),
        "involved_units": process_context.get("involved_units", []),
        "mentioned_dates": process_context.get("mentioned_dates", []),
        "deadlines": process_context.get("deadlines", []),
        "requires_response": process_context.get("requires_response"),
        "action_required": process_context.get("action_required"),
        "dominant_action_kind": process_context.get("dominant_action_kind"),
        "key_documents": process_context.get("key_documents", []),
        "action_items": _process_action_items(base_result),
    }
    return _result(
        operation=operation,
        context=base_result["context"],
        resolved_ids=base_result["resolved_ids"],
        data=summary_data,
        next_actions=[
            NextAction(action="process-read", label="Ler contexto completo do processo", params={"numero_ou_id": numero_ou_id}),
            *[NextAction(**item) for item in base_result.get("next_actions", [])[:2]],
        ],
        warnings=base_result.get("warnings", []),
    )


def _normalize_marker_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        marker_id = item.get("marcador_id") or item.get("id")
        return {
            "marcador_id": marker_id,
            "id": marker_id,
            "nome": item.get("nome"),
            "descricao": item.get("descricao") or "",
            "cor": item.get("cor"),
            "link": item.get("link"),
        }
    return {
        "marcador_id": getattr(item, "marcador_id", None),
        "id": getattr(item, "marcador_id", None),
        "nome": getattr(item, "nome", None),
        "descricao": getattr(item, "descricao", "") or "",
        "cor": getattr(item, "cor", None),
        "link": getattr(item, "link", None),
    }


def _normalize_marker_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.strip().casefold().replace("/", " ").replace("-", " ")


def _resolve_marker_reference(markers: list[dict[str, Any]], marker_ref: str | None) -> dict[str, Any] | None:
    if not marker_ref:
        return None
    ref = marker_ref.strip()
    if not ref:
        return None
    for marker in markers:
        if str(marker.get("marcador_id") or "") == ref:
            return marker
    normalized_ref = _normalize_marker_name(ref)
    for marker in markers:
        name = str(marker.get("nome") or "")
        if _normalize_marker_name(name) == normalized_ref:
            return marker
    for marker in markers:
        name = str(marker.get("nome") or "")
        if normalized_ref and normalized_ref in _normalize_marker_name(name):
            return marker
    return None


def _build_marker_suggested_text(summary_data: dict[str, Any]) -> str:
    process_data = summary_data.get("processo") or {}
    parts: list[str] = []
    process_kind = summary_data.get("process_kind_guess")
    process_type = process_data.get("tipo")
    if process_type:
        parts.append(process_type)
    elif process_kind:
        parts.append(str(process_kind).replace("_", " "))
    involved = summary_data.get("involved_military") or []
    if involved:
        names = ", ".join(
            person.get("display_name") or person.get("name") or ""
            for person in involved[:2]
            if person.get("display_name") or person.get("name")
        )
        if names:
            parts.append(names)
    deadlines = summary_data.get("deadlines") or []
    if deadlines:
        parts.append(f"prazo {', '.join(deadlines[:1])}")
    if summary_data.get("action_required"):
        action_kind = summary_data.get("dominant_action_kind") or "manifestacao"
        parts.append(f"aguarda {action_kind}")
    elif summary_data.get("requires_response"):
        parts.append("demanda resposta")
    elif summary_data.get("information_only"):
        parts.append("somente informação")

    short = " - ".join(part.strip(" .") for part in parts if part).strip()
    # Sanitize to latin-1 safe chars (SEI encoding)
    short = short.encode("latin-1", errors="replace").decode("latin-1")
    if short:
        return short

    summary = " ".join((summary_data.get("summary") or "").split()).strip()
    if summary:
        return summary[:180].rstrip(" .,;") + ("..." if len(summary) > 180 else "")
    return ""


def _suggest_marker_from_summary(markers: list[dict[str, Any]], summary_data: dict[str, Any]) -> dict[str, Any] | None:
    haystacks = [
        str((summary_data.get("processo") or {}).get("tipo") or ""),
        str((summary_data.get("processo") or {}).get("especificacao") or ""),
        str(summary_data.get("summary") or ""),
        str(summary_data.get("process_kind_guess") or ""),
    ]
    haystack = _normalize_marker_name(" ".join(haystacks))
    preference_map = [
        ("ferias", "Férias / Dispensas"),
        ("dispensa", "Férias / Dispensas"),
        ("licenca", "Férias / Dispensas"),
        ("auxilio alimenta", "Auxílio Alimentação"),
        ("auxilio refeic", "Auxílio Alimentação"),
        ("capacitac", "Cursos / Capacitacao"),
        ("curso", "Cursos / Capacitacao"),
        ("instrucao", "Cursos / Capacitacao"),
        ("treinamento", "Cursos / Capacitacao"),
        ("vistoria", "Vistorias / Camara Tecnica"),
        ("camara tecnica", "Vistorias / Camara Tecnica"),
        ("evento", "Demandas Externas"),
        ("peticionamento", "Demandas Externas"),
        ("demanda externa", "Demandas Externas"),
        ("orgao", "Demandas Externas"),
        ("oficio", "Ofícios"),
        ("normativo", "Normativos / Diretrizes"),
        ("diretriz", "Normativos / Diretrizes"),
        ("orientac", "Normativos / Diretrizes"),
        ("material", "Materiais"),
        ("viatura", "VTR / Viaturas"),
        ("vtr", "VTR / Viaturas"),
        ("licitac", "Licitacoes / Contratos"),
        ("contrato", "Licitacoes / Contratos"),
        ("diaria", "Diárias Operacionais"),
        ("denuncia", "Denúncias"),
        ("interdi", "Interdições 2025"),
        ("notifica", "Notificações 2025"),
        ("suprimento", "Suprimento de Fundos"),
        ("pessoal", "Pessoal / Requerimentos"),
        ("requerimento", "Pessoal / Requerimentos"),
        ("censo", "Pessoal / Requerimentos"),
        ("cadastral", "Pessoal / Requerimentos"),
        ("isenc", "Isenção de CLEP"),
        ("clep", "Isenção de CLEP"),
        ("levantamento", "Demandas Externas"),
    ]
    for token, marker_name in preference_map:
        if token in haystack:
            resolved = _resolve_marker_reference(markers, marker_name)
            if resolved:
                return resolved
    # Fallback: "Ofícios" as catch-all for uncategorized processes
    fallback = _resolve_marker_reference(markers, "Ofícios")
    return fallback


def _environment_triage_reason(process: Process) -> list[str]:
    reasons: list[str] = []
    if process.novo:
        reasons.append("new")
    if process.recente:
        reasons.append("changed")
    if not process.marcador:
        reasons.append("unmarked")
    elif process.recente:
        reasons.append("marked_review")
    return reasons


def _environment_candidate(process: Process, *, include_marked_review: bool) -> bool:
    if process.novo or process.recente or not process.marcador:
        return True
    if include_marked_review and process.marcador:
        return True
    return False


def _fast_suggest_marker(markers: list[dict[str, Any]], process: Process) -> dict[str, Any] | None:
    """Suggest a marker using only process metadata (tipo + especificacao). No HTTP calls."""
    fake_summary = {
        "processo": {"tipo": process.tipo or "", "especificacao": process.especificacao or ""},
        "summary": f"{process.tipo or ''} {process.especificacao or ''}",
        "process_kind_guess": "",
    }
    return _suggest_marker_from_summary(markers, fake_summary)


def _sanitize_marker_text(value: str) -> str:
    value = " ".join(value.split()).strip()
    value = value.encode("latin-1", errors="replace").decode("latin-1")
    return value[:180].rstrip(" .,;")


def _process_subject(process: Process) -> str:
    tipo = (process.tipo or "").strip(" .")
    especificacao = (process.especificacao or "").strip(" .")
    if especificacao and tipo:
        tipo_norm = _normalize_marker_name(tipo)
        especificacao_norm = _normalize_marker_name(especificacao)
        if tipo_norm and tipo_norm not in especificacao_norm:
            return f"{tipo} - {especificacao}"
        return especificacao
    return especificacao or tipo or process.numero


def _status_from_semantic(semantic_context: dict[str, Any], text: str, doc: TreeDocument | None = None) -> str:
    lower = text.lower()
    deadline = semantic_context.get("deadline")
    if deadline:
        return f"responder até {deadline}"
    if semantic_context.get("action_required"):
        action_kind = semantic_context.get("action_kind")
        if action_kind == "despacho":
            return "aguarda despacho"
        if action_kind == "encaminhamento":
            return "aguarda encaminhamento"
        return "exige providência"
    if "empenho" in lower:
        return "empenho emitido"
    if "autoriz" in lower:
        return "autorizado"
    if "encaminh" in lower:
        return "encaminhado"
    if semantic_context.get("information_only"):
        return "somente informação"
    if doc and doc.assinado:
        return "último documento assinado"
    return "em andamento"


def _fast_suggested_text(process: Process) -> str:
    """Build suggested marker text from process metadata only. No HTTP calls."""
    subject = _process_subject(process)
    parts: list[str] = []
    if subject:
        parts.append(subject)
    if process.novo:
        parts.append("novo")
    elif process.recente:
        parts.append("teve novidade")
    short = " - ".join(part.strip(" .") for part in parts if part).strip()
    return _sanitize_marker_text(short) if short else ""


def _select_context_document(docs: list[TreeDocument]) -> TreeDocument | None:
    if not docs:
        return None

    def _score(item: tuple[int, TreeDocument]) -> tuple[int, int]:
        index, doc = item
        name = _normalize_marker_name(doc.nome or "")
        keyword_score = 0
        for token, score in (
            ("despacho", 60),
            ("oficio", 55),
            ("parecer", 50),
            ("manifest", 45),
            ("requer", 40),
            ("solicit", 35),
            ("relatorio", 30),
            ("inform", 25),
            ("parte generica", 20),
        ):
            if token in name:
                keyword_score = max(keyword_score, score)
        signed_score = 5 if doc.assinado else 0
        recency_score = index
        return keyword_score + signed_score + recency_score, recency_score

    index, selected = max(enumerate(docs), key=_score)
    return docs[index] if selected else None


def _contextual_triage_candidate(client: Any, process: Process, markers: list[dict[str, Any]]) -> dict[str, Any]:
    process_preview = _process_preview(process)
    process_id = process.id_procedimento or process.numero
    docs = client.get_full_document_tree(process_id)
    context_doc = _select_context_document(docs)
    if not context_doc:
        selected_marker = _fast_suggest_marker(markers, process)
        suggested_text = _fast_suggested_text(process)
        return {
            "processo": process_preview,
            "triage_reason": _environment_triage_reason(process),
            "marker_action": "create" if not process.marcador else ("update" if process.recente or process.novo else "keep"),
            "current_marker": process.marcador,
            "selected_marker": selected_marker,
            "suggested_marker_text": suggested_text,
            "summary": suggested_text,
            "context_document": None,
        }

    text, extraction_method = _read_tree_document_text(
        client,
        context_doc,
        id_documento=context_doc.id_documento,
        id_procedimento=process_id,
    )
    semantic_context, _domain_context = _semantic_context(
        {
            "nome": context_doc.nome,
            "tipo": context_doc.tipo,
            "sei_number": context_doc.sei_number,
        },
        text,
    )
    summary_data = {
        "processo": {
            "tipo": process.tipo or "",
            "especificacao": process.especificacao or "",
        },
        "summary": semantic_context.get("summary") or "",
        "process_kind_guess": semantic_context.get("document_kind_guess") or "",
        "involved_military": semantic_context.get("involved_military") or [],
        "deadlines": [semantic_context["deadline"]] if semantic_context.get("deadline") else [],
        "requires_response": semantic_context.get("requires_response"),
        "action_required": semantic_context.get("action_required"),
        "dominant_action_kind": semantic_context.get("action_kind"),
        "information_only": semantic_context.get("information_only"),
    }
    selected_marker = _suggest_marker_from_summary(markers, summary_data)
    subject = _process_subject(process)
    status = _status_from_semantic(semantic_context, text, context_doc)
    suggested_text = _sanitize_marker_text(f"{subject} - {status}")
    marker_action = "create" if not process.marcador else ("update" if process.recente or process.novo else "keep")
    return {
        "processo": process_preview,
        "triage_reason": _environment_triage_reason(process),
        "marker_action": marker_action,
        "current_marker": process.marcador,
        "selected_marker": selected_marker,
        "suggested_marker_text": suggested_text,
        "summary": semantic_context.get("summary") or suggested_text,
        "context_document": {
            "id_documento": context_doc.id_documento,
            "numero_documento": context_doc.sei_number,
            "nome": context_doc.nome,
            "tipo": context_doc.tipo,
            "assinado": context_doc.assinado,
            "extraction_method": extraction_method,
        },
    }


def _triage_priority(process: Process) -> tuple[int, int]:
    score = 0
    if process.novo:
        score += 4
    if process.recente:
        score += 3
    if not process.marcador:
        score += 2
    return score, 1 if process.caixa == "recebidos" else 0


def _list_process_markers(client: Any, id_procedimento: str) -> list[dict[str, Any]]:
    if not hasattr(client, "list_process_markers"):
        return []
    return [
        _normalize_marker_item(item) | {"texto": item.get("texto", "")}
        for item in client.list_process_markers(id_procedimento)
    ]


def marker_catalog(client: Any) -> dict[str, Any]:
    operation = "marker-catalog"
    resolved_ids: dict[str, Any] = {}
    try:
        context = _context(client)
        markers = [_normalize_marker_item(item) for item in client.list_marcadores()]
        return _result(
            operation=operation,
            context=context,
            data={
                "markers_total": len(markers),
                "markers": markers,
            },
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def process_marker_preview(
    client: Any,
    numero_ou_id: str,
    *,
    marker: str | None = None,
    mode: str = "summary",
    date_from: str | None = None,
    date_to: str | None = None,
    sample_size: int = 3,
    suggested_text: str | None = None,
) -> dict[str, Any]:
    operation = "process-marker-preview"
    base_result = process_summary(
        client,
        numero_ou_id,
        mode=mode,
        date_from=date_from,
        date_to=date_to,
        sample_size=sample_size,
    )
    if not base_result["ok"]:
        base_result["operation"] = operation
        return base_result

    markers = [_normalize_marker_item(item) for item in client.list_marcadores()]
    selected_marker = _resolve_marker_reference(markers, marker)
    warnings = list(base_result.get("warnings", []))
    if marker and not selected_marker:
        warnings.append(f"Marcador '{marker}' não encontrado no catálogo atual da unidade.")

    summary_data = base_result["data"]
    marker_text = (suggested_text or "").strip() or _build_marker_suggested_text(summary_data)
    process_data = summary_data.get("processo", {})
    current_markers = _list_process_markers(client, base_result["resolved_ids"]["id_procedimento"])
    current_marker = process_data.get("marcador")

    return _result(
        operation=operation,
        context=base_result["context"],
        resolved_ids=base_result["resolved_ids"],
        data={
            "processo": process_data,
            "preflight": summary_data.get("preflight", {}),
            "current_marker": current_marker,
            "current_markers": current_markers,
            "summary": summary_data.get("summary"),
            "action_items": summary_data.get("action_items", []),
            "requires_response": summary_data.get("requires_response"),
            "action_required": summary_data.get("action_required"),
            "deadlines": summary_data.get("deadlines", []),
            "involved_military": summary_data.get("involved_military", []),
            "selected_marker": selected_marker,
            "suggested_marker_text": marker_text,
            "available_markers_total": len(markers),
            "available_markers": markers,
        },
        next_actions=[
            NextAction(
                action="process-marker-set-preview",
                label="Preparar aplicação de marcador no processo",
                params={
                    "numero_ou_id": base_result["resolved_ids"].get("id_procedimento") or numero_ou_id,
                    "marker": selected_marker.get("marcador_id") if selected_marker else marker,
                },
            )
        ],
        warnings=warnings,
    )


def process_marker_read(
    client: Any,
    numero_ou_id: str,
    *,
    mode: str = "summary",
    date_from: str | None = None,
    date_to: str | None = None,
    sample_size: int = 3,
) -> dict[str, Any]:
    operation = "process-marker-read"
    base_result = process_marker_preview(
        client,
        numero_ou_id,
        mode=mode,
        date_from=date_from,
        date_to=date_to,
        sample_size=sample_size,
    )
    if not base_result["ok"]:
        base_result["operation"] = operation
        return base_result

    current_markers = base_result["data"].get("current_markers", [])
    return _result(
        operation=operation,
        context=base_result["context"],
        resolved_ids=base_result["resolved_ids"],
        data={
            "processo": base_result["data"].get("processo"),
            "preflight": base_result["data"].get("preflight"),
            "current_marker": base_result["data"].get("current_marker"),
            "current_markers_total": len(current_markers),
            "current_markers": current_markers,
            "available_markers_total": base_result["data"].get("available_markers_total"),
            "available_markers": base_result["data"].get("available_markers"),
            "summary": base_result["data"].get("summary"),
        },
        next_actions=[
            NextAction(
                action="process-marker-history",
                label="Ler histórico de marcador do processo",
                params={"numero_ou_id": base_result["resolved_ids"].get("id_procedimento") or numero_ou_id},
            ),
            NextAction(
                action="process-marker-update-preview",
                label="Preparar alteração do texto de um marcador existente",
                params={"numero_ou_id": base_result["resolved_ids"].get("id_procedimento") or numero_ou_id},
            ),
        ],
        warnings=base_result.get("warnings", []),
    )


def process_marker_history(
    client: Any,
    numero_ou_id: str,
    *,
    marker: str | None = None,
) -> dict[str, Any]:
    operation = "process-marker-history"
    resolved_ids: dict[str, Any] = {}
    try:
        context = _context(client)
        id_procedimento, numero_processo = _resolve_process_id(client, numero_ou_id)
        resolved_ids = {
            "id_procedimento": id_procedimento,
            "numero_processo": numero_processo or numero_ou_id,
        }
        current_markers = _list_process_markers(client, id_procedimento)
        selected_marker = _resolve_marker_reference(current_markers, marker)
        if marker and not selected_marker:
            raise ProcessNotFoundError(f"Marcador '{marker}' não encontrado no processo.")
        entries = client.marker_history(
            id_procedimento,
            marcador_id=(selected_marker or {}).get("marcador_id"),
        )
        users = sorted({item.get("usuario") for item in entries if item.get("usuario")})
        actions = sorted({item.get("acao") for item in entries if item.get("acao")})
        latest_entry = entries[0] if entries else None
        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "selected_marker": selected_marker,
                "current_markers_total": len(current_markers),
                "current_markers": current_markers,
                "history_total": len(entries),
                "history": entries,
                "history_summary": {
                    "users": users,
                    "actions": actions,
                    "latest_entry": latest_entry,
                },
            },
            next_actions=[
                NextAction(
                    action="process-marker-update-preview",
                    label="Preparar alteração do texto do marcador",
                    params={
                        "numero_ou_id": id_procedimento,
                        "marker": (selected_marker or {}).get("marcador_id"),
                    },
                )
            ],
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def environment_triage_preview(
    client: Any,
    *,
    only_new: bool = False,
    only_changed: bool = False,
    only_unmarked: bool = False,
    include_marked_review: bool = False,
    limit: int = 5,
    mode: str = "contextual",
    sample_size: int = 3,
) -> dict[str, Any]:
    operation = "environment-triage-preview"
    try:
        context = _context(client)
        warnings: list[str] = []
        processes = client.list_processes()
        all_processes = list(processes.recebidos) + list(processes.gerados)
        filtered: list[Process] = []
        for process in all_processes:
            if not _environment_candidate(process, include_marked_review=include_marked_review):
                continue
            reasons = _environment_triage_reason(process)
            if only_new and "new" not in reasons:
                continue
            if only_changed and "changed" not in reasons:
                continue
            if only_unmarked and "unmarked" not in reasons:
                continue
            filtered.append(process)

        filtered.sort(key=_triage_priority, reverse=True)
        candidates: list[dict[str, Any]] = []
        markers = [_normalize_marker_item(item) for item in client.list_marcadores()]

        if mode == "deep":
            # Deep mode: reads docs per process (~100s each). Use for small batches.
            for process in filtered:
                if len(candidates) >= limit:
                    break
                preview = process_marker_preview(
                    client,
                    process.id_procedimento or process.numero,
                    mode="summary",
                    sample_size=sample_size,
                )
                if not preview.get("ok"):
                    warnings.append(
                        f"deep_skip:{process.numero}: {((preview.get('error') or {}).get('message') or 'sem acesso ou leitura indisponível')}"
                    )
                    continue
                current_markers = preview["data"].get("current_markers") or []
                selected_marker = _suggest_marker_from_summary(markers, preview["data"])
                if not current_markers:
                    marker_action = "create"
                elif process.recente or process.novo:
                    marker_action = "update"
                else:
                    marker_action = "keep"
                candidates.append(
                    {
                        "processo": preview["data"].get("processo"),
                        "triage_reason": _environment_triage_reason(process),
                        "marker_action": marker_action,
                        "current_marker": preview["data"].get("current_marker"),
                        "current_markers": current_markers,
                        "selected_marker": selected_marker,
                        "suggested_marker_text": preview["data"].get("suggested_marker_text"),
                        "summary": preview["data"].get("summary"),
                    }
                )
        elif mode == "contextual":
            for process in filtered[:limit]:
                try:
                    candidates.append(_contextual_triage_candidate(client, process, markers))
                except Exception as exc:
                    selected_marker = _fast_suggest_marker(markers, process)
                    suggested_text = _fast_suggested_text(process)
                    candidates.append(
                        {
                            "processo": _process_preview(process),
                            "triage_reason": _environment_triage_reason(process),
                            "marker_action": "create" if not process.marcador else ("update" if process.recente or process.novo else "keep"),
                            "current_marker": process.marcador,
                            "selected_marker": selected_marker,
                            "suggested_marker_text": suggested_text,
                            "summary": suggested_text,
                            "context_document": None,
                            "warning": f"contextual_fallback: {exc}",
                        }
                    )
        else:
            # Fast mode: uses only process metadata. No doc reads.
            for process in filtered[:limit]:
                selected_marker = _fast_suggest_marker(markers, process)
                suggested_text = _fast_suggested_text(process)
                has_marker = bool(process.marcador)
                if not has_marker:
                    marker_action = "create"
                elif process.recente or process.novo:
                    marker_action = "update"
                else:
                    marker_action = "keep"
                candidates.append(
                    {
                        "processo": _process_preview(process),
                        "triage_reason": _environment_triage_reason(process),
                        "marker_action": marker_action,
                        "current_marker": process.marcador,
                        "selected_marker": selected_marker,
                        "suggested_marker_text": suggested_text,
                        "summary": suggested_text,
                        "context_document": None,
                    }
                )

        return _result(
            operation=operation,
            context=context,
            data={
                "filters": {
                    "only_new": only_new,
                    "only_changed": only_changed,
                    "only_unmarked": only_unmarked,
                    "include_marked_review": include_marked_review,
                    "limit": limit,
                    "mode": mode,
                },
                "recebidos_total": len(processes.recebidos),
                "gerados_total": len(processes.gerados),
                "candidates_total": len(filtered),
                "candidates_selected_total": len(candidates),
                "candidates": candidates,
            },
            next_actions=[
                NextAction(
                    action="environment-triage-apply",
                    label="Aplicar criação/atualização de marcadores para os candidatos selecionados",
                    params={
                        "only_new": only_new,
                        "only_changed": only_changed,
                        "only_unmarked": only_unmarked,
                        "include_marked_review": include_marked_review,
                        "limit": limit,
                        "mode": mode,
                    },
                )
            ],
            warnings=warnings,
        )
    except Exception as exc:
        return _error_result(operation=operation, exc=exc)


def process_report(
    client: Any,
    numero_ou_id: str,
    *,
    mode: str = "summary",
    date_from: str | None = None,
    date_to: str | None = None,
    sample_size: int = 3,
    include_relatorios: bool = True,
    relatorio_limit: int = 1,
) -> dict[str, Any]:
    operation = "process-report"
    base_result = process_read(
        client,
        numero_ou_id,
        mode=mode,
        date_from=date_from,
        date_to=date_to,
        sample_size=sample_size,
    )
    if not base_result["ok"]:
        base_result["operation"] = operation
        return base_result

    data = base_result["data"]
    process_context = data.get("process_context", {})
    relatorio_reports: list[dict[str, Any]] = []
    relatorio_failures: list[dict[str, Any]] = []
    relatorio_candidates = data.get("relatorio_candidates", [])
    if include_relatorios:
        for candidate in relatorio_candidates:
            numero = candidate.get("sei_number") or candidate.get("id_documento")
            relatorio_result = relatorio_read(client, numero, id_procedimento=base_result["resolved_ids"]["id_procedimento"])
            if relatorio_result["ok"]:
                relatorio_reports.append(
                    {
                        "documento": relatorio_result["data"]["documento"],
                        "signature_status": relatorio_result["data"]["signature_status"],
                        "parsing_strategy": relatorio_result["data"].get("parsing_strategy"),
                        "summary": relatorio_result["data"]["summary"],
                        "relatorio": relatorio_result["data"]["relatorio"],
                    }
                )
                if len(relatorio_reports) >= relatorio_limit:
                    break
            else:
                relatorio_failures.append(
                    {
                        "documento": candidate,
                        "error": relatorio_result.get("error", {}),
                    }
                )

    report_data = {
        "processo": data.get("processo", {}),
        "executive_summary": process_context.get("summary"),
        "overview": {
            "documents_total": data.get("documents_total"),
            "folders_total": data.get("folders_total"),
            "signed_total": data.get("signed_total"),
            "unsigned_total": data.get("unsigned_total"),
            "process_kind_guess": process_context.get("process_kind_guess"),
            "preflight": data.get("preflight", {}),
            "selection": data.get("selection", {}),
            "read_summary": data.get("read_summary", {}),
        },
        "people_and_units": {
            "involved_military": process_context.get("involved_military", []),
            "involved_units": process_context.get("involved_units", []),
        },
        "timeline": {
            "mentioned_dates": process_context.get("mentioned_dates", []),
            "deadlines": process_context.get("deadlines", []),
        },
        "action_analysis": {
            "requires_response": process_context.get("requires_response"),
            "action_required": process_context.get("action_required"),
            "dominant_action_kind": process_context.get("dominant_action_kind"),
            "action_items": _process_action_items(base_result),
        },
        "documents": {
            "key_documents": process_context.get("key_documents", []),
            "documents_read": data.get("documents_read", []),
        },
        "relatorios": relatorio_reports,
        "relatorio_failures": relatorio_failures,
    }
    return _result(
        operation=operation,
        context=base_result["context"],
        resolved_ids=base_result["resolved_ids"],
        data=report_data,
        next_actions=[
            NextAction(action="process-summary", label="Gerar visão rápida do processo", params={"numero_ou_id": numero_ou_id}),
            NextAction(action="process-read", label="Ler contexto completo do processo", params={"numero_ou_id": numero_ou_id, "mode": "all"}),
        ],
        warnings=base_result.get("warnings", []),
    )


def document_read(client: Any, numero_ou_id: str, *, id_procedimento: str | None = None) -> dict[str, Any]:
    operation = "document-read"
    resolved_ids: dict[str, Any] = {}
    try:
        context = _context(client)
        navigation_mode = "quick-search-document" if id_procedimento is None else "direct-document-id"
        docs: list[TreeDocument] | None = None

        if id_procedimento is not None:
            id_documento, docs = _resolve_document_id_with_process(
                client,
                numero_ou_id,
                id_procedimento=id_procedimento,
            )
            id_procedimento_resolved = id_procedimento
            numero_documento = None if id_documento == numero_ou_id else numero_ou_id
        else:
            id_documento, id_procedimento_resolved, numero_documento = _resolve_document_ids(
                client,
                numero_ou_id,
                id_procedimento=id_procedimento,
            )
            docs = client.get_full_document_tree(id_procedimento_resolved)
        preflight, unit_guard = _process_unit_preflight(client, id_procedimento_resolved)
        with unit_guard as switched_to:
            if switched_to:
                preflight["switched"] = True
                preflight["switched_to"] = switched_to
                context = _context(client)
                docs = client.get_full_document_tree(id_procedimento_resolved)
            process = _find_process_metadata(client, id_procedimento_resolved, None)
            doc_payload = _document_read_core(
                client,
                context=context,
                id_documento=id_documento,
                id_procedimento=id_procedimento_resolved,
                numero_documento=numero_documento,
                docs=docs,
                process=process,
                navigation_mode=navigation_mode,
            )
            resolved_ids = doc_payload["resolved_ids"]

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={**doc_payload["data"], "preflight": preflight},
            next_actions=[
                NextAction(
                    action="process-open",
                    label="Abrir processo relacionado",
                    params={"numero_ou_id": id_procedimento_resolved},
                ),
                NextAction(
                    action="process-read",
                    label="Ler contexto estrutural do processo",
                    params={"numero_ou_id": id_procedimento_resolved},
                ),
            ],
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def relatorio_read(client: Any, numero_ou_id: str, *, id_procedimento: str | None = None) -> dict[str, Any]:
    operation = "relatorio-read"
    resolved_ids: dict[str, Any] = {}
    try:
        context = _context(client)
        if id_procedimento is not None:
            id_documento, docs = _resolve_document_id_with_process(
                client,
                numero_ou_id,
                id_procedimento=id_procedimento,
            )
            id_procedimento_resolved = id_procedimento
            numero_documento = None if id_documento == numero_ou_id else numero_ou_id
        else:
            id_documento, id_procedimento_resolved, numero_documento = _resolve_document_ids(
                client,
                numero_ou_id,
                id_procedimento=id_procedimento,
            )
            docs = client.get_full_document_tree(id_procedimento_resolved)
        preflight, unit_guard = _process_unit_preflight(client, id_procedimento_resolved)
        with unit_guard as switched_to:
            if switched_to:
                preflight["switched"] = True
                preflight["switched_to"] = switched_to
                context = _context(client)
                docs = client.get_full_document_tree(id_procedimento_resolved)
            doc_meta = next((doc for doc in docs if doc.id_documento == id_documento), None)

            numero_documento_resolvido = (
                doc_meta.sei_number if doc_meta and doc_meta.sei_number else numero_documento or numero_ou_id
            )
            resolved_ids = {
                "id_documento": id_documento,
                "id_procedimento": id_procedimento_resolved,
                "numero_documento": numero_documento_resolvido,
            }

            metadata = _tree_document(doc_meta) if doc_meta else {
                "id_documento": id_documento,
                "sei_number": numero_documento_resolvido,
            }
            parsing_strategy = "structured_editor"
            extraction_method: str | None = "read_relatorio_editor"
            try:
                if doc_meta and doc_meta.tipo.lower() in {"pdf", "documento", "externo"}:
                    raise ParseError(
                        "Documento exige leitura textual canônica antes do parser estruturado.",
                        details={"tipo": doc_meta.tipo, "id_documento": id_documento},
                    )
                relatorio = client.read_relatorio(id_documento, id_procedimento_resolved)
            except Exception:
                try:
                    html = client.view_document_html(id_documento, id_procedimento_resolved)
                    relatorio = parse_relatorio(html)
                    parsing_strategy = "structured_html_view"
                    extraction_method = "view_document_html"
                except Exception:
                    doc_payload = _document_read_core(
                        client,
                        context=context,
                        id_documento=id_documento,
                        id_procedimento=id_procedimento_resolved,
                        numero_documento=numero_documento_resolvido,
                        docs=docs,
                        process=None,
                        navigation_mode="direct-document-id",
                    )
                    extraction_method = doc_payload["data"]["extraction_method"]
                    relatorio = _fallback_relatorio_from_text(doc_payload["data"]["text"])
                    parsing_strategy = "text_fallback"

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "documento": metadata,
                "preflight": preflight,
                "signature_status": _signature_status(metadata),
                "parsing_strategy": parsing_strategy,
                "extraction_method": extraction_method,
                "relatorio": relatorio_to_dict(relatorio),
                "summary": summarize_relatorio(relatorio),
            },
            next_actions=[
                NextAction(
                    action="process-read",
                    label="Ler contexto do processo",
                    params={"numero_ou_id": id_procedimento_resolved},
                )
            ],
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def block_review(client: Any, block_numero: str) -> dict[str, Any]:
    result = signature_block_read(client, block_numero)
    result["operation"] = "block-review"
    return result


def signature_block_list(client: Any) -> dict[str, Any]:
    operation = "signature-block-list"
    try:
        context = _context(client)
        blocks = client.list_blocks()
        pending_documents_total = 0
        signed_documents_total = 0
        states: Counter[str] = Counter()
        previews: list[dict[str, Any]] = []

        for block in blocks:
            previews.append(_block_preview(block))
            states[block.estado or "desconhecido"] += 1
            try:
                documents = client.get_block_documents(block.numero)
            except Exception:
                documents = []
            signed = sum(1 for doc in documents if doc.assinado)
            signed_documents_total += signed
            pending_documents_total += len(documents) - signed

        next_actions: list[NextAction] = []
        if blocks:
            next_actions.append(
                NextAction(
                    action="signature-block-read",
                    label="Abrir primeiro bloco listado",
                    params={"block_numero": blocks[0].numero},
                )
            )

        return _result(
            operation=operation,
            context=context,
            data={
                "blocks_total": len(blocks),
                "signed_documents_total": signed_documents_total,
                "pending_documents_total": pending_documents_total,
                "states": dict(states),
                "blocks": previews,
            },
            next_actions=next_actions,
            warnings=[] if blocks else ["Nenhum bloco de assinatura foi encontrado na unidade atual."],
        )
    except Exception as exc:
        return _error_result(operation=operation, exc=exc)


def signature_block_read(client: Any, block_numero: str) -> dict[str, Any]:
    operation = "signature-block-read"
    resolved_ids = {"block_numero": block_numero}
    try:
        context = _context(client)
        blocks = client.list_blocks()
        block = next((item for item in blocks if item.numero == block_numero), None)
        if not block:
            raise BlockNotFoundError(
                f"Bloco {block_numero} nao encontrado na unidade atual.",
                details={"block_numero": block_numero},
            )

        documents = client.get_block_documents(block_numero)
        signed_total = sum(1 for doc in documents if doc.assinado)
        pending_documents = [doc for doc in documents if not doc.assinado]
        processos = sorted({doc.processo for doc in documents if doc.processo})

        next_actions: list[NextAction] = []
        if processos:
            next_actions.append(
                NextAction(
                    action="process-open",
                    label="Abrir processo relacionado ao bloco",
                    params={"numero_ou_id": processos[0]},
                )
            )
        if pending_documents:
            next_actions.append(
                NextAction(
                    action="signature-block-review",
                    label="Revisar pendencias deste bloco",
                    params={"block_numero": block_numero},
                )
            )

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "bloco": _block_preview(block),
                "documents_total": len(documents),
                "signed_total": signed_total,
                "pending_total": len(documents) - signed_total,
                "processos_total": len(processos),
                "processos": processos,
                "documents": [_block_document(doc) for doc in documents],
            },
            next_actions=next_actions,
            warnings=[] if documents else ["Nenhum documento foi encontrado no bloco informado."],
        )
    except Exception as exc:
        return _error_result(
            operation=operation,
            context=locals().get("context"),
            resolved_ids=resolved_ids,
            exc=exc,
        )


def signature_block_review(client: Any, block_numero: str) -> dict[str, Any]:
    operation = "signature-block-review"
    base = signature_block_read(client, block_numero)
    if not base.get("ok"):
        base["operation"] = operation
        return base

    documents = base["data"].get("documents", [])
    pending_documents = [doc for doc in documents if not doc.get("assinado")]
    signed_documents = [doc for doc in documents if doc.get("assinado")]
    processos = base["data"].get("processos", [])
    warnings = list(base.get("warnings", []))
    if not pending_documents:
        warnings.append("Bloco sem documentos pendentes de assinatura.")

    next_actions: list[NextAction] = []
    if pending_documents:
        first_pending = pending_documents[0]
        next_actions.append(
            NextAction(
                action="document-read",
                label="Ler primeiro documento pendente do bloco",
                params={
                    "numero_ou_id": first_pending.get("documento_id"),
                    "process_id": processos[0] if processos else None,
                },
            )
        )
    if processos:
        next_actions.append(
            NextAction(
                action="process-open",
                label="Abrir primeiro processo relacionado",
                params={"numero_ou_id": processos[0]},
            )
        )

    return _result(
        operation=operation,
        context=base["context"],
        resolved_ids=base["resolved_ids"],
        data={
            **base["data"],
            "pending_documents": pending_documents,
            "signed_documents": signed_documents,
            "ready_to_sign": bool(pending_documents),
            "signable_document_ids": [doc.get("documento_id") for doc in pending_documents if doc.get("documento_id")],
        },
        next_actions=next_actions,
        warnings=warnings,
    )
