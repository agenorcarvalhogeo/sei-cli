from __future__ import annotations

import json

from click.testing import CliRunner

from sei_cli.cli import cli
from sei_cli.operations import workflow_next, workflow_show


def test_workflow_show_reaprazamento() -> None:
    result = workflow_show("reaprazamento")

    assert result["ok"] is True
    assert result["operation"] == "workflow-show"
    assert result["data"]["workflow"]["slug"] == "reaprazamento"
    assert result["data"]["workflow"]["steps_total"] == 9
    assert result["data"]["steps"][0]["step_id"] == "01-escolher-cenario"
    assert result["data"]["steps"][2]["future_operation"] == "document-create-preview"
    assert result["data"]["steps"][3]["canonical_operation"] == "document-read"
    assert result["data"]["steps"][5]["canonical_operation"] == "process-read"
    assert result["data"]["steps"][6]["canonical_operation"] == "document-read"


def test_workflow_next_returns_first_step() -> None:
    result = workflow_next("reaprazamento")

    assert result["ok"] is True
    assert result["data"]["current_step"] is None
    assert result["data"]["next_step"]["step_id"] == "01-escolher-cenario"
    assert result["data"]["transition_reason"] == "Primeira etapa do workflow."


def test_workflow_next_requires_initial_decision() -> None:
    result = workflow_next("reaprazamento", current_step="01-escolher-cenario")

    assert result["ok"] is True
    assert result["data"]["decision_required"] is True
    assert result["data"]["next_step"] is None
    assert result["data"]["available_decisions"] == ["subordinado_solicita", "vou_solicitar"]


def test_workflow_next_self_request_branch() -> None:
    result = workflow_next("reaprazamento", current_step="01-escolher-cenario", decision="vou_solicitar")

    assert result["ok"] is True
    assert result["data"]["decision_required"] is False
    assert result["data"]["next_step"]["step_id"] == "02-auto-criar-processo"
    assert "mapeado diretamente para a etapa seguinte" in result["data"]["transition_reason"]


def test_workflow_next_subordinate_branch() -> None:
    result = workflow_next("reaprazamento", current_step="01-escolher-cenario", decision="subordinado_solicita")

    assert result["ok"] is True
    assert result["data"]["decision_required"] is False
    assert result["data"]["next_step"]["step_id"] == "06-analisar-processo-recebido"


def test_workflow_next_follows_step_id_destination() -> None:
    result = workflow_next("reaprazamento", current_step="02-auto-criar-processo")

    assert result["ok"] is True
    assert result["data"]["next_step"]["step_id"] == "03-auto-criar-solicitacao"
    assert "mapeado diretamente para a etapa seguinte" in result["data"]["transition_reason"]


def test_workflow_next_terminal_step() -> None:
    result = workflow_next("reaprazamento", current_step="09-encaminhar-secretarias")

    assert result["ok"] is True
    assert result["data"]["next_step"] is None
    assert result["data"]["transition_reason"] == "Etapa terminal do workflow."


def test_workflow_next_self_request_reads_document_before_forwarding() -> None:
    result = workflow_next("reaprazamento", current_step="03-auto-criar-solicitacao")

    assert result["ok"] is True
    assert result["data"]["next_step"]["step_id"] == "04-auto-ler-solicitacao"
    assert result["next_actions"][0]["action"] == "document-read"


def test_workflow_next_subordinate_reads_document_before_dispatching() -> None:
    result = workflow_next("reaprazamento", current_step="06-analisar-processo-recebido")

    assert result["ok"] is True
    assert result["data"]["next_step"]["step_id"] == "07-ler-solicitacao-recebida"
    assert result["next_actions"][0]["action"] == "document-read"


def test_workflow_show_cli_json() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["workflow-show", "reaprazamento", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["workflow"]["slug"] == "reaprazamento"


def test_workflow_next_cli_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow-next", "reaprazamento", "--current-step", "01-escolher-cenario", "--decision", "vou_solicitar", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["data"]["next_step"]["step_id"] == "02-auto-criar-processo"


def test_workflow_next_invalid_decision_exit_code() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["workflow-next", "reaprazamento", "--current-step", "01-escolher-cenario", "--decision", "talvez", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "workflow_violation"
