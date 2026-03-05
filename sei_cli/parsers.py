from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from lxml import html

from sei_cli.models import Block, Document, LoginForm, Process, ProcessDetails, ProcessList, SystemStatus, Unit


@dataclass(slots=True)
class ParsedForm:
    action: str


def _tree(content: str) -> html.HtmlElement:
    return html.fromstring(content)


def _norm(text: str | None) -> str:
    return (text or "").replace("\xa0", " ").strip()


def _extract_id_procedimento(link: str) -> str | None:
    parsed = urlparse(link)
    values = parse_qs(parsed.query).get("id_procedimento")
    if not values:
        return None
    return values[0]


def parse_login_form(content: str, current_url: str) -> LoginForm:
    page = _tree(content)
    form = page.xpath("//form[@id='frmLogin']")
    if not form:
        raise ValueError("Formulário de login não encontrado")
    action = form[0].attrib.get("action", "")
    return LoginForm(action=urljoin(current_url, action))


def parse_system_status(content: str) -> SystemStatus:
    page = _tree(content)
    valid = bool(page.xpath("//div[@id='divInfraBarraLocalizacao'][contains(normalize-space(.), 'Controle de Processos')]") or page.xpath("//title[contains(., 'Controle de Processos')]"))

    unidade_links = page.xpath("//a[@id='lnkInfraUnidade']")
    unidade_sigla = _norm(unidade_links[0].text_content()) if unidade_links else None
    unidade_desc = _norm(unidade_links[0].attrib.get("title")) if unidade_links else None

    usuario_links = page.xpath("//a[@id='lnkUsuarioSistema']")
    usuario = _norm(usuario_links[0].attrib.get("title")) if usuario_links else None

    ultimo = page.xpath("//div[@id='divInfraBarraAcesso']//a/text()")
    ultimo_acesso = _norm(ultimo[0]) if ultimo else None

    return SystemStatus(
        valid=valid,
        unidade_sigla=unidade_sigla,
        unidade_descricao=unidade_desc,
        usuario=usuario,
        ultimo_acesso=ultimo_acesso,
    )


def _parse_process_row(row: html.HtmlElement, caixa: str, base_url: str) -> Process | None:
    anchors = row.xpath("./td//a[contains(@class, 'processoVisualizado') or contains(@class, 'processoNaoVisualizado')]")
    if not anchors:
        return None

    link_el = anchors[0]
    link = urljoin(base_url, link_el.attrib.get("href", ""))
    numero = _norm(link_el.text_content()).replace(" ", "")
    aria = _norm(link_el.attrib.get("aria-label"))

    tipo = aria
    especificacao = ""
    if " / " in aria:
        tipo, especificacao = aria.split(" / ", 1)

    novo = "processoNaoVisualizado" in (link_el.attrib.get("class") or "")

    atribuido = None
    atrib_links = row.xpath("./td/a[contains(@class, 'ancoraSigla')]/text()")
    if atrib_links:
        atribuido = _norm(atrib_links[0])

    marcador = None
    marcador_links = row.xpath("./td/a[contains(@aria-label,'Marcador')]/@aria-label")
    if marcador_links:
        marcador = _norm(unescape(marcador_links[0]))

    return Process(
        numero=numero,
        tipo=tipo,
        especificacao=especificacao,
        id_procedimento=_extract_id_procedimento(link),
        link=link,
        novo=novo,
        atribuido=atribuido,
        marcador=marcador,
        caixa=caixa,
    )


def parse_process_table(content: str, base_url: str, table_id: str, caixa: str) -> list[Process]:
    page = _tree(content)
    rows = page.xpath(f"//table[@id='{table_id}']//tr[starts-with(@id, 'P')]")
    result: list[Process] = []
    for row in rows:
        item = _parse_process_row(row, caixa=caixa, base_url=base_url)
        if item:
            result.append(item)
    return result


def parse_processes(content: str, base_url: str) -> ProcessList:
    return ProcessList(
        recebidos=parse_process_table(content, base_url, "tblProcessosRecebidos", "recebidos"),
        gerados=parse_process_table(content, base_url, "tblProcessosGerados", "gerados"),
    )


