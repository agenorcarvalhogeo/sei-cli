"""SEI HTML parsers.

The SEI interface uses server-rendered HTML with JS-enhanced navigation.
Key patterns:
- Process tree: ifrArvore iframe with JS array `Nos[]` = new infraArvoreNo(...)
- Blocks: standard HTML tables with infraTrClara/infraTrEscura rows
- Unit switch: table with infraArvoreNo-like rows
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse

from lxml import html

from sei_cli.models import (
    Block, BlockDocument, Document, LoginForm, Process,
    ProcessDetails, ProcessList, SystemStatus, Unit,
)


def _tree(content: str) -> html.HtmlElement:
    if not content or not content.strip():
        raise ValueError("Empty HTML content")
    return html.fromstring(content)


def _norm(text: str | None) -> str:
    return (text or "").replace("\xa0", " ").strip()


def _extract_id(link: str, param: str = "id_procedimento") -> str | None:
    parsed = urlparse(link)
    values = parse_qs(parsed.query).get(param)
    return values[0] if values else None


# --- Login ---

def parse_login_form(content: str, current_url: str) -> LoginForm:
    page = _tree(content)
    form = page.xpath("//form[@id='frmLogin']")
    if not form:
        form = page.xpath("//form")
    if not form:
        raise ValueError("Formulário de login não encontrado")
    action = form[0].attrib.get("action", "")
    return LoginForm(action=urljoin(current_url, action))


# --- System status ---

def parse_system_status(content: str) -> SystemStatus:
    page = _tree(content)
    valid = bool(
        page.xpath("//title[contains(., 'Controle de Processos')]")
        or "Controle de Processos" in (page.text_content() or "")[:5000]
    )

    unit_el = page.xpath("//a[@id='lnkInfraUnidade']")
    unidade_sigla = _norm(unit_el[0].text_content()) if unit_el else None
    unidade_desc = _norm(unit_el[0].attrib.get("title")) if unit_el else None

    user_el = page.xpath("//a[@id='lnkUsuarioSistema']")
    usuario = _norm(user_el[0].attrib.get("title")) if user_el else None

    ultimo = page.xpath("//div[@id='divInfraBarraAcesso']//a/text()")
    ultimo_acesso = _norm(ultimo[0]) if ultimo else None

    return SystemStatus(
        valid=valid,
        unidade_sigla=unidade_sigla,
        unidade_descricao=unidade_desc,
        usuario=usuario,
        ultimo_acesso=ultimo_acesso,
    )


# --- Processes ---

def _parse_process_row(row: html.HtmlElement, caixa: str, base_url: str) -> Process | None:
    anchors = row.xpath(
        "./td//a[contains(@class, 'processoVisualizado') "
        "or contains(@class, 'processoNaoVisualizado')]"
    )
    if not anchors:
        return None

    el = anchors[0]
    link = urljoin(base_url, el.attrib.get("href", ""))
    numero = _norm(el.text_content()).replace(" ", "")
    aria = _norm(el.attrib.get("aria-label"))

    tipo, especificacao = aria, ""
    if " / " in aria:
        tipo, especificacao = aria.split(" / ", 1)

    novo = "processoNaoVisualizado" in (el.attrib.get("class") or "")

    atrib = row.xpath("./td/a[contains(@class, 'ancoraSigla')]/text()")
    atribuido = _norm(atrib[0]) if atrib else None

    marcador = row.xpath("./td/a[contains(@aria-label,'Marcador')]/@aria-label")
    marcador_val = _norm(unescape(marcador[0])) if marcador else None

    return Process(
        numero=numero,
        tipo=tipo,
        especificacao=especificacao,
        id_procedimento=_extract_id(link),
        link=link,
        novo=novo,
        atribuido=atribuido,
        marcador=marcador_val,
        caixa=caixa,
    )


def parse_processes(content: str, base_url: str) -> ProcessList:
    page = _tree(content)
    recebidos, gerados = [], []
    for table_id, caixa, dest in [
        ("tblProcessosRecebidos", "recebidos", recebidos),
        ("tblProcessosGerados", "gerados", gerados),
    ]:
        for row in page.xpath(f"//table[@id='{table_id}']//tr[starts-with(@id, 'P')]"):
            p = _parse_process_row(row, caixa, base_url)
            if p:
                dest.append(p)
    return ProcessList(recebidos=recebidos, gerados=gerados)


# --- Document tree (from iframe JS) ---

# Pattern: new infraArvoreNo("TYPE","id_doc","id_proc","url","iframe","title1","title2",...)
_ARVORE_RE = re.compile(
    r'new\s+infraArvoreNo\('
    r'"(\w+)",'          # tipo: PROCESSO or DOCUMENTO
    r'"(\d+)",'          # id
    r'(?:"(\d+)"|null),' # parent id
    r'"([^"]+)",'        # url
    r'"([^"]*)",'        # iframe target
    r'"([^"]*)",'        # title/label
    r'"([^"]*)"'         # title2
)


def parse_document_tree(content: str, base_url: str) -> list[Document]:
    """Parse the ifrArvore iframe content to extract document list."""
    docs = []
    for m in _ARVORE_RE.finditer(content):
        tipo_raw, doc_id, _parent_id, url, _iframe, title, _title2 = m.groups()
        if tipo_raw == "PROCESSO":
            continue
        # Determine document type from icon in the full match context
        full_line = content[m.start():m.start() + 500]
        if "documento_externo" in full_line:
            tipo = "externo"
        elif "documento_interno" in full_line:
            tipo = "interno"
        else:
            tipo = "documento"
        
        docs.append(Document(
            numero=doc_id,
            nome=_norm(title),
            tipo=tipo,
            id_documento=doc_id,
            link=urljoin(base_url, url),
        ))
    return docs


# --- Blocks ---

def parse_blocks(content: str, base_url: str) -> list[Block]:
    """Parse blocos de assinatura list page.
    
    Table columns: checkbox | numero | icons | icons | estado | unidade_origem | unidade_destino | icons | descricao | actions
    """
    page = _tree(content)
    blocks = []
    rows = page.xpath("//tr[contains(@class,'infraTrClara') or contains(@class,'infraTrEscura')]")
    
    for row in rows:
        tds = row.xpath("./td")
        if len(tds) < 8:
            continue
        
        numero = _norm(tds[1].text_content())
        if not numero or not numero.isdigit():
            continue
        
        estado = _norm(tds[4].text_content())
        unidade_origem = _norm(tds[5].text_content())
        unidade_destino = _norm(tds[6].text_content())
        descricao = _norm(tds[8].text_content()) if len(tds) > 8 else ""
        
        # Link to bloco detail
        link_el = tds[1].xpath(".//a[@href]")
        link = urljoin(base_url, link_el[0].attrib.get("href", "")) if link_el else None
        
        blocks.append(Block(
            numero=numero,
            estado=estado,
            unidade_origem=unidade_origem,
            unidade_destino=unidade_destino,
            descricao=descricao,
            link=link,
        ))
    
    return blocks


def parse_block_documents(content: str, base_url: str) -> list[BlockDocument]:
    """Parse documents inside a bloco de assinatura.
    
    Table: seq | processo | documento_id | tipo | assinante | status icons
    """
    page = _tree(content)
    docs = []
    rows = page.xpath("//tr[contains(@class,'infraTrClara') or contains(@class,'infraTrEscura')]")
    
    for row in rows:
        tds = row.xpath("./td")
        if len(tds) < 5:
            continue
        
        seq = _norm(tds[1].text_content()) if len(tds) > 1 else ""
        processo = _norm(tds[2].text_content()) if len(tds) > 2 else ""
        doc_id = _norm(tds[3].text_content()) if len(tds) > 3 else ""
        tipo_doc = _norm(tds[4].text_content()) if len(tds) > 4 else ""
        assinante = _norm(tds[5].text_content()) if len(tds) > 5 else ""
        
        # Check if signed (look for 'Assinatura' img with specific title)
        imgs = row.xpath(".//img[@title]")
        assinado = any("Assinatura" in (i.attrib.get("title", "")) for i in imgs)
        
        docs.append(BlockDocument(
            seq=seq,
            processo=processo,
            documento_id=doc_id,
            tipo_documento=tipo_doc,
            assinante=assinante,
            assinado=assinado,
        ))
    
    return docs


# --- Units ---

def parse_unit_switch_link(content: str, base_url: str) -> str | None:
    """Extract the 'trocar unidade' URL from the control page."""
    page = _tree(content)
    el = page.xpath("//a[@id='lnkInfraUnidade']")
    if not el:
        return None
    onclick = el[0].attrib.get("onclick", "")
    match = re.search(r"href='([^']+)'", onclick)
    if not match:
        return None
    return urljoin(base_url, match.group(1))


def parse_units_switch_page(content: str, base_url: str) -> list[Unit]:
    """Parse the unit switch page.
    
    Structure: form with radio buttons (chkInfraItem=<unit_id>) and table rows.
    Switching uses JS: creates hidden 'selInfraUnidades' field and submits form.
    We return the form action URL and unit IDs so the client can POST directly.
    """
    page = _tree(content)
    units = []
    
    # Get radio buttons (unit IDs)
    radios = page.xpath("//input[@type='radio' and @name='chkInfraItem']")
    radio_values = [r.attrib.get("value", "") for r in radios]
    
    # Get table rows (sigla, descricao)
    rows = page.xpath("//tr[contains(@class,'infraTrClara') or contains(@class,'infraTrEscura')]")
    
    for i, row in enumerate(rows):
        tds = row.xpath("./td")
        if len(tds) < 3:
            continue
        
        sigla = _norm(tds[1].text_content())
        descricao = _norm(tds[2].text_content())
        unit_id = radio_values[i] if i < len(radio_values) else None
        
        if not sigla:
            continue
        
        units.append(Unit(sigla=sigla, descricao=descricao, link=unit_id))
    
    return units


def parse_unit_switch_form(content: str) -> tuple[str, dict[str, str]]:
    """Extract form action URL and hidden fields from the switch page.
    
    Returns (form_action, hidden_fields_dict).
    """
    page = _tree(content)
    form = page.xpath("//form[@id='frmInfraSelecaoUnidade']")
    if not form:
        # Might be on a different page (e.g. already redirected to control)
        form = page.xpath("//form")
    if not form:
        raise ValueError("Form de troca de unidade não encontrado")
    
    action = form[0].attrib.get("action", "")
    hiddens = {}
    for inp in form[0].xpath(".//input[@type='hidden']"):
        name = inp.attrib.get("name", "")
        if name:
            hiddens[name] = inp.attrib.get("value", "")
    
    return action, hiddens


# --- Menu links ---

def parse_menu_links(content: str, base_url: str) -> dict[str, str]:
    """Extract menu links from the control page (blocos, pesquisa, etc.)."""
    page = _tree(content)
    links = {}
    for el in page.xpath("//a[@href]"):
        href = el.attrib.get("href", "")
        text = _norm(el.text_content())
        # Key navigation links
        if "bloco_assinatura_listar" in href:
            links["blocos_assinatura"] = urljoin(base_url, href)
        elif "bloco_interno_listar" in href:
            links["blocos_internos"] = urljoin(base_url, href)
        elif "protocolo_pesquisa_rapida" in href:
            links["pesquisa_rapida"] = urljoin(base_url, href)
    return links
