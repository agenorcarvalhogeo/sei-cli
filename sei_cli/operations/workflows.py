from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import NextAction, OperationResult
from .errors import WorkflowViolationError, error_from_exception

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"

ACTION_HINTS: dict[str, dict[str, Any]] = {
    "definir_cenario": {
        "canonical_operation": None,
        "supported_now": False,
        "preflight_operations": [],
        "notes": "Etapa lógica de triagem para escolher o ramo correto do workflow.",
    },
    "consultar_caixa": {
        "canonical_operation": "inbox-snapshot",
        "supported_now": True,
        "preflight_operations": [],
        "notes": "Leitura canônica da caixa atual.",
    },
    "abrir_processo": {
        "canonical_operation": "process-open",
        "supported_now": True,
        "preflight_operations": [],
        "notes": "Abre o processo e lista documentos relacionados.",
    },
    "ler_processo": {
        "canonical_operation": "process-read",
        "supported_now": True,
        "preflight_operations": [],
        "notes": "Leitura contextual do processo.",
    },
    "ler_documento": {
        "canonical_operation": "document-read",
        "supported_now": True,
        "preflight_operations": ["process-open"],
        "notes": "Leitura textual do documento.",
    },
    "ler_relatorio": {
        "canonical_operation": "relatorio-read",
        "supported_now": True,
        "preflight_operations": ["process-read"],
        "notes": "Leitura estruturada de relatório operacional.",
    },
    "revisar_bloco": {
        "canonical_operation": "block-review",
        "supported_now": True,
        "preflight_operations": ["inbox-snapshot"],
        "notes": "Revisão de bloco e pendências associadas.",
    },
    "criar_processo": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "process-create-preview",
        "preflight_operations": [],
        "notes": "Etapa de escrita ainda não promovida para operação canônica.",
    },
    "criar_documento": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "document-create-preview",
        "preflight_operations": ["process-read"],
        "notes": "Criação guiada de documento ainda será promovida para operação canônica.",
    },
    "analisar_pedido": {
        "canonical_operation": "process-read",
        "supported_now": True,
        "preflight_operations": ["process-open"],
        "notes": "Leitura e análise contextual do processo recebido.",
    },
    "despachar": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "document-create-preview",
        "preflight_operations": ["process-read"],
        "notes": "A skill já descreve o fluxo de despacho; falta promover a etapa de escrita.",
    },
    "encaminhar": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "process-forward-preview",
        "preflight_operations": ["process-read"],
        "notes": "Encaminhamento existe no client bruto; falta promovê-lo para operação canônica.",
    },
    "acostar_autos": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "process-attach-records",
        "preflight_operations": ["process-read"],
        "notes": "Etapa guiada por workflow; operação canônica ainda pendente.",
    },
    "aguardar_manifestacoes": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "workflow-await-confirmations",
        "preflight_operations": [],
        "notes": "Etapa de acompanhamento humano; usada para explicitar dependências externas antes do fechamento.",
    },
    "publicar": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "document-create-preview",
        "preflight_operations": ["process-read"],
        "notes": "Publicação ainda depende de futura superfície de escrita.",
    },
    "ciencia": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "document-notice-confirm",
        "preflight_operations": ["process-read"],
        "notes": "Já existe no client bruto; ainda não foi promovido para operação canônica.",
    },
    "arquivar_e_concluir": {
        "canonical_operation": None,
        "supported_now": False,
        "future_operation": "process-archive-close-confirm",
        "preflight_operations": ["process-read"],
        "notes": "Arquivamento em acompanhamento especial e conclusão ainda serão promovidos como escrita guiada.",
    },
}


@dataclass(slots=True)
class _YamlLine:
    indent: int
    text: str


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "step"


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item.strip()) for item in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _prepare_lines(text: str) -> list[_YamlLine]:
    lines: list[_YamlLine] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append(_YamlLine(indent=indent, text=raw.lstrip()))
    return lines


def _parse_block_scalar(lines: list[_YamlLine], index: int, parent_indent: int, style: str) -> tuple[str, int]:
    chunks: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line.indent <= parent_indent:
            break
        chunks.append(line.text.strip())
        index += 1
    if style == ">":
        return " ".join(chunk for chunk in chunks if chunk).strip(), index
    return "\n".join(chunks).strip(), index


