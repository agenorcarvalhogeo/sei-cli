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
