from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from sei_cli import auth
from sei_cli.config import load_credentials, SESSION_PATH
from sei_cli.models import (
    Block, Credentials, Process, ProcessList, SessionData,
    SystemStatus, Unit,
)
from sei_cli.parsers import (
    parse_blocks,
    parse_processes,
    parse_system_status,
    parse_units_switch_page,
)


class SEIClient:
    BASE = "https://sei.rn.gov.br"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or self.BASE).rstrip("/")
        self.client = auth.create_http_client()
        self._page_cache: str | None = None  # Cache the last control page
        self._load_persisted_session()

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "SEIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # --- Session persistence ---

    def _load_persisted_session(self) -> None:
        if SESSION_PATH.exists():
            try:
                data = json.loads(SESSION_PATH.read_text())
                for name, value in data.get("cookies", {}).items():
                    self.client.cookies.set(name, value)
            except Exception:
                pass

    def _save_session(self) -> None:
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        cookies = {name: value for name, value in self.client.cookies.items()}
        SESSION_PATH.write_text(json.dumps({"cookies": cookies}))

    # --- Auth ---

    def login(self) -> SystemStatus:
        creds = load_credentials()
        status, html = auth.login(self.client, creds)
        if not status.success:
            raise RuntimeError(status.message)
        self._page_cache = html
        self._save_session()
        return self._parse_status(html)

    def is_valid(self) -> bool:
        ok, html = auth.check_session(self.client, self._control_url())
        if ok:
            self._page_cache = html
        return ok

    def ensure_auth(self) -> str:
        """Ensure authenticated, return control page HTML."""
        if self._page_cache:
            html = self._page_cache
            self._page_cache = None
            return html
        ok, html = auth.check_session(self.client, self._control_url())
        if ok:
            return html
        # Re-login
        self.login()
        html = self._page_cache or ""
        self._page_cache = None
        return html

    # --- URLs ---

    def _control_url(self) -> str:
        return f"{self.base_url}/sei/controlador.php?acao=procedimento_controlar"

    # --- Core operations ---

    def status(self) -> SystemStatus:
        html = self.ensure_auth()
        return self._parse_status(html)

    def _parse_status(self, html: str) -> SystemStatus:
        return parse_system_status(html)

    def list_processes(self, unit: str | None = None) -> ProcessList:
        if unit:
            self.switch_unit(unit)
        html = self.ensure_auth()
        return parse_processes(html, base_url=self.base_url)

    def search(self, query: str) -> str:
        """Search via pesquisa rápida. Returns result page HTML."""
        html = self.ensure_auth()
        soup = BeautifulSoup(html, "lxml")
        pesq = soup.find(id="txtPesquisaRapida")
        if not pesq:
            raise RuntimeError("Campo de pesquisa rápida não encontrado")
        form = pesq.find_parent("form")
        action = form.get("action", "") if form else ""
        search_url = urljoin(self._control_url(), action)
        
        r = self.client.post(search_url, data={"txtPesquisaRapida": query})
        r = auth._follow(self.client, r, search_url)
        return r.text

    def list_blocks(self) -> list[Block]:
        """List signature blocks."""
        html = self.ensure_auth()
        soup = BeautifulSoup(html, "lxml")
        # Find blocos link from the page
        links = soup.find_all("a")
        blocos_url = None
        for link in links:
            href = link.get("href", "")
            if "bloco_assinatura_listar" in href or "bloco" in href.lower():
                blocos_url = urljoin(self._control_url(), href)
                break
        
        if not blocos_url:
            # Try constructing the URL with infra_hash from the page
            import re
            hashes = re.findall(r'infra_hash=([a-f0-9]{64})', html)
            if hashes:
                blocos_url = (
                    f"{self.base_url}/sei/controlador.php?"
                    f"acao=bloco_assinatura_listar&"
                    f"infra_sistema=100000100&"
                    f"infra_hash={hashes[0]}"
                )
        
        if not blocos_url:
            return []
        
        r = self.client.get(blocos_url)
        r = auth._follow(self.client, r, blocos_url)
        return parse_blocks(r.text, base_url=self.base_url)

    def list_units(self) -> list[Unit]:
        """List available units."""
        html = self.ensure_auth()
        soup = BeautifulSoup(html, "lxml")
        # Find unit switch link
        unit_link = soup.find(id="lnkInfraUnidade")
        if not unit_link:
            return []
        onclick = unit_link.get("onclick", "")
        # Extract URL from onclick: window.location.href='...'
        import re
        match = re.search(r"href='([^']+)'", onclick)
        if not match:
            return []
        switch_url = urljoin(self._control_url(), match.group(1))
        r = self.client.get(switch_url)
        r = auth._follow(self.client, r, switch_url)
        return parse_units_switch_page(r.text, base_url=self.base_url)

    def switch_unit(self, sigla: str) -> bool:
        """Switch active unit by sigla keyword."""
        units = self.list_units()
        target = None
        for u in units:
            if sigla.lower() in u.sigla.lower() or sigla.lower() in u.descricao.lower():
                target = u
                break
        if not target or not target.link:
            raise RuntimeError(f"Unidade '{sigla}' não encontrada")
        
        r = self.client.get(urljoin(self.base_url, target.link))
        r = auth._follow(self.client, r, self.base_url)
        self._page_cache = r.text
        self._save_session()
        return "Controle de Processos" in r.text