def _parse_sequence(lines: list[_YamlLine], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        line = lines[index]
        if line.indent != indent or not line.text.startswith("- "):
            break

        item_text = line.text[2:].strip()
        index += 1

        if not item_text:
            if index < len(lines) and lines[index].indent > line.indent:
                if lines[index].text.startswith("- "):
                    value, index = _parse_sequence(lines, index, lines[index].indent)
                else:
                    value, index = _parse_mapping(lines, index, lines[index].indent)
                items.append(value)
            else:
                items.append(None)
            continue

        if ":" in item_text:
            key, _, remainder = item_text.partition(":")
            key = key.strip()
            remainder = remainder.strip()
            item: dict[str, Any] = {}

            if remainder in {">", "|"}:
                value, index = _parse_block_scalar(lines, index, line.indent, remainder)
                item[key] = value
            elif remainder:
                item[key] = _parse_scalar(remainder)
            else:
                if index < len(lines) and lines[index].indent > line.indent:
                    if lines[index].text.startswith("- "):
                        value, index = _parse_sequence(lines, index, lines[index].indent)
                    else:
                        value, index = _parse_mapping(lines, index, lines[index].indent)
                    item[key] = value
                else:
                    item[key] = None

            if index < len(lines) and lines[index].indent > line.indent:
                extra, index = _parse_mapping(lines, index, lines[index].indent)
                item.update(extra)

            items.append(item)
            continue

        items.append(_parse_scalar(item_text))

    return items, index


def _parse_mapping(lines: list[_YamlLine], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if line.indent < indent or line.text.startswith("- "):
            break
        if line.indent > indent:
            break

        key, sep, remainder = line.text.partition(":")
        if not sep:
            raise WorkflowViolationError(f"Linha YAML inválida: {line.text}")

        key = key.strip()
        remainder = remainder.strip()
        index += 1

        if remainder in {">", "|"}:
            value, index = _parse_block_scalar(lines, index, line.indent, remainder)
            mapping[key] = value
            continue

        if remainder:
            mapping[key] = _parse_scalar(remainder)
            continue

        if index < len(lines) and lines[index].indent > line.indent:
            if lines[index].text.startswith("- "):
                value, index = _parse_sequence(lines, index, lines[index].indent)
            else:
                value, index = _parse_mapping(lines, index, lines[index].indent)
            mapping[key] = value
        else:
            mapping[key] = None

    return mapping, index


def _load_yaml_subset(path: Path) -> dict[str, Any]:
    lines = _prepare_lines(path.read_text(encoding="utf-8"))
    if not lines:
        raise WorkflowViolationError(f"Workflow vazio: {path}")
    data, index = _parse_mapping(lines, 0, lines[0].indent)
    if index != len(lines):
        raise WorkflowViolationError(f"Workflow com conteúdo não processado: {path}")
    return data


def _workflow_files(orgao: str | None = None) -> list[Path]:
    if not WORKFLOWS_DIR.exists():
        return []

    if orgao:
        target_dir = WORKFLOWS_DIR / orgao.lower()
        return sorted(target_dir.glob("*.yaml"))

    return sorted(WORKFLOWS_DIR.glob("*/*.yaml"))


def _default_orgao() -> str | None:
    directories = sorted(path.name for path in WORKFLOWS_DIR.iterdir() if path.is_dir())
    if len(directories) == 1:
        return directories[0]
    return None


def _decorate_step(raw_step: dict[str, Any]) -> dict[str, Any]:
    order = int(raw_step.get("ordem", 0))
    action_key = str(raw_step.get("acao", "")).strip().lower()
    actor = str(raw_step.get("ator", "")).strip()
    hint = ACTION_HINTS.get(action_key, {})
    step_id = raw_step.get("id") or f"{order:02d}-{_slugify(action_key or actor or 'step')}"
    decisions = raw_step.get("decisao") if isinstance(raw_step.get("decisao"), dict) else {}

    return {
        "step_id": step_id,
        "order": order,
        "actor": actor,
        "actor_key": _slugify(actor),
        "role": raw_step.get("funcao"),
        "action": raw_step.get("acao"),
        "action_key": action_key,
        "document": raw_step.get("documento"),
        "description": raw_step.get("descricao"),
        "destination": raw_step.get("destino"),
        "terminal": bool(raw_step.get("fim")),
        "decision_paths": decisions,
        "canonical_operation": hint.get("canonical_operation"),
        "supported_now": bool(hint.get("supported_now", False)),
        "future_operation": hint.get("future_operation"),
        "preflight_operations": hint.get("preflight_operations", []),
        "notes": hint.get("notes"),
    }


def _normalize_workflow(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data.get("etapas"), list) or not data["etapas"]:
        raise WorkflowViolationError(f"Workflow sem etapas válidas: {path}")

    slug = _slugify(path.stem)
    steps = [_decorate_step(step) for step in data["etapas"] if isinstance(step, dict)]
    steps.sort(key=lambda item: item["order"])

    return {
        "slug": slug,
        "file": str(path),
        "nome": data.get("nome", path.stem),
        "orgao": str(data.get("orgao", path.parent.name)).lower(),
        "tipo_processo": data.get("tipo_processo"),
        "descricao": data.get("descricao"),
        "steps": steps,
    }


def _load_all_workflows(orgao: str | None = None) -> list[dict[str, Any]]:
    selected_orgao = orgao or _default_orgao()
    files = _workflow_files(selected_orgao)
    workflows: list[dict[str, Any]] = []
    for path in files:
        workflows.append(_normalize_workflow(path, _load_yaml_subset(path)))
    return workflows


def _resolve_workflow(ref: str, orgao: str | None = None) -> dict[str, Any]:
    workflows = _load_all_workflows(orgao)
    if not workflows:
        raise WorkflowViolationError("Nenhum workflow disponível para o órgão informado.")

    ref_key = _slugify(ref)
    for workflow in workflows:
        if workflow["slug"] == ref_key or _slugify(workflow["nome"]) == ref_key:
            return workflow

    available = ", ".join(sorted(workflow["slug"] for workflow in workflows))
    raise WorkflowViolationError(
        f"Workflow '{ref}' não encontrado.",
        details={"available_workflows": available},
    )


def _find_step(workflow: dict[str, Any], ref: str) -> dict[str, Any]:
    ref_key = _slugify(ref)
    for step in workflow["steps"]:
        if step["step_id"] == ref or step["step_id"] == ref_key:
            return step
        if str(step["order"]) == ref:
            return step
        if _slugify(step["action_key"]) == ref_key:
            return step
    raise WorkflowViolationError(
        f"Etapa '{ref}' não encontrada no workflow '{workflow['slug']}'.",
        details={"workflow": workflow["slug"]},
    )


def _find_next_by_destination(
    workflow: dict[str, Any],
    current_step: dict[str, Any],
    destination: str | None,
) -> tuple[dict[str, Any] | None, str]:
    later_steps = [step for step in workflow["steps"] if step["order"] > current_step["order"]]
    if not later_steps:
        return None, "Não há etapas posteriores."

    if destination:
        destination_key = _slugify(destination)
        for step in later_steps:
            if step["step_id"] == destination or _slugify(step["step_id"]) == destination_key:
                return step, f"Destino '{destination}' mapeado diretamente para a etapa seguinte."
            if step["actor_key"] == destination_key:
                return step, f"Destino '{destination}' mapeado para o ator da próxima etapa."

    return later_steps[0], "Seguindo a ordem declarada do workflow."


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


def workflow_show(ref: str, *, orgao: str | None = None) -> dict[str, Any]:
    operation = "workflow-show"
    try:
        workflow = _resolve_workflow(ref, orgao)
        context = {"orgao": workflow["orgao"]}
        resolved_ids = {"workflow": workflow["slug"], "workflow_file": workflow["file"]}

        supported_now = sum(1 for step in workflow["steps"] if step["supported_now"])
        warnings: list[str] = []
        if supported_now != len(workflow["steps"]):
            warnings.append("Nem todas as etapas já possuem operação canônica executável.")

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "workflow": {
                    "slug": workflow["slug"],
                    "nome": workflow["nome"],
                    "orgao": workflow["orgao"],
                    "tipo_processo": workflow.get("tipo_processo"),
                    "descricao": workflow.get("descricao"),
                    "steps_total": len(workflow["steps"]),
                    "supported_steps_total": supported_now,
                },
                "steps": workflow["steps"],
            },
            next_actions=[
                NextAction(
                    action="workflow-next",
                    label="Obter a próxima etapa do workflow",
                    params={"workflow": workflow["slug"]},
                )
            ],
            warnings=warnings,
        )
    except Exception as exc:
        return _error_result(operation=operation, context={"orgao": orgao}, exc=exc)


