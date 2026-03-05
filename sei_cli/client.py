"""SEI HTTP Client — read-only operations.

Handles the full login flow with manual redirect following to preserve
the PHPSESSID cookie that changes at inicializar.php.

Key insight: After login, the initial page load is the ONLY guaranteed
request that works. Subsequent requests to controlador.php fail because
SEI validates infra_hash per-session. So we cache the control page HTML
and extract all navigation URLs from it.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from sei_cli import auth
from sei_cli.config import load_credentials, SESSION_PATH
from sei_cli.models import (
    Block, BlockDocument, Document, Process, ProcessList,
    SystemStatus, Unit,
)
from sei_cli.parsers import (
    parse_block_documents,
    parse_blocks,
    parse_document_tree,
    parse_menu_links,
    parse_processes,
    parse_system_status,
    parse_unit_switch_form,
    parse_unit_switch_link,
    parse_units_switch_page,
)


class SEIClient:
    BASE = "https://sei.rn.gov.br"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or self.BASE).rstrip("/")
        self.client = auth.create_http_client()
        self._control_html: str | None = None
        self._menu_links: dict[str, str] = {}

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "SEIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # --- Internal HTTP helpers ---

    def _get(self, url: str) -> httpx.Response:
        r = self.client.get(url)
        return auth._follow(self.client, r, self.base_url)

    def _post(self, url: str, data: dict) -> httpx.Response:
        r = self.client.post(url, data=data)
        return auth._follow(self.client, r, self.base_url)

    def _sei_url(self, path: str) -> str:
        return f"{self.base_url}/sei/{path}"

    # --- Auth ---

    def login(self) -> SystemStatus:
        creds = load_credentials()
        status, html = auth.login(self.client, creds)
        if not status.success:
            raise RuntimeError(status.message)
        self._control_html = html
        self._menu_links = parse_menu_links(html, self._sei_url(""))
        return parse_system_status(html)

    def _ensure_control(self) -> str:
        """Return cached control page HTML, re-logging in if needed."""
        if self._control_html:
            return self._control_html
        self.login()
        return self._control_html or ""

    def _fresh_control(self) -> str:
        """Force re-login to get fresh control page."""
        self._control_html = None
        self.login()
        return self._control_html or ""

    # --- Status ---

    def status(self) -> SystemStatus:
        html = self._ensure_control()
        return parse_system_status(html)

    # --- Processes ---

    def list_processes(self) -> ProcessList:
        html = self._ensure_control()
        return parse_processes(html, base_url=self._sei_url(""))

    def get_process_documents(self, id_procedimento: str) -> list[Document]:
        """Get document tree for a process by navigating to it and parsing the JS tree."""
        html = self._ensure_control()
        
        # Find the process link
        soup = BeautifulSoup(html, "lxml")
        proc_link = None
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "procedimento_trabalhar" in href and id_procedimento in href:
                proc_link = urljoin(self._sei_url(""), href)
                break
        
        if not proc_link:
            # Try constructing URL from infra_hash
            hashes = re.findall(r'infra_hash=([a-f0-9]{64})', html)
            if hashes:
                proc_link = (
                    self._sei_url("controlador.php")
                    + f"?acao=procedimento_trabalhar&id_procedimento={id_procedimento}"
                    + f"&infra_sistema=100000100&infra_hash={hashes[0]}"
                )
        
        if not proc_link:
            return []
        
        # Navigate to process page
        r = self._get(proc_link)
        psoup = BeautifulSoup(r.text, "lxml")
        
        # Find ifrArvore iframe
        iframe = psoup.find("iframe", {"name": "ifrArvore"})
        if not iframe or not iframe.get("src"):
            return []
        
        arvore_url = urljoin(self._sei_url(""), iframe["src"])
        ra = self._get(arvore_url)
        
        # Need to re-login after navigating away from control page
        self._control_html = None
        
        return parse_document_tree(ra.text, base_url=self._sei_url(""))

    # --- Blocks ---

    def list_blocks(self) -> list[Block]:
        """List blocos de assinatura."""
        html = self._ensure_control()
        
        blocos_url = self._menu_links.get("blocos_assinatura")
        if not blocos_url:
            return []
        
        r = self._get(blocos_url)
        # Invalidate control cache since we navigated away
        self._control_html = None
        
        return parse_blocks(r.text, base_url=self._sei_url(""))

    def get_block_documents(self, block_numero: str) -> list[BlockDocument]:
        """List documents inside a specific bloco de assinatura."""
        html = self._ensure_control()
        blocos_url = self._menu_links.get("blocos_assinatura")
        if not blocos_url:
            return []
        
        r = self._get(blocos_url)
        soup = BeautifulSoup(r.text, "lxml")
        
        # Find the link to the specific block
        detail_url = None
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "rel_bloco_protocolo_listar" in href and a.text.strip() == block_numero:
                detail_url = urljoin(self._sei_url(""), href)
                break
        
        self._control_html = None
        
        if not detail_url:
            return []
        
        rd = self._get(detail_url)
        return parse_block_documents(rd.text, base_url=self._sei_url(""))

    # --- Units ---

    def list_units(self) -> list[Unit]:
        """List available units for switching."""
        html = self._ensure_control()
        switch_url = parse_unit_switch_link(html, self._sei_url(""))
        if not switch_url:
            return []
        
        r = self._get(switch_url)
        self._control_html = None
        
        return parse_units_switch_page(r.text, base_url=self._sei_url(""))

    def switch_unit(self, keyword: str) -> SystemStatus:
        """Switch active unit. Keyword matches against sigla or descricao.
        
        The unit.link stores the unit ID (not a URL). We POST the switch form
        with selInfraUnidades=<unit_id> to replicate the JS selecionarUnidade().
        
        After switching, we need a fresh login because the infra_hash changes.
        """
        # Always get a fresh control page for valid switch URL
        html = self._fresh_control()
        switch_url = parse_unit_switch_link(html, self._sei_url(""))
        if not switch_url:
            raise RuntimeError("Link de troca de unidade não encontrado")
        
        r = self._get(switch_url)
        units = parse_units_switch_page(r.text, self._sei_url(""))
        form_action, hiddens = parse_unit_switch_form(r.text)
        
        kw = keyword.lower()
        target = None
        for u in units:
            if kw in u.sigla.lower() or kw in u.descricao.lower():
                target = u
                break
        
        if not target or not target.link:
            available = ", ".join(u.sigla for u in units)
            raise RuntimeError(f"Unidade '{keyword}' não encontrada. Disponíveis: {available}")
        
        # POST form with selInfraUnidades (the key JS creates dynamically)
        post_url = urljoin(str(r.url), form_action) if form_action else switch_url
        data = {**hiddens, "selInfraUnidades": target.link}
        
        r2 = self._post(post_url, data)
        self._control_html = r2.text
        self._menu_links = parse_menu_links(r2.text, self._sei_url(""))
        return parse_system_status(r2.text)

    # --- Search ---

    def search(self, query: str) -> str:
        """Quick search (pesquisa rápida). Returns raw HTML."""
        html = self._ensure_control()
        soup = BeautifulSoup(html, "lxml")
        
        pesq_form = soup.find("form", {"id": "frmProtocoloPesquisaRapida"})
        if not pesq_form:
            # Fallback: find any form with txtPesquisaRapida
            pesq_input = soup.find("input", {"id": "txtPesquisaRapida"})
            if pesq_input:
                pesq_form = pesq_input.find_parent("form")
        
        if not pesq_form:
            raise RuntimeError("Formulário de pesquisa não encontrado")
        
        action = pesq_form.get("action", "")
        search_url = urljoin(self._sei_url(""), action)
        
        r = self._post(search_url, data={"txtPesquisaRapida": query})
        self._control_html = None
        
        return r.text

    # --- New processes check ---

    def check_new_processes(self) -> list[Process]:
        """Return only processes marked as 'novo' (unread)."""
        procs = self.list_processes()
        return [p for p in procs.recebidos if p.novo]

    # --- Signing ---

    def sign_block(self, block_numero: str) -> dict:
        """Sign all pending documents in a bloco de assinatura.

        Returns dict with 'signed', 'already_signed', 'errors' lists.
        """
        return self._sign_from_blocos(block_numero)

    def sign_document(self, id_documento: str, id_procedimento: str) -> dict:
        """Sign a single document by ID (from process tree).

        Uses the linkAssinarDocumento URL from arvore_visualizar.
        """
        html = self._ensure_control()

        # Navigate to process
        proc_url = (
            self._sei_url("controlador.php")
            + f"?acao=procedimento_trabalhar&id_procedimento={id_procedimento}"
        )
        # Find with valid hash
        soup = BeautifulSoup(html, "lxml")
        proc_link = None
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "procedimento_trabalhar" in href and id_procedimento in href:
                proc_link = urljoin(self._sei_url(""), href)
                break

        if not proc_link:
            return {"error": f"Processo {id_procedimento} não encontrado na tela atual"}

        rp = self._get(proc_link)
        psoup = BeautifulSoup(rp.text, "lxml")
        iframe = psoup.find("iframe", {"name": "ifrArvore"})
        if not iframe:
            return {"error": "Árvore de documentos não encontrada"}

        arvore_url = urljoin(self._sei_url(""), iframe["src"])
        ra = self._get(arvore_url)

        # Find the specific document's arvore_visualizar URL
        doc_pattern = re.compile(
            rf'controlador\.php\?acao=arvore_visualizar[^"]*id_documento={id_documento}[^"]*'
        )
        doc_match = doc_pattern.search(ra.text)
        if not doc_match:
            return {"error": f"Documento {id_documento} não encontrado na árvore"}

        doc_url = urljoin(self._sei_url(""), doc_match.group())
        rd = self._get(doc_url)

        # Extract linkAssinarDocumento
        sign_match = re.search(r"var\s+linkAssinarDocumento\s*=\s*'([^']+)'", rd.text)
        if not sign_match:
            return {"error": "Link de assinatura não encontrado para este documento"}

        sign_url = urljoin(self._sei_url(""), sign_match.group(1))
        self._control_html = None

        return self._execute_sign(sign_url, id_documento)

    def _sign_from_blocos(self, block_numero: str) -> dict:
        """Navigate to blocos, find the block, and sign its documents."""
        html = self._ensure_control()
        blocos_url = self._menu_links.get("blocos_assinatura")
        if not blocos_url:
            return {"error": "Link de blocos não encontrado"}

        rb = self._get(blocos_url)

        # Extract sign URL from acaoAssinar JS
        urls = re.findall(
            r"controlador\.php\?acao=documento_assinar[^'\"]+",
            rb.text,
        )
        if not urls:
            return {"error": "URL de assinatura não encontrada na página de blocos"}

        sign_url = urljoin(self._sei_url(""), urls[0])

        # POST the blocos form with the target block ID
        bsoup = BeautifulSoup(rb.text, "lxml")
        form = bsoup.find("form", {"id": "frmBlocoLista"})
        if not form:
            return {"error": "Formulário de blocos não encontrado"}

        fdata = {}
        for inp in form.find_all("input"):
            n = inp.get("name", "")
            if n:
                fdata[n] = inp.get("value", "")
        fdata["hdnInfraItemId"] = block_numero

        rs = self._post(sign_url, fdata)
        ssoup = BeautifulSoup(rs.text, "lxml")
        form2 = ssoup.find("form", {"id": "frmAssinaturas"})
        if not form2:
            return {"error": "Formulário de assinatura não encontrado"}

        doc_id = form2.find("input", {"name": "hdnIdDocumentos"})
        doc_id_val = doc_id.get("value", "") if doc_id else ""

        self._control_html = None
        return self._execute_sign_form(form2, rs.text)

    def _execute_sign(self, sign_url: str, doc_id: str) -> dict:
        """GET the sign page and submit it."""
        rs = self._get(sign_url)
        ssoup = BeautifulSoup(rs.text, "lxml")
        form = ssoup.find("form", {"id": "frmAssinaturas"})
        if not form:
            return {"error": "Formulário de assinatura não encontrado"}
        return self._execute_sign_form(form, rs.text)

    def _execute_sign_form(self, form: Any, page_html: str) -> dict:
        """Submit a sign form with credentials.

        The SEI sign form uses ISO-8859-1 encoding (º → \\xba).
        """
        from urllib.parse import urlencode as _urlencode

        creds = load_credentials()
        form_action = urljoin(self._sei_url(""), form.get("action", ""))

        # Collect hidden fields
        sign_data = {}
        for inp in form.find_all("input"):
            n = inp.get("name", "")
            if n:
                sign_data[n] = inp.get("value", "")

        # The cargo is "2º Tenente QOEM BM" — must use latin1 º (\xba)
        cargo = "2\xba Tenente QOEM BM"

        sign_data.update({
            "txtUsuario": "LEO ZENON TASSI",
            "hdnIdUsuario": sign_data.get("hdnIdUsuario", "100066959"),
            "pwdSenha": creds.senha,
            "selOrgao": "28",
            "selCargoFuncao": cargo,
            "hdnFormaAutenticacao": "S",
        })

        doc_ids = sign_data.get("hdnIdDocumentos", "")

        # Encode as ISO-8859-1
        body = _urlencode(
            list(sign_data.items()),
            encoding="iso-8859-1",
        )

        r = self.client.post(
            form_action,
            content=body.encode("iso-8859-1"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r = auth._follow(self.client, r, self.base_url)

        # Parse response for messages
        result: dict = {"doc_ids": doc_ids, "signed": [], "already_signed": [], "errors": []}

        # Check for server messages
        for msg in re.findall(
            r'<div[^>]*class="alert[^"]*"[^>]*>.*?</div>',
            r.text,
            re.DOTALL,
        ):
            text = BeautifulSoup(msg, "lxml").text.strip()
            if "já foi assinado" in text:
                result["already_signed"].append(text)
            elif "assinado com sucesso" in text.lower() or "Blocos de Assinatura" in r.text:
                result["signed"].append(doc_ids)
            elif "erro" in text.lower() or "não" in text.lower():
                result["errors"].append(text)

        # Check if redirected to blocos list (success — signed and returned)
        if "Blocos de Assinatura" in r.text and not result["signed"] and not result["already_signed"]:
            result["signed"].append(doc_ids)

        # If still on sign page with no messages, docs were likely all already signed
        if not result["signed"] and not result["already_signed"] and not result["errors"]:
            if "Assinatura de Documento" in r.text:
                # The form re-rendered but no error → all docs already signed
                result["already_signed"].append(f"Documentos {doc_ids} já assinados")

        self._control_html = None
        return result
