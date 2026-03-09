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
    table.add_column("Número")
    table.add_column("Estado")
    table.add_column("Descrição")
    table.add_column("Origem")
    table.add_column("Destino")
    for item in items:
        table.add_row(
            item.numero,
            item.estado or "-",
            item.descricao,
            item.unidade_origem,
            item.unidade_destino,
        )
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


@cli.command("goto")
@click.argument("numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
@click.option("--read", "do_read", is_flag=True, help="Ler conteúdo do documento (se for relatório)")
@click.option("--unit", default=None, help="Unidade SEI (sigla parcial)")
def goto_cmd(numero: str, as_json: bool, do_read: bool, unit: str | None) -> None:
    """Navegar direto para um documento ou processo pelo número SEI.

    Aceita número de documento SEI (ex: 39860248) ou número de processo
    (ex: 08810108.001215/2025-10). Usa a pesquisa rápida do SEI.
    """
    with SEIClient() as client:
        if unit:
            client.switch_unit(unit)

        # Detect if it's a process number (has dots/slashes) or document number
        is_process = "." in numero or "/" in numero

        if is_process:
            html = client.search(numero)
            has_tree = "ifrArvore" in html
            if has_tree:
                import re
                id_proc_m = re.search(r"id_procedimento=(\d+)", html)
                id_proc = id_proc_m.group(1) if id_proc_m else "?"
                if as_json:
                    docs = client.get_process_documents(id_proc) if id_proc != "?" else []
                    _emit({
                        "tipo": "processo",
                        "numero": numero,
                        "id_procedimento": id_proc,
                        "documentos": [{"id": d.id_documento, "nome": d.nome, "tipo": d.tipo} for d in docs],
                    }, True)
                else:
                    console.print(f"[green]✅ Processo {numero}[/green] (id_procedimento={id_proc})")
                    if id_proc != "?":
                        docs = client.get_process_documents(id_proc)
                        table = Table(title=f"Documentos ({len(docs)})")
                        table.add_column("ID")
                        table.add_column("Nome")
                        table.add_column("Tipo")
                        for d in docs:
                            table.add_row(d.id_documento, d.nome, d.tipo)
                        console.print(table)
            else:
                console.print(f"[red]❌ Processo {numero} não encontrado[/red]")
        else:
            result = client.search_document(numero)
            if result:
                id_doc, id_proc = result
                if as_json:
                    out = {"tipo": "documento", "numero_sei": numero, "id_documento": id_doc, "id_procedimento": id_proc}
                    if do_read:
                        try:
                            relatorio = client.read_relatorio(id_doc, id_proc)
                            out["conteudo"] = str(relatorio) if relatorio else None
                        except Exception:
                            out["conteudo"] = None
                    _emit(out, True)
                else:
                    console.print(f"[green]✅ Documento SEI {numero}[/green]")
                    console.print(f"  id_documento: {id_doc}")
                    console.print(f"  id_procedimento: {id_proc}")
                    if do_read:
                        try:
                            relatorio = client.read_relatorio(id_doc, id_proc)
                            if relatorio:
                                console.print(f"\n[bold]Conteúdo:[/bold]")
                                console.print(str(relatorio))
                            else:
                                console.print("[yellow]Sem conteúdo legível[/yellow]")
                        except Exception as e:
                            console.print(f"[red]Erro ao ler: {e}[/red]")
            else:
                console.print(f"[red]❌ Documento {numero} não encontrado[/red]")


@cli.command("encaminhar")
@click.argument("processo")
@click.argument("destino")
@click.option("--unit", default=None, help="Unidade SEI atual (trocar antes de encaminhar)")
@click.option("--fechar", is_flag=True, help="Fechar processo na unidade atual após envio")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def encaminhar_cmd(processo: str, destino: str, unit: str | None, fechar: bool, as_json: bool) -> None:
    """Encaminhar processo para outra unidade.

    PROCESSO: id_procedimento ou número do processo (ex: 08810254.000081/2026-17)
    DESTINO: sigla ou nome parcial da unidade destino (ex: "3ºGBM", "PABM APODI")
    """
    with SEIClient() as client:
        if unit:
            client.switch_unit(unit)

        # Se é número de processo, resolver pra id_procedimento via goto/search
        id_proc = processo
        if "." in processo or "/" in processo:
            import re
            html = client.search(processo)
            m = re.search(r"id_procedimento=(\d+)", html)
            if m:
                id_proc = m.group(1)
            else:
                console.print(f"[red]❌ Processo {processo} não encontrado[/red]")
                return

        manter_aberto = not fechar
        try:
            ok = client.enviar_processo(id_proc, destino, manter_aberto=manter_aberto)
            if ok:
                if as_json:
                    _emit({"status": "ok", "processo": processo, "destino": destino, "mantido_aberto": manter_aberto}, True)
                else:
                    console.print(f"[green]✅ Processo {processo} encaminhado para {destino}[/green]")
                    if manter_aberto:
                        console.print("  (mantido aberto na unidade atual)")
            else:
                console.print(f"[red]❌ Falha ao encaminhar processo[/red]")
        except RuntimeError as e:
            console.print(f"[red]❌ {e}[/red]")


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


@cli.command("block-create")
@click.argument("descricao")
@click.argument("unidade_destino")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_create_cmd(descricao: str, unidade_destino: str, as_json: bool) -> None:
    """Create a new bloco de assinatura.

    UNIDADE_DESTINO can be a known alias (e.g. 'CMDO 3GBM') or a numeric SEI unit ID.
    Known aliases: CMDO 3GBM, CMDO PABM APODI, SEC 1SGB/3GBM, SEC 2SGB/3GBM,
    SECRETARIA 3GBM, OP 3GBM, LOGISTICA 3GBM, PAD-PDF, DAT-1CAT.
    """
    # Resolve alias or use as-is
    unit_id = SEIClient.UNIT_IDS.get(unidade_destino.upper(), None)
    if not unit_id:
        # Try case-insensitive fuzzy match
        for alias, uid in SEIClient.UNIT_IDS.items():
            if unidade_destino.upper().replace("º", "").replace("°", "") in alias.replace("º", ""):
                unit_id = uid
                break
    if not unit_id:
        if unidade_destino.isdigit():
            unit_id = unidade_destino
        else:
            click.echo(f"❌ Unidade desconhecida: {unidade_destino}")
            click.echo(f"   Aliases válidos: {', '.join(SEIClient.UNIT_IDS.keys())}")
            raise SystemExit(1)

    with SEIClient() as client:
        client.login()
        numero = client.create_block(descricao, unit_id)

    result = {"ok": True, "numero": numero, "descricao": descricao, "unidade_id": unit_id}
    if as_json:
        _emit(result, True)
        return
    click.echo(f"✅ Bloco {numero} criado — {descricao}")


@cli.command("block-add")
@click.argument("id_procedimento")
@click.argument("id_documento")
@click.argument("block_numero")
@click.option("--disponibilizar", is_flag=True, help="Incluir E disponibilizar no mesmo passo")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_add_cmd(
    id_procedimento: str,
    id_documento: str,
    block_numero: str,
    disponibilizar: bool,
    as_json: bool,
) -> None:
    """Include a document in a bloco de assinatura."""
    with SEIClient() as client:
        client.login()
        result = client.add_document_to_block(
            id_procedimento, id_documento, block_numero,
            disponibilizar=disponibilizar,
        )
    if as_json:
        _emit(result, True)
        return
    icon = "✅" if result["ok"] else "❌"
    click.echo(f"{icon} {result['message']}")


@cli.command("block-disponibilizar")
@click.argument("block_numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_disponibilizar_cmd(block_numero: str, as_json: bool) -> None:
    """Disponibilizar (make available) a bloco de assinatura."""
    with SEIClient() as client:
        client.login()
        result = client.disponibilizar_block(block_numero)
    if as_json:
        _emit(result, True)
        return
    icon = "✅" if result["ok"] else "❌"
    click.echo(f"{icon} {result['message']}")


@cli.command("block-cancelar")
@click.argument("block_numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_cancelar_cmd(block_numero: str, as_json: bool) -> None:
    """Cancel disponibilização of a bloco de assinatura."""
    with SEIClient() as client:
        client.login()
        result = client.cancelar_disponibilizacao_block(block_numero)
    if as_json:
        _emit(result, True)
        return
    icon = "✅" if result["ok"] else "❌"
    click.echo(f"{icon} {result['message']}")


@cli.command("block-delete")
@click.argument("block_numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_delete_cmd(block_numero: str, as_json: bool) -> None:
    """Delete an empty bloco de assinatura."""
    with SEIClient() as client:
        client.login()
        try:
            client.delete_block(block_numero)
        except RuntimeError as e:
            if as_json:
                _emit({"ok": False, "message": str(e)}, True)
            else:
                click.echo(f"❌ {e}")
            raise SystemExit(1)
    if as_json:
        _emit({"ok": True, "message": f"Bloco {block_numero} excluído"}, True)
        return
    click.echo(f"✅ Bloco {block_numero} excluído")


@cli.command("block-devolver")
@click.argument("block_numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_devolver_cmd(block_numero: str, as_json: bool) -> None:
    """Devolver (return) a received bloco de assinatura to the sender."""
    with SEIClient() as client:
        client.login()
        result = client.devolver_block(block_numero)
    if as_json:
        _emit(result, True)
        return
    icon = "✅" if result["ok"] else "❌"
    click.echo(f"{icon} {result['message']}")


@cli.command("block-remove")
@click.argument("id_documento")
@click.argument("block_numero")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
def block_remove_cmd(id_documento: str, block_numero: str, as_json: bool) -> None:
    """Remove a document from a bloco de assinatura."""
    with SEIClient() as client:
        client.login()
        result = client.remove_document_from_block(id_documento, block_numero)
    if as_json:
        _emit(result, True)
        return
    icon = "✅" if result["ok"] else "❌"
    click.echo(f"{icon} {result['message']}")


@cli.command("read-doc")
@click.argument("id_documento")
@click.argument("id_procedimento")
def read_doc_cmd(id_documento: str, id_procedimento: str) -> None:
    """Read a document's text content."""
    with SEIClient() as client:
        client.login()
        text = client.read_document(id_documento, id_procedimento)
    click.echo(text)


@cli.command("read-relatorio")
@click.argument("id_documento")
@click.argument("id_procedimento")
@click.option("--unit", default=None, help="Switch to unit before reading (e.g. 'OP 3')")
@click.option("--json", "as_json", is_flag=True, help="Saída JSON")
@click.option("--summary", is_flag=True, help="Print human-readable summary")
def read_relatorio_cmd(
    id_documento: str,
    id_procedimento: str,
    unit: str | None,
    as_json: bool,
    summary: bool,
) -> None:
    """Parse a Relatório de Serviço Operacional into structured data."""
    from sei_cli.relatorio_parser import summarize as _summarize, to_dict

    with SEIClient() as client:
        client.login()
        if unit:
            client.switch_unit(unit)
        r = client.read_relatorio(id_documento, id_procedimento)

    if as_json:
        click.echo(json.dumps(to_dict(r), ensure_ascii=False, indent=2))
        return

    if summary or not as_json:
        click.echo(_summarize(r))
        return


if __name__ == "__main__":
    cli()