def workflow_next(
    ref: str,
    *,
    current_step: str | None = None,
    decision: str | None = None,
    orgao: str | None = None,
) -> dict[str, Any]:
    operation = "workflow-next"
    try:
        workflow = _resolve_workflow(ref, orgao)
        context = {"orgao": workflow["orgao"]}
        resolved_ids = {"workflow": workflow["slug"], "workflow_file": workflow["file"]}

        if current_step is None:
            next_step = workflow["steps"][0]
            return _result(
                operation=operation,
                context=context,
                resolved_ids=resolved_ids,
                data={
                    "workflow": {
                        "slug": workflow["slug"],
                        "nome": workflow["nome"],
                    },
                    "current_step": None,
                    "next_step": next_step,
                    "decision_required": False,
                    "available_decisions": [],
                    "transition_reason": "Primeira etapa do workflow.",
                },
                next_actions=_step_actions(next_step),
            )

        current = _find_step(workflow, current_step)
        decision_paths = current.get("decision_paths") if isinstance(current.get("decision_paths"), dict) else {}

        if current["terminal"]:
            return _result(
                operation=operation,
                context=context,
                resolved_ids=resolved_ids,
                data={
                    "workflow": {
                        "slug": workflow["slug"],
                        "nome": workflow["nome"],
                    },
                    "current_step": current,
                    "next_step": None,
                    "decision_required": False,
                    "available_decisions": [],
                    "transition_reason": "Etapa terminal do workflow.",
                },
            )

        if decision_paths and not decision:
            return _result(
                operation=operation,
                context=context,
                resolved_ids=resolved_ids,
                data={
                    "workflow": {
                        "slug": workflow["slug"],
                        "nome": workflow["nome"],
                    },
                    "current_step": current,
                    "next_step": None,
                    "decision_required": True,
                    "available_decisions": sorted(decision_paths.keys()),
                    "transition_reason": "A etapa atual depende de decisão para definir a próxima transição.",
                },
                next_actions=[
                    NextAction(
                        action="workflow-next",
                        label=f"Seguir decisão '{choice}'",
                        params={
                            "workflow": workflow["slug"],
                            "current_step": current["step_id"],
                            "decision": choice,
                        },
                    )
                    for choice in sorted(decision_paths.keys())
                ],
            )

        destination: str | None = current.get("destination")
        transition_reason = "Seguindo a ordem declarada do workflow."
        warnings: list[str] = []

        if decision_paths:
            branch = decision_paths.get(str(decision))
            if not isinstance(branch, dict):
                raise WorkflowViolationError(
                    f"Decisão '{decision}' inválida para a etapa '{current['step_id']}'.",
                    details={"available_decisions": sorted(decision_paths.keys())},
                )
            destination = branch.get("destino")
            transition_reason = f"Ramo de decisão '{decision}' selecionado."
            if branch.get("notificar"):
                warnings.append("A decisão selecionada prevê notificação adicional.")

        next_step, resolution_reason = _find_next_by_destination(workflow, current, destination)
        if next_step is None:
            return _result(
                operation=operation,
                context=context,
                resolved_ids=resolved_ids,
                data={
                    "workflow": {
                        "slug": workflow["slug"],
                        "nome": workflow["nome"],
                    },
                    "current_step": current,
                    "next_step": None,
                    "decision_required": False,
                    "available_decisions": sorted(decision_paths.keys()) if decision_paths else [],
                    "transition_reason": resolution_reason,
                },
                warnings=warnings,
            )

        return _result(
            operation=operation,
            context=context,
            resolved_ids=resolved_ids,
            data={
                "workflow": {
                    "slug": workflow["slug"],
                    "nome": workflow["nome"],
                },
                "current_step": current,
                "next_step": next_step,
                "decision_required": False,
                "available_decisions": sorted(decision_paths.keys()) if decision_paths else [],
                "transition_reason": f"{transition_reason} {resolution_reason}".strip(),
            },
            next_actions=_step_actions(next_step),
            warnings=warnings,
        )
    except Exception as exc:
        return _error_result(operation=operation, context={"orgao": orgao}, exc=exc)


def _step_actions(step: dict[str, Any]) -> list[NextAction]:
    actions: list[NextAction] = []
    if step.get("canonical_operation"):
        actions.append(
            NextAction(
                action=step["canonical_operation"],
                label="Executar operação canônica da etapa",
                params={"step_id": step["step_id"]},
            )
        )
    if step.get("future_operation"):
        actions.append(
            NextAction(
                action=step["future_operation"],
                label="Operação planejada para esta etapa",
                params={"step_id": step["step_id"]},
            )
        )
    return actions
