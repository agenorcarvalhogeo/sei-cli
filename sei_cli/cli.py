from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from sei_cli.client import SEIClient
from sei_cli.models import Block, Process, SystemStatus

console = Console()


def _emit(data: Any, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _print_status(status: SystemStatus) -> None:
    table = Table(title="Status da Sessão")
    table.add_column("Campo")
    table.add_column("Valor")
    table.add_row("Válida", "Sim" if status.valid else "Não")
    table.add_row("Unidade", status.unidade_sigla or "-")
    table.add_row("Descrição", status.unidade_descricao or "-")
    table.add_row("Usuário", status.usuario or "-")
    table.add_row("Último acesso", status.ultimo_acesso or "-")
    console.print(table)


def _table_processes(title: str, items: list[Process]) -> None:
    table = Table(title=title)
    table.add_column("Nº")
    table.add_column("Tipo")
    table.add_column("Especificação")
    table.add_column("Novo")
    table.add_column("Atribuído")

    for item in items:
        table.add_row(
            item.numero,
            item.tipo,
            item.especificacao,
            "Sim" if item.novo else "Não",
            item.atribuido or "-",
        )

    console.print(table)


def _table_blocks(items: list[Block]) -> None:
    table = Table(title="Blocos")
    table.add_column("ID")
    table.add_column("Tipo")
    table.add_column("Descrição")
    table.add_column("Estado")
    for item in items:
        table.add_row(item.id, item.tipo, item.descricao, item.estado or "-")
    console.print(table)


@click.group()
def cli() -> None:
    """CLI read-only para o SEI-RN."""


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def login(as_json: bool) -> None:
    with SEIClient() as client:
        status = client.login()
    if as_json:
        _emit(asdict(status), True)
        return
    _print_status(status)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def status(as_json: bool) -> None:
    with SEIClient() as client:
        data = client.status()
    if as_json:
        _emit(asdict(data), True)
        return
    _print_status(data)


@cli.command("processes")
@click.option("--unit", "unit", default=None, help="Filtra por unidade (troca unidade ativa)")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def processes_cmd(unit: str | None, as_json: bool) -> None:
    with SEIClient() as client:
        data = client.list_processes(unit=unit)
    if as_json:
        _emit({"recebidos": [asdict(x) for x in data.recebidos], "gerados": [asdict(x) for x in data.gerados]}, True)
        return
    _table_processes("Processos Recebidos", data.recebidos)
    _table_processes("Processos Gerados", data.gerados)


@cli.command("process")
@click.argument("numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def process_cmd(numero: str, as_json: bool) -> None:
    with SEIClient() as client:
        details = client.get_process(numero)
    if as_json:
        _emit(asdict(details), True)
        return

    table = Table(title=f"Processo {details.processo_numero}")
    table.add_column("Documento")
    table.add_column("Nome")
    for doc in details.documentos:
        table.add_row(doc.numero, doc.nome)
    console.print(table)


@cli.command("doc")
@click.argument("numero")
def doc_cmd(numero: str) -> None:
    with SEIClient() as client:
        content = client.get_document(numero)
    click.echo(content)


@cli.command("blocks")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def blocks_cmd(as_json: bool) -> None:
    with SEIClient() as client:
        blocks = client.list_blocks()
    if as_json:
        _emit([asdict(x) for x in blocks], True)
        return
    _table_blocks(blocks)


@cli.command("block")
@click.argument("block_id")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_cmd(block_id: str, as_json: bool) -> None:
    with SEIClient() as client:
        details = client.get_block(block_id)
    if as_json:
        _emit(asdict(details), True)
        return

    table = Table(title=f"Bloco {details.block_id}")
    table.add_column("Documento")
    table.add_column("Nome")
    for doc in details.documentos:
        table.add_row(doc.numero, doc.nome)
    console.print(table)


@cli.command("search")
@click.argument("query")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def search_cmd(query: str, as_json: bool) -> None:
    with SEIClient() as client:
        result = client.search(query)

    if as_json:
        _emit({"query": result.query, "processos": [asdict(x) for x in result.processos]}, True)
        return

    _table_processes(f"Pesquisa: {query}", result.processos)


@cli.command("units")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def units_cmd(as_json: bool) -> None:
    with SEIClient() as client:
        units = client.list_units()

    if as_json:
        _emit([asdict(x) for x in units], True)
        return

    table = Table(title="Unidades")
    table.add_column("Sigla")
    table.add_column("Descrição")
    for unit in units:
        table.add_row(unit.sigla, unit.descricao)
    console.print(table)


@cli.command("switch")
@click.argument("sigla")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def switch_cmd(sigla: str, as_json: bool) -> None:
    with SEIClient() as client:
        status = client.switch_unit(sigla)

    if as_json:
        _emit(asdict(status), True)
        return
    _print_status(status)


if __name__ == "__main__":
    cli()