def parse_menu_links(content: str, base_url: str) -> dict[str, str]:
    page = _tree(content)
    links: dict[str, str] = {}
    for el in page.xpath("//ul[@id='infraMenu']//a[@link and @href]"):
        key = _norm(el.attrib.get("link"))
        href = urljoin(base_url, el.attrib.get("href", ""))
        if key:
            links[key] = href
    return links


def parse_quick_search_form(content: str, base_url: str) -> str | None:
    page = _tree(content)
    forms = page.xpath("//form[@id='frmProtocoloPesquisaRapida']")
    if not forms:
        return None
    action = forms[0].attrib.get("action", "")
    return urljoin(base_url, action)


def parse_units_from_login(content: str) -> list[Unit]:
    page = _tree(content)
    options = page.xpath("//select[@id='selOrgao']/option[@value!='null']")
    return [Unit(sigla=_norm(opt.text), descricao=_norm(opt.text), link=opt.attrib.get("value")) for opt in options]


def parse_current_unit_switch_link(content: str, base_url: str) -> str | None:
    page = _tree(content)
    links = page.xpath("//a[@id='lnkInfraUnidade']")
    if not links:
        return None

    onclick = links[0].attrib.get("onclick", "")
    marker = "window.location.href='"
    if marker not in onclick:
        return None
    part = onclick.split(marker, 1)[1]
    target = part.split("'", 1)[0]
    return urljoin(base_url, target)


def parse_units_switch_page(content: str, base_url: str) -> list[Unit]:
    page = _tree(content)
    units: list[Unit] = []
    for link in page.xpath("//a[contains(@href,'infra_alterar_unidade') or contains(@href,'infra_trocar_unidade')]"):
        label = _norm(link.text_content())
        if not label:
            continue
        units.append(Unit(sigla=label, descricao=_norm(link.attrib.get("title")) or label, link=urljoin(base_url, link.attrib.get("href", ""))))
    seen: set[str] = set()
    deduped: list[Unit] = []
    for unit in units:
        key = f"{unit.sigla}|{unit.link}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(unit)
    return deduped


def parse_documents(content: str, base_url: str) -> list[Document]:
    page = _tree(content)
    docs: list[Document] = []

    selectors: Iterable[str] = (
        "//a[contains(@href,'documento_visualizar')]",
        "//a[contains(@href,'documento_consultar')]",
        "//a[contains(@href,'acao=documento_') and @href]",
    )

    seen: set[str] = set()
    for selector in selectors:
        for el in page.xpath(selector):
            href = el.attrib.get("href", "")
            if not href:
                continue
            link = urljoin(base_url, href)
            if link in seen:
                continue
            seen.add(link)
            nome = _norm(el.attrib.get("title")) or _norm(el.text_content()) or "Documento"
            numero = _norm(el.text_content()) or nome
            docs.append(Document(numero=numero, nome=nome, link=link))

    return docs


def parse_process_details(content: str, base_url: str, numero: str, processo_link: str) -> ProcessDetails:
    docs = parse_documents(content, base_url)
    return ProcessDetails(processo_numero=numero, processo_link=processo_link, documentos=docs)


def parse_blocks(content: str, base_url: str) -> list[Block]:
    page = _tree(content)
    blocks: list[Block] = []

    rows = page.xpath("//table//tr[td]")
    for row in rows:
        cols = row.xpath("./td")
        if len(cols) < 2:
            continue

        block_id = _norm(cols[0].text_content())
        descricao = _norm(cols[1].text_content())
        if not block_id or not any(ch.isdigit() for ch in block_id):
            continue

        link_el = cols[0].xpath(".//a[@href]")
        link = urljoin(base_url, link_el[0].attrib.get("href", "")) if link_el else None

        tipo = _norm(cols[2].text_content()) if len(cols) > 2 else "assinatura"
        estado = _norm(cols[3].text_content()) if len(cols) > 3 else None

        blocks.append(Block(id=block_id, tipo=tipo or "assinatura", descricao=descricao or block_id, estado=estado, link=link))

    return blocks


def parse_block_details(content: str, base_url: str, block_id: str) -> list[Document]:
    return parse_documents(content, base_url)
