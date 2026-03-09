"""SEI HTTP Client — full workflow operations.

Handles login, process listing, document creation/editing, signing,
and unit switching via pure HTTP (no browser needed).

Key insight: After login, the initial page load is the ONLY guaranteed
request that works. Subsequent requests to controlador.php fail because
SEI validates infra_hash per-session. So we cache the control page HTML
and extract all navigation URLs from it.

Cookie flow: Login creates PHPSESSID on /sip/, then inicializar.php
creates a NEW PHPSESSID for /sei/. Must follow redirects manually
(hop-by-hop) to capture both cookies.
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
    Block, BlockDocument, Document, DocumentCreated, DocumentType,
    EditorSection, Marcador, Process, ProcessList, SystemStatus,
    TramitarForm, TreeDocument, TreeFolder, Unit,
)
from sei_cli.relatorio_parser import (
    RelatorioServico,
    parse_relatorio,
    summarize_batch,
    summarize as summarize_relatorio,
)
from sei_cli.parsers import (
    parse_block_documents,
    parse_blocks,
    parse_document_tree,
    parse_expanded_folder,
    parse_marcador_form,
    parse_marcadores_list,
    parse_menu_links,
    parse_processes,
    parse_system_status,
    parse_tramitar_form,
    parse_tree_folders,
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
        self._editor_hiddens: dict[str, str] = {}
        self._current_unit_id: str | None = None

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

    def _extract_action_url(self, html: str, token: str) -> str | None:
        """Extract action URL from href or JS onclick snippets."""
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a"):
            href = a.get("href", "")
            onclick = a.get("onclick", "")
            if token in href:
                return urljoin(self._sei_url(""), href)
            if token in onclick:
                m = re.search(r"'([^']*" + re.escape(token) + r"[^']*)'", onclick)
                if m:
                    return urljoin(self._sei_url(""), m.group(1))
                m = re.search(r'"([^"]*' + re.escape(token) + r'[^"]*)"', onclick)
                if m:
                    return urljoin(self._sei_url(""), m.group(1))
        return None

    def _find_process_link(self, control_html: str, id_procedimento: str) -> str | None:
        soup = BeautifulSoup(control_html, "lxml")
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "procedimento_trabalhar" in href and f"id_procedimento={id_procedimento}" in href:
                return urljoin(self._sei_url(""), href)
        return None

    def _navigate_process_page(self, id_procedimento: str) -> httpx.Response:
        html = self._ensure_control()
        proc_link = self._find_process_link(html, id_procedimento)
        if not proc_link:
            raise RuntimeError(
                f"Processo {id_procedimento} não encontrado na unidade ativa. "
                "Verifique se o processo está visível nessa unidade."
            )
        return self._get(proc_link)

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

    # --- Process creation ---

    def create_process(
        self,
        tipo_processo_id: str,
        *,
        especificacao: str = "",
        interessados: str = "",
        observacoes: str = "",
        nivel_acesso: str = "0",  # 0=Público, 1=Restrito, 2=Sigiloso
    ) -> dict:
        """Create a new process (Iniciar Processo).

        Args:
            tipo_processo_id: The process type ID (e.g. '100000506' for Diárias).
            especificacao: Description/specification field.
            interessados: Interested party text.
            observacoes: Notes for the unit.
            nivel_acesso: '0' (Público), '1' (Restrito), '2' (Sigiloso).

        Returns:
            Dict with 'numero' (process number), 'id_procedimento', 'link'.
        """
        html = self._ensure_control()

        # Step 1: Navigate to type chooser page
        href_match = re.search(
            r'href="(controlador\.php\?acao=procedimento_escolher_tipo[^"]+)"',
            html,
        )
        if not href_match:
            raise RuntimeError("Link 'Iniciar Processo' não encontrado")

        tipo_url = self._sei_url(href_match.group(1))
        r_tipo = self._get(tipo_url)

        soup_tipo = BeautifulSoup(r_tipo.text, "lxml")
        form_tipo = soup_tipo.find(
            "form", id="frmProcedimentoEscolherTipo"
        )
        if not form_tipo:
            raise RuntimeError("Formulário de escolha de tipo não encontrado")

        action_tipo = urljoin(self._sei_url(""), form_tipo["action"])
        data_tipo: dict[str, str] = {}
        for inp in form_tipo.find_all("input"):
            n = inp.get("name", "")
            if n and inp.get("type") != "checkbox":
                data_tipo[n] = inp.get("value", "")
        data_tipo["hdnIdTipoProcedimento"] = tipo_processo_id

        # Step 2: Submit type selection → get cadastro form
        r_cad = self._post(action_tipo, data_tipo)
        soup_cad = BeautifulSoup(r_cad.text, "lxml")
        form_cad = soup_cad.find("form", id="frmProcedimentoCadastro")
        if not form_cad:
            raise RuntimeError("Formulário de cadastro de processo não encontrado")

        action_cad = urljoin(self._sei_url(""), form_cad["action"])

        # Collect all form fields
        data_cad: dict[str, str] = {}
        for inp in form_cad.find_all("input"):
            n = inp.get("name", "")
            if not n:
                continue
            if inp.get("type") == "radio":
                # Only include checked radios or set our defaults
                if inp.get("checked"):
                    data_cad[n] = inp.get("value", "")
            else:
                data_cad[n] = inp.get("value", "")
        for sel in form_cad.find_all("select"):
            n = sel.get("name", "")
            if n:
                selected = sel.find("option", selected=True)
                data_cad[n] = selected["value"] if selected else ""
        for ta in form_cad.find_all("textarea"):
            n = ta.get("name", "")
            if n:
                data_cad[n] = ta.get_text()

        # Set our values
        data_cad["hdnFlagProcedimentoCadastro"] = "2"  # Critical: triggers save
        data_cad["rdoProtocolo"] = "A"  # Automático
        data_cad["selTipoProcedimento"] = tipo_processo_id
        data_cad["rdoNivelAcesso"] = nivel_acesso
        if especificacao:
            data_cad["txtDescricao"] = especificacao
        if observacoes:
            data_cad["txaObservacoes"] = observacoes

        # Submit creation
        r_create = self._post(action_cad, data_cad)
        self._control_html = None

        # Parse response for process number
        url_str = str(r_create.url)
        id_proc_match = re.search(r"id_procedimento=(\d+)", url_str)
        if not id_proc_match:
            id_proc_match = re.search(r"id_procedimento=(\d+)", r_create.text)

        # Extract process number from page
        csoup = BeautifulSoup(r_create.text, "lxml")
        title = csoup.title.get_text() if csoup.title else ""
        # Title is usually "SEI - 08810xxx.xxxxxx/2026-xx"
        num_match = re.search(r"(\d{8}\.\d+/\d{4}-\d{2})", title)
        if not num_match:
            num_match = re.search(
                r"(\d{8}\.\d+/\d{4}-\d{2})", r_create.text
            )

        return {
            "numero": num_match.group(1) if num_match else "",
            "id_procedimento": id_proc_match.group(1) if id_proc_match else "",
            "link": url_str,
        }

    # Process type constants for convenience
    PROC_TYPES: dict[str, str] = {
        "diarias": "100000506",
        "diarias_passagens": "100000506",
        "curso_proprio": "100000515",
        "curso_outra": "100000205",
        "ferias": "100000182",
        "escala_plantao": "100000191",
        "informacao": "100000595",
        "requerimento": "100000268",
        "suprimento_fundos": "100000815",
    }

    # --- Enhanced document tree with folder expansion ---

    def get_actions(
        self,
        id_procedimento: str,
        id_documento: str | None = None,
    ) -> dict[str, str]:
        """Return available actions for a process or document.

        Navigates to ``arvore_visualizar`` (optionally with a document
        selected) and extracts the ``var linkXxx = '...'`` JS variables
        that define the action menu URLs.

        Args:
            id_procedimento: Process ID.
            id_documento: If given, returns document-level actions.
                If None, returns process-level actions.

        Returns:
            Dict mapping JS variable names (e.g. ``linkExcluirDocumento``,
            ``linkAssinarDocumento``) to their full URL paths.
        """
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            return {}

        # Find the arvore_visualizar URL for the target
        target_id = id_documento or id_procedimento
        pattern = (
            rf'(controlador\.php\?acao=arvore_visualizar[^"]*'
            rf'id_{"documento" if id_documento else "procedimento"}={re.escape(target_id)}[^"]*)'
        )

        sel_url = None
        # Search in main tree and expanded folders
        m = re.search(pattern, arvore_html)
        if m:
            sel_url = self._sei_url(m.group(1).replace('&amp;', '&'))
            # For process-level, strip id_documento if present
            if not id_documento:
                sel_url = re.sub(r'&id_documento=\d+', '', sel_url)

        if not sel_url:
            # Try expanding lazy folders
            from sei_cli.parsers import parse_tree_folders
            for folder in parse_tree_folders(arvore_html):
                if folder.carregado:
                    continue
                r = self._post(self._sei_url(folder.link), {
                    'hdnArvore': '',
                    'hdnPastaAtual': folder.folder_id,
                    'hdnProtocolos': folder.protocolos,
                })
                m = re.search(pattern, r.text)
                if m:
                    sel_url = self._sei_url(m.group(1).replace('&amp;', '&'))
                    break

        if not sel_url:
            return {}

        r_sel = self._get(sel_url)

        # Extract var linkXxx = 'url' patterns
        links = re.findall(r"var\s+(link\w+)\s*=\s*'([^']+)'", r_sel.text)
        return {name: url for name, url in links}

    def alter_process(
        self,
        id_procedimento: str,
        *,
        descricao: str | None = None,
        observacoes: str | None = None,
    ) -> bool:
        """Update a process's description and/or observations.

        Navigates to ``procedimento_alterar``, reads the current form
        values, updates the specified fields, and POSTs back.

        Args:
            id_procedimento: Process ID.
            descricao: New description/specification (``txtDescricao``).
            observacoes: New observations (``txaObservacoes``).

        Returns:
            True if the update succeeded (302 redirect).

        Raises:
            RuntimeError: If the alter form is unavailable.
        """
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            raise RuntimeError("Could not navigate to process tree")

        # Find procedimento_alterar URL from Nos[0] acoes
        start = arvore_html.find('Nos[0]')
        end = arvore_html.find('Nos[1]', start)
        nos0 = arvore_html[start:end].replace('\\"', '"')

        alt_m = re.search(
            r'href="(controlador\.php\?acao=procedimento_alterar[^"]*)"',
            nos0,
        )
        if not alt_m:
            raise RuntimeError("Alterar Processo action not found in toolbar")

        alt_url = self._sei_url(alt_m.group(1).replace('&amp;', '&'))
        r_form = self._get(alt_url)

        # Parse form
        soup = BeautifulSoup(r_form.text, 'lxml')
        form = soup.find('form', id='frmProcedimentoCadastro')
        if not form:
            raise RuntimeError("Alter process form not found")

        action_url = urljoin(self._sei_url(""), form['action'])

        # Collect all current field values
        data: dict[str, str] = {}
        for inp in form.find_all('input'):
            name = inp.get('name', '')
            if not name:
                continue
            typ = inp.get('type', '')
            if typ == 'radio':
                if inp.get('checked'):
                    data[name] = inp.get('value', '')
            elif typ != 'button' and typ != 'submit':
                data[name] = inp.get('value', '')

        for sel in form.find_all('select'):
            name = sel.get('name', '')
            if name:
                selected = sel.find('option', selected=True)
                data[name] = selected.get('value', '') if selected else ''

        for ta in form.find_all('textarea'):
            name = ta.get('name', '')
            if name:
                data[name] = ta.string or ''

        # Set flag to "alterar" mode
        data['hdnFlagProcedimentoCadastro'] = '2'

        # Apply changes
        if descricao is not None:
            data['txtDescricao'] = descricao
        if observacoes is not None:
            data['txaObservacoes'] = observacoes

        # --- Fill required hidden fields from their select counterparts ---
        # SEI JS normally syncs these; we must do it manually.

        # Assuntos: hdnAssuntos must mirror selAssuntos options
        if not data.get('hdnAssuntos'):
            sel_a = soup.find('select', id='selAssuntos')
            if sel_a:
                vals = [o.get('value', '') for o in sel_a.find_all('option') if o.get('value')]
                data['hdnAssuntos'] = vals[0] if vals else ''
                if vals:
                    data['selAssuntos'] = vals[0]

        # Interessados: hdnInteressadosProcedimento must mirror selInteressadosProcedimento
        if not data.get('hdnInteressadosProcedimento'):
            sel_i = soup.find('select', id='selInteressadosProcedimento')
            if sel_i:
                vals = [o.get('value', '') for o in sel_i.find_all('option') if o.get('value')]
                data['hdnInteressadosProcedimento'] = vals[0] if vals else ''
                if vals:
                    data['selInteressadosProcedimento'] = vals[0]

        # POST — use _post which handles redirects
        r_save = self._post(action_url, data)
        self._control_html = None

        # After _follow, a successful save redirects to arvore_visualizar
        # Check the final URL or look for the process tree
        final_url = str(r_save.url)
        if 'arvore_visualizar' in final_url or 'procedimento_trabalhar' in final_url:
            return True
        # If still on the alter page, check for flag=1 (means form re-rendered = error)
        if 'hdnFlagProcedimentoCadastro' in r_save.text:
            flag_m = re.search(
                r'name="hdnFlagProcedimentoCadastro"[^>]*value="(\d)"',
                r_save.text,
            )
            if flag_m and flag_m.group(1) == '1':
                return False
        return True

    def get_full_document_tree(
        self, id_procedimento: str, *, expand_all: bool = True
    ) -> list[TreeDocument]:
        """Get complete document tree for a process, expanding lazy-loaded folders.

        Unlike get_process_documents(), this method:
        1. Parses folder metadata (Pastas[]) from the arvore JS
        2. POSTs to expand any folders with carregado=false
        3. Returns TreeDocument objects with download/view URLs (.src_url)

        Args:
            id_procedimento: Process ID.
            expand_all: If True, expand all unloaded folders. If False,
                        only return already-loaded documents.

        Returns:
            List of TreeDocument with src_url for download/viewing.
        """
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            return []

        all_docs: list[TreeDocument] = []

        # Parse folders from the tree JS
        folders = parse_tree_folders(arvore_html)

        # Parse already-loaded documents (from folders with carregado=true)
        loaded_docs = parse_expanded_folder(arvore_html, self._sei_url(""))
        all_docs.extend(loaded_docs)

        if expand_all:
            # Expand each unloaded folder via POST
            for folder in folders:
                if folder.carregado:
                    continue

                post_url = self._sei_url(folder.link)
                r = self._post(post_url, {
                    'hdnArvore': '',
                    'hdnPastaAtual': folder.folder_id,
                    'hdnProtocolos': folder.protocolos,
                })

                if r.text.startswith('OK'):
                    folder_docs = parse_expanded_folder(
                        r.text, self._sei_url("")
                    )
                    # Tag docs with their parent folder
                    for doc in folder_docs:
                        if not doc.parent_folder:
                            doc.parent_folder = folder.folder_id
                    all_docs.extend(folder_docs)

        return all_docs

    def download_document(
        self,
        doc: TreeDocument,
        output_path: str | None = None,
    ) -> bytes | str:
        """Download a document's content.

        For PDF/external documents (src_url contains documento_download_anexo):
            Returns binary PDF content. If output_path given, saves to file.
        For internal SEI documents (src_url contains documento_visualizar):
            Returns the rendered HTML content as text.

        Args:
            doc: TreeDocument from get_full_document_tree().
            output_path: Optional file path to save binary content.

        Returns:
            bytes for PDF downloads, str for HTML documents.
        """
        if not doc.src_url:
            raise ValueError(
                f"Document {doc.id_documento} ({doc.nome}) has no download URL"
            )

        r = self._get(doc.src_url)

        content_type = r.headers.get('content-type', '')

        if 'pdf' in content_type or 'octet-stream' in content_type:
            if output_path:
                with open(output_path, 'wb') as f:
                    f.write(r.content)
            return r.content

        # HTML content (internal SEI document)
        if 'html' in content_type:
            soup = BeautifulSoup(r.text, 'lxml')
            # Check if it's a login page (session expired)
            if soup.find('input', {'name': 'pwdSenha'}):
                raise RuntimeError(
                    "Session expired during document download. Re-login needed."
                )
            return r.text

        # Unknown type — return raw
        if output_path:
            with open(output_path, 'wb') as f:
                f.write(r.content)
        return r.content

    def read_document_content(
        self,
        doc: TreeDocument,
    ) -> str:
        """Read a document and return plain text content.

        Works for both internal SEI documents (HTML → text) and
        external PDFs (requires pdftotext).

        Args:
            doc: TreeDocument from get_full_document_tree().

        Returns:
            Plain text content of the document.
        """
        result = self.download_document(doc)

        if isinstance(result, str):
            # HTML content — extract text
            soup = BeautifulSoup(result, 'lxml')
            return soup.get_text('\n', strip=True)

        # Binary (PDF) — try pdftotext
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=True) as tmp:
            tmp.write(result)
            tmp.flush()
            proc = subprocess.run(
                ['pdftotext', '-layout', tmp.name, '-'],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                return proc.stdout
            raise RuntimeError(
                f"pdftotext failed for {doc.nome}: {proc.stderr}"
            )

    def delete_document(
        self,
        id_documento: str,
        id_procedimento: str,
    ) -> bool:
        """Delete an unsigned document from a process.

        Navigates to arvore_visualizar with the document selected, which
        exposes JS link variables including ``linkExcluirDocumento``.
        That URL is the direct delete action (the browser JS just does
        ``confirm()`` then ``location.href = linkExcluirDocumento``).

        Only works for documents created by the current unit that have NOT
        been signed.

        Args:
            id_documento: Document ID to delete.
            id_procedimento: Process ID containing the document.

        Returns:
            True if deletion succeeded.

        Raises:
            RuntimeError: If the document cannot be deleted.
        """
        # Step 1: Navigate to tree and find the doc link
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            raise RuntimeError("Could not navigate to process tree")

        # The doc might be inside a lazy-loaded folder — expand all
        from sei_cli.parsers import parse_tree_folders

        search_sources = [arvore_html]
        for folder in parse_tree_folders(arvore_html):
            if folder.carregado:
                continue
            r = self._post(self._sei_url(folder.link), {
                'hdnArvore': '',
                'hdnPastaAtual': folder.folder_id,
                'hdnProtocolos': folder.protocolos,
            })
            if id_documento in r.text:
                search_sources.append(r.text)

        # Step 2: Find arvore_visualizar link for this document
        sel_url = None
        for src in search_sources:
            m = re.search(
                rf'(controlador\.php\?acao=arvore_visualizar[^"]*'
                rf'id_documento={re.escape(id_documento)}[^"]*)',
                src,
            )
            if m:
                sel_url = self._sei_url(m.group(1).replace('&amp;', '&'))
                break

        if not sel_url:
            raise RuntimeError(
                f"Document {id_documento} not found in process tree. "
                "It may not exist or may be in a different unit."
            )

        # Step 3: Load arvore_visualizar with doc selected → get JS links
        r_sel = self._get(sel_url)

        # Step 4: Extract linkExcluirDocumento (direct delete URL)
        link_match = re.search(
            r"linkExcluirDocumento\s*=\s*'(controlador\.php[^']+)'",
            r_sel.text,
        )
        if not link_match:
            raise RuntimeError(
                f"Delete action not available for document {id_documento}. "
                "It may be signed or belong to another unit."
            )

        delete_url = self._sei_url(link_match.group(1).replace('&amp;', '&'))

        # Step 5: Execute the delete (single GET)
        r_delete = self._get(delete_url)
        self._control_html = None

        if 'erro' in r_delete.text.lower():
            raise RuntimeError("Delete failed: check SEI for details")

        return True

    def list_acompanhamento_especial(self) -> list[Process]:
        """List processes in 'Acompanhamento Especial'.

        Returns list of Process objects found on the acompanhamento page.
        """
        html = self._ensure_control()
        soup = BeautifulSoup(html, "lxml")

        acomp_url = None
        for a in soup.find_all("a", href=True):
            if "acompanhamento_listar" in a["href"]:
                acomp_url = urljoin(self._sei_url(""), a["href"])
                break

        if not acomp_url:
            acomp_url = self._menu_links.get("acompanhamento")
        if not acomp_url:
            return []

        r = self._get(acomp_url)
        self._control_html = None

        # Parse process links from the page
        procs: list[Process] = []
        asoup = BeautifulSoup(r.text, "lxml")
        for a in asoup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if "procedimento_trabalhar" not in href:
                continue
            id_m = re.search(r"id_procedimento=(\d+)", href)
            if not id_m:
                continue
            # Extract process number from link text (e.g. "08810035.004097/2025-01")
            numero = text.strip()
            if not re.match(r"\d{8}\.\d+/\d{4}-\d{2}", numero):
                continue
            procs.append(Process(
                numero=numero,
                tipo="Acompanhamento Especial",
                especificacao="",
                id_procedimento=id_m.group(1),
                link=urljoin(self._sei_url(""), href),
                novo=False,
            ))

        return procs

    def list_grupos_acompanhamento(self) -> list[tuple[str, str]]:
        """List available Acompanhamento Especial groups for current unit.

        Returns list of (group_id, group_name) tuples.
        """
        html = self._ensure_control()

        # Navigate to acompanhamento_cadastrar to access the grupo select
        cad = re.search(
            r'(controlador\.php\?acao=acompanhamento_cadastrar[^"\']+)', html
        )
        if not cad:
            return []

        r = self._get(self._sei_url(cad.group(1).replace("&amp;", "&")))
        soup = BeautifulSoup(r.text, "lxml")
        sel = soup.find("select", {"name": "selGrupoAcompanhamento"})
        if not sel:
            return []

        result = []
        for opt in sel.find_all("option"):
            val = opt.get("value", "")
            name = opt.get_text(strip=True)
            if val and val != "null" and name:
                result.append((val, name))
        return result

    def create_grupo_acompanhamento(self, nome: str) -> bool:
        """Create a new Acompanhamento Especial group in the current unit.

        Args:
            nome: Group name (e.g. 'Pessoal', 'Operacional').

        Returns:
            True if created successfully.
        """
        html = self._ensure_control()

        cad = re.search(
            r'(controlador\.php\?acao=acompanhamento_cadastrar[^"\']+)', html
        )
        if not cad:
            raise RuntimeError("Link acompanhamento_cadastrar not found")

        r_cad = self._get(self._sei_url(cad.group(1).replace("&amp;", "&")))
        grupo_url = re.search(
            r'(controlador\.php\?acao=grupo_acompanhamento_cadastrar[^"\']+)',
            r_cad.text,
        )
        if not grupo_url:
            raise RuntimeError("Link grupo_acompanhamento_cadastrar not found")

        r_form = self._get(
            self._sei_url(grupo_url.group(1).replace("&amp;", "&"))
        )
        soup = BeautifulSoup(r_form.text, "lxml")
        form = soup.find("form", id="frmGrupoAcompanhamentoCadastro")
        if not form:
            raise RuntimeError("Grupo cadastro form not found")

        action = self._sei_url(form["action"])
        data = {
            "hdnInfraTipoPagina": "2",
            "txtNome": nome,
            "hdnIdGrupoAcompanhamento": "",
            "sbmCadastrarGrupoAcompanhamento": "Salvar",
        }
        self._post(action, data)
        self._control_html = None
        return True

    def add_acompanhamento_especial(
        self, id_procedimento: str, grupo_id: str, observacao: str
    ) -> bool:
        """Add a process to Acompanhamento Especial.

        Flow: procedimento_trabalhar → ifrVisualizacao → acompanhamento_gerenciar → POST

        Args:
            id_procedimento: Process ID.
            grupo_id: Group ID from list_grupos_acompanhamento().
            observacao: Description text (required by SEI).

        Returns:
            True if added successfully.
        """
        html = self._ensure_control()

        # Navigate to process
        proc_link = re.search(
            rf'(controlador\.php\?acao=procedimento_trabalhar[^"]*'
            rf'id_procedimento={id_procedimento}[^"]*)',
            html,
        )
        if not proc_link:
            raise RuntimeError(
                f"Process {id_procedimento} not found in control page"
            )

        r = self._get(
            self._sei_url(proc_link.group(1).replace("&amp;", "&"))
        )

        # Get visualization iframe
        vis = re.search(
            r'src="(controlador\.php\?acao=procedimento_visualizar[^"]+)"',
            r.text,
        )
        if not vis:
            raise RuntimeError("Visualization iframe not found")

        r_vis = self._get(
            self._sei_url(vis.group(1).replace("&amp;", "&"))
        )

        # Get acompanhamento_gerenciar URL
        acomp = re.search(
            r'(controlador\.php\?acao=acompanhamento_gerenciar[^"\\]+)',
            r_vis.text,
        )
        if not acomp:
            raise RuntimeError("acompanhamento_gerenciar link not found")

        r_ger = self._get(
            self._sei_url(
                acomp.group(1).replace("&amp;", "&").replace("\\", "")
            )
        )

        soup = BeautifulSoup(r_ger.text, "lxml")
        form = soup.find("form", id="frmAcompanhamentoCadastro")
        if not form:
            raise RuntimeError(
                "Cadastro form not found (process may already be in "
                "Acompanhamento Especial)"
            )

        action = self._sei_url(form["action"])
        data = {
            "hdnInfraTipoPagina": "2",
            "selGrupoAcompanhamento": str(grupo_id),
            "txaObservacao": observacao,
            "hdnIdAcompanhamento": "",
            "hdnIdProtocolo": str(id_procedimento),
            "sbmCadastrarAcompanhamento": "Salvar",
        }

        r_add = self._post(action, data)
        self._control_html = None

        if (
            "Lista de Acompanhamentos" in r_add.text
            or "Acompanhamentos Especiais" in r_add.text
        ):
            return True

        return False

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

    def _get_blocos_page(self) -> tuple[str, "BeautifulSoup"]:
        """Navigate to blocos de assinatura page, return (url, soup)."""
        html = self._ensure_control()
        blocos_url = self._menu_links.get("blocos_assinatura")
        if not blocos_url:
            raise RuntimeError("Link de blocos de assinatura não encontrado no menu")
        r = self._get(blocos_url)
        self._control_html = None
        soup = BeautifulSoup(r.text, "lxml")
        return blocos_url, soup

    def _blocos_form_action(self, soup: "BeautifulSoup", action_name: str) -> str:
        """Extract a JS action URL from the blocos page (e.g. bloco_disponibilizar)."""
        pattern = rf"(controlador\.php\?acao={action_name}[^'\"]+)"
        match = re.search(pattern, str(soup))
        if not match:
            raise RuntimeError(f"URL de {action_name} não encontrada na página de blocos")
        return self._sei_url(match.group(1).replace("&amp;", "&"))

    def add_document_to_block(
        self,
        id_procedimento: str,
        id_documento: str,
        block_numero: str,
        *,
        disponibilizar: bool = False,
    ) -> dict:
        """Include a document in a bloco de assinatura.

        Uses the bloco_escolher page (accessible from the process tree) which
        lists all documents with checkboxes and a dropdown to select the target
        block. This approach works reliably because the URL hash is generated
        server-side in the tree.

        Args:
            id_procedimento: Process ID containing the document.
            id_documento: Document ID to include (SEI internal ID).
            block_numero: Block number (e.g. '871299').
            disponibilizar: If True, include AND make available in one step
                           (uses 'Incluir e Disponibilizar' button).

        Returns:
            dict with 'ok' bool and 'message'.

        Note:
            If the block is already disponibilizado, you must cancel the
            disponibilização first before editing or signing documents in it.
        """
        # Navigate to process → tree → bloco_escolher
        r = self._navigate_process_page(id_procedimento)
        soup = BeautifulSoup(r.text, "lxml")
        iframe = soup.find("iframe", {"name": "ifrArvore"})
        if not iframe:
            return {"ok": False, "message": "Árvore não encontrada"}

        arv_url = urljoin(self._sei_url(""), iframe["src"])
        r_arv = self._get(arv_url)

        # Find bloco_escolher URL (has valid hash with id_documento)
        chooser_match = re.search(
            r"(controlador\.php\?acao=bloco_escolher[^'\"]+)",
            r_arv.text,
        )
        if not chooser_match:
            return {"ok": False, "message": "Ação 'Incluir em Bloco de Assinatura' não encontrada na árvore"}

        chooser_url = self._sei_url(chooser_match.group(1).replace("&amp;", "&"))
        r_chooser = self._get(chooser_url)
        chooser_soup = BeautifulSoup(r_chooser.text, "lxml")

        # Find the form
        form = chooser_soup.find("form")
        if not form:
            return {"ok": False, "message": "Formulário 'Incluir em Bloco' não encontrado"}

        form_action = form.get("action", "")
        if not form_action:
            return {"ok": False, "message": "Form action não encontrado"}
        form_url = self._sei_url(form_action.replace("&amp;", "&"))

        # Verify the target block is in the dropdown
        sel = chooser_soup.find("select", {"name": "selBloco"})
        if sel:
            options = {opt.get("value"): opt.get_text(strip=True) for opt in sel.find_all("option")}
            if block_numero not in options:
                available = ", ".join(f"{v} ({k})" for k, v in options.items() if k != "null")
                return {
                    "ok": False,
                    "message": f"Bloco {block_numero} não disponível. Disponíveis: {available}",
                }

        # Find the checkbox for this document
        doc_checkbox = None
        for cb in chooser_soup.find_all("input", {"type": "checkbox"}):
            if cb.get("value") == id_documento:
                doc_checkbox = cb
                break

        # Build POST data from hidden inputs
        post_data = {}
        for inp in form.find_all("input"):
            name = inp.get("name", "")
            if not name:
                continue
            inp_type = inp.get("type", "")
            if inp_type == "hidden":
                post_data[name] = inp.get("value", "")
            elif inp_type == "checkbox" and inp.get("value") == id_documento:
                post_data[name] = id_documento

        post_data["selBloco"] = block_numero
        post_data["hdnDocumentosItensSelecionados"] = id_documento

        # Choose button: include only vs include and disponibilizar
        if disponibilizar:
            post_data["sbmIncluirDisponibilizar"] = "Incluir e Disponibilizar"
        else:
            post_data["sbmIncluir"] = "Incluir"

        r_submit = self._post(form_url, post_data)
        self._control_html = None

        # Verify success by checking if the block number appears in the Blocos column
        result_soup = BeautifulSoup(r_submit.text, "lxml")

        # Check for validation errors
        val = result_soup.find("textarea", {"id": "txaInfraValidacao"})
        if val and val.get_text(strip=True):
            return {"ok": False, "message": val.get_text(strip=True)[:200]}

        # Check if block_numero appears in result page
        for td in result_soup.find_all("td"):
            if block_numero in td.get_text():
                action = "incluído e disponibilizado" if disponibilizar else "incluído"
                return {
                    "ok": True,
                    "message": f"Documento {id_documento} {action} no bloco {block_numero}",
                }

        return {"ok": True, "message": f"Documento incluído no bloco {block_numero} (verificar)"}

    def devolver_block(self, block_numero: str) -> dict:
        """Return (devolver) a received bloco de assinatura to the sender unit.

        Only works on blocks that were received from another unit (estado=Recebido).
        After returning, the block goes back to the sender unit.

        Args:
            block_numero: Block number (e.g. '869251').

        Returns:
            dict with 'ok' bool and 'message'.
        """
        _, soup = self._get_blocos_page()
        form = soup.find("form", {"id": "frmBlocoLista"})
        if not form:
            return {"ok": False, "message": "Formulário de blocos não encontrado"}

        # Check if this block can be returned (has acaoRetornarBloco)
        retornar_pattern = re.compile(rf"acaoRetornarBloco\('{block_numero}'\)")
        if not retornar_pattern.search(str(soup)):
            # Check if block exists at all
            if block_numero not in str(soup):
                return {"ok": False, "message": f"Bloco {block_numero} não encontrado"}
            return {
                "ok": False,
                "message": f"Bloco {block_numero} não pode ser devolvido (somente blocos recebidos)",
            }

        retornar_url = self._blocos_form_action(soup, "bloco_retornar")

        fdata = {}
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            if name:
                fdata[name] = inp.get("value", "")

        fdata["hdnInfraItemId"] = block_numero

        r = self._post(retornar_url, fdata)
        self._control_html = None

        if r.status_code == 200:
            rsoup = BeautifulSoup(r.text, "lxml")

            # Check for validation/error
            val = rsoup.find("textarea", {"id": "txaInfraValidacao"})
            if val and val.get_text(strip=True):
                return {"ok": False, "message": val.get_text(strip=True)[:200]}

            # Check if block disappeared (returned successfully)
            if block_numero not in rsoup.get_text():
                return {"ok": True, "message": f"Bloco {block_numero} devolvido com sucesso"}

            # Check state
            for row in rsoup.find_all("tr", class_=["infraTrClara", "infraTrEscura"]):
                if block_numero in row.get_text():
                    tds = row.find_all("td")
                    if len(tds) > 4:
                        estado = tds[4].get_text(strip=True)
                        return {"ok": True, "message": f"Bloco {block_numero} devolvido — estado: {estado}"}

            return {"ok": True, "message": f"Bloco {block_numero} devolvido"}

        return {"ok": False, "message": f"Erro ao devolver bloco (status {r.status_code})"}

    def disponibilizar_block(self, block_numero: str) -> dict:
        """Make a bloco de assinatura available to the destination unit.

        Args:
            block_numero: Block number (e.g. '871299').

        Returns:
            dict with 'ok' bool and 'message'.
        """
        _, soup = self._get_blocos_page()
        form = soup.find("form", {"id": "frmBlocoLista"})
        if not form:
            return {"ok": False, "message": "Formulário de blocos não encontrado"}

        # Get the disponibilizar action URL from JS
        disp_url = self._blocos_form_action(soup, "bloco_disponibilizar")

        # Build form data
        fdata = {}
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            if name:
                fdata[name] = inp.get("value", "")

        fdata["hdnInfraItemId"] = block_numero

        r = self._post(disp_url, fdata)
        self._control_html = None

        # Check if we're back on the list page
        if r.status_code == 200:
            rsoup = BeautifulSoup(r.text, "lxml")
            # After disponibilizar, the block state changes to "Disponibilizado"
            for row in rsoup.find_all("tr", class_=["infraTrClara", "infraTrEscura"]):
                if block_numero in row.get_text():
                    tds = row.find_all("td")
                    if len(tds) > 4:
                        estado = tds[4].get_text(strip=True)
                        return {"ok": True, "message": f"Bloco {block_numero} — estado: {estado}"}

            return {"ok": True, "message": f"Bloco {block_numero} disponibilizado"}

        return {"ok": False, "message": f"Erro ao disponibilizar (status {r.status_code})"}

    def cancelar_disponibilizacao_block(self, block_numero: str) -> dict:
        """Cancel availability of a bloco de assinatura (retract from destination unit).

        Args:
            block_numero: Block number (e.g. '871299').

        Returns:
            dict with 'ok' bool and 'message'.
        """
        _, soup = self._get_blocos_page()
        form = soup.find("form", {"id": "frmBlocoLista"})
        if not form:
            return {"ok": False, "message": "Formulário de blocos não encontrado"}

        cancel_url = self._blocos_form_action(soup, "bloco_cancelar_disponibilizacao")

        fdata = {}
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name", "")
            if name:
                fdata[name] = inp.get("value", "")

        fdata["hdnInfraItemId"] = block_numero

        r = self._post(cancel_url, fdata)
        self._control_html = None

        if r.status_code == 200:
            rsoup = BeautifulSoup(r.text, "lxml")
            for row in rsoup.find_all("tr", class_=["infraTrClara", "infraTrEscura"]):
                if block_numero in row.get_text():
                    tds = row.find_all("td")
                    if len(tds) > 4:
                        estado = tds[4].get_text(strip=True)
                        return {"ok": True, "message": f"Bloco {block_numero} — estado: {estado}"}

            return {"ok": True, "message": f"Disponibilização do bloco {block_numero} cancelada"}

        return {"ok": False, "message": f"Erro ao cancelar disponibilização (status {r.status_code})"}

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

        # After switching, the response is a confirmation page, not the control
        # page. We need to explicitly load the control page to get process lists.
        status = parse_system_status(r2.text)
        self._current_unit_id = target.link
        control_url = self._sei_url(
            f"controlador.php?acao=procedimento_controlar"
            f"&infra_sistema=100000100&infra_unidade_atual={target.link}"
        )
        rc = self._get(control_url)
        self._control_html = rc.text
        self._menu_links = parse_menu_links(rc.text, self._sei_url(""))
        return parse_system_status(rc.text)

    # --- Search ---

    def search(self, query: str) -> str:
        """Quick search (pesquisa rápida).

        When given a SEI protocol/document number, navigates directly
        to that document or process. Returns raw HTML of the result page.
        """
        html = self._ensure_control()
        soup = BeautifulSoup(html, "lxml")

        pesq_form = soup.find("form", {"id": "frmProtocoloPesquisaRapida"})
        if not pesq_form:
            pesq_input = soup.find("input", {"id": "txtPesquisaRapida"})
            if pesq_input:
                pesq_form = pesq_input.find_parent("form")

        if not pesq_form:
            raise RuntimeError("Formulário de pesquisa não encontrado")

        action = pesq_form.get("action", "")
        search_url = urljoin(self._sei_url(""), action)

        r = self._post(search_url, data={"txtPesquisaRapida": query})
        self._control_html = None

        # Check if we were redirected to a process/document page
        final_url = str(r.url)
        if "procedimento_trabalhar" in final_url:
            # Landed on a process page — return it
            return r.text
        if "documento_visualizar" in final_url:
            # Landed on a document view — return it
            return r.text

        # Check for frameset — SEI often uses framesets
        rsoup = BeautifulSoup(r.text, "lxml")
        frame = rsoup.find("iframe", {"id": "ifrVisualizacao"})
        if frame and frame.get("src"):
            # Follow the iframe to get actual content
            iframe_url = urljoin(self._sei_url(""), frame["src"])
            ri = self._get(iframe_url)
            return ri.text

        return r.text

    def search_document(self, protocolo: str) -> tuple[str, str] | None:
        """Search for a document by its SEI protocol number.

        Uses pesquisa rápida to find a document and extracts
        id_documento and id_procedimento from the resulting page.

        Args:
            protocolo: SEI protocol number (e.g. '39701977').

        Returns:
            Tuple of (id_documento, id_procedimento) or None if not found.
        """
        html = self.search(protocolo)
        soup = BeautifulSoup(html, "lxml")

        # Check URL patterns in the page
        final_url = ""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "id_documento" in href:
                id_doc = re.search(r"id_documento=(\d+)", href)
                id_proc = re.search(r"id_procedimento=(\d+)", href)
                if id_doc and id_proc:
                    return (id_doc.group(1), id_proc.group(1))

        # Try extracting from any script or hidden field
        for pattern in [
            r'"id_documento":"(\d+)".*?"id_procedimento":"(\d+)"',
            r'id_documento=(\d+).*?id_procedimento=(\d+)',
        ]:
            m = re.search(pattern, html)
            if m:
                return (m.group(1), m.group(2))

        return None

    # --- New processes check ---

    def check_new_processes(self) -> list[Process]:
        """Return only processes marked as 'novo' (unread)."""
        procs = self.list_processes()
        return [p for p in procs.recebidos if p.novo]

    # --- Tramitação ---

    def get_tramitar_form(self, id_procedimento: str) -> TramitarForm:
        """Open 'Enviar Processo' form and parse destination units/fields."""
        rp = self._navigate_process_page(id_procedimento)
        send_url = self._extract_action_url(rp.text, "procedimento_enviar")
        if not send_url:
            raise RuntimeError("Ação 'Enviar Processo' não encontrada na página do processo")

        rsend = self._get(send_url)
        tramitar = parse_tramitar_form(rsend.text, self._sei_url(""), str(rsend.url))
        return tramitar

    def list_unidades_destino_tramitacao(self, id_procedimento: str) -> list[Unit]:
        """List units available in the process send form."""
        form = self.get_tramitar_form(id_procedimento)
        return [Unit(sigla=d.nome, descricao=d.nome, link=d.id_unidade) for d in form.destinos]

    def enviar_processo(
        self,
        id_procedimento: str,
        unidade_destino: str,
        manter_aberto: bool = True,
    ) -> bool:
        """Send process to another unit."""
        form = self.get_tramitar_form(id_procedimento)
        target = None
        kw = unidade_destino.lower().strip()
        for dest in form.destinos:
            if kw == dest.id_unidade or kw in dest.nome.lower():
                target = dest
                break
        if not target:
            opts = ", ".join(d.nome for d in form.destinos[:15])
            raise RuntimeError(
                f"Unidade destino '{unidade_destino}' não encontrada. "
                f"Algumas opções: {opts}"
            )

        data: dict[str, str] = {}
        data.update(form.hidden_fields)
        data.update(form.select_fields)
        data[form.destino_field] = target.id_unidade
        if form.manter_aberto_field and manter_aberto:
            data[form.manter_aberto_field] = "S"

        r = self._post(form.action, data)
        self._control_html = None
        lower = r.text.lower()
        if "erro" in lower or "falha" in lower:
            return False
        return True

    def tramitar_processo(
        self,
        id_procedimento: str,
        unidade_destino: str,
        manter_aberto: bool = True,
    ) -> bool:
        """Alias de enviar_processo para API mais explícita."""
        return self.enviar_processo(
            id_procedimento=id_procedimento,
            unidade_destino=unidade_destino,
            manter_aberto=manter_aberto,
        )

    # --- Marcadores ---

    def list_marcadores(self) -> list[Marcador]:
        """List marker catalog available to current unit."""
        html = self._ensure_control()
        marcadores_url = self._menu_links.get("marcadores")
        if not marcadores_url:
            marcadores_url = self._extract_action_url(html, "marcador_listar")
        if not marcadores_url:
            return []

        r = self._get(marcadores_url)
        self._control_html = None
        return parse_marcadores_list(r.text, self._sei_url(""))

    def set_marcador(self, id_procedimento: str, marcador_id: str, texto: str = "") -> bool:
        """Apply marker to a process.

        Navigates: process tree → Nos[0] toolbar → andamento_marcador_gerenciar
        → "Adicionar" button → andamento_marcador_cadastrar form → POST.

        Args:
            id_procedimento: Process ID.
            marcador_id: Marker ID from the select (e.g. '64956' for Diárias).
            texto: Description text for the marker.

        Returns:
            True if the marker was applied successfully.
        """
        # Step 1: Navigate to tree and get gerenciar URL from toolbar
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            raise RuntimeError("Could not navigate to process tree")

        start = arvore_html.find('Nos[0]')
        end = arvore_html.find('Nos[1]', start)
        nos0 = arvore_html[start:end].replace('\\"', '"')

        ger_m = re.search(
            r'href="(controlador\.php\?acao=andamento_marcador_gerenciar[^"]*)"',
            nos0,
        )
        if not ger_m:
            raise RuntimeError("Gerenciar Marcador action not found in toolbar")

        # Step 2: Go to gerenciar page (lists existing marcadores)
        r_ger = self._get(self._sei_url(ger_m.group(1).replace('&amp;', '&')))

        # Step 3: Find the "Adicionar" button → andamento_marcador_cadastrar
        add_m = re.search(
            r'(controlador\.php\?acao=andamento_marcador_cadastrar[^"\']+)',
            r_ger.text,
        )
        if not add_m:
            raise RuntimeError("Adicionar marcador link not found")

        # Step 4: Load the cadastrar form
        r_cad = self._get(self._sei_url(add_m.group(1).replace('&amp;', '&')))

        soup = BeautifulSoup(r_cad.text, 'lxml')
        form = soup.find('form', id='frmAndamentoMarcadorCadastro')
        if not form:
            raise RuntimeError("Marcador cadastro form not found")

        action_url = urljoin(self._sei_url(""), form['action'])

        # Step 5: POST with marcador data
        data = {
            'hdnInfraTipoPagina': '2',
            'selMarcador': marcador_id,
            'hdnIdMarcador': marcador_id,
            'txaTexto': texto,
            'hdnIdProtocolo': id_procedimento,
            'sbmSalvar': 'Salvar',
        }

        r_save = self._post(action_url, data)
        self._control_html = None

        # Success: redirects to gerenciar (200 with table showing the marker)
        # or shows the form again (error)
        return marcador_id in r_save.text or 'andamento_marcador_gerenciar' in str(r_save.url)

    def remove_marcador(self, id_procedimento: str) -> bool:
        """Remove marker from a process."""
        rp = self._navigate_process_page(id_procedimento)
        rm_url = self._extract_action_url(rp.text, "andamento_marcador_remover")
        if not rm_url:
            control_html = self._ensure_control()
            rm_url = self._extract_action_url(control_html, "andamento_marcador_remover")
        if not rm_url:
            raise RuntimeError("Ação de remoção de marcador não encontrada")

        rr = self._get(rm_url)
        rsoup = BeautifulSoup(rr.text, "lxml")
        form = rsoup.find("form")
        if form:
            action = urljoin(str(rr.url), form.get("action", ""))
            data: dict[str, str] = {}
            for inp in form.find_all("input"):
                n = inp.get("name", "")
                if n:
                    data[n] = inp.get("value", "")
            rr = self._post(action, data)

        self._control_html = None
        lower = rr.text.lower()
        if "erro" in lower or "falha" in lower:
            return False
        return True

    # --- Document creation & editing ---

    # Maps friendly name → SEI id_serie (from frmDocumentoEscolherTipo)
    DOC_TYPES: dict[str, str] = {
        "externo": "-1",
        "analise_riscos": "220",
        "autorizacao": "305",
        "declaracao": "83",
        "despacho_diligencial": "377",
        "despacho": "5",
        "dfd": "970",
        "encaminhamento": "327",
        "etp": "1170",
        "informacao": "92",
        "justificativa": "307",
        "memorando": "12",
        "minuta_portaria": "235",
        "oficio": "11",
        "parecer": "191",
        "parte_generica": "292",
        "plano_trabalho": "669",
        "relatorio_viagem": "326",
        "solicitacao_providencias": "347",
        "solicitacao": "178",
        "termo_referencia": "214",
    }

    def list_document_types(self, id_procedimento: str) -> list[DocumentType]:
        """List available document types for a process.

        Navigates to the process → extracts 'Incluir Documento' URL from
        the arvore toolbar → GETs the type selection page → parses the
        onclick escolher(id) calls.
        """
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            return []

        # Find 'Incluir Documento' href (next to documento_incluir.svg icon)
        href_match = re.search(
            r'href="([^"]+)"[^>]*>\s*<img\s+[^>]*documento_incluir',
            arvore_html,
        )
        if not href_match:
            return []

        incl_url = urljoin(self._sei_url(""), href_match.group(1))
        rtype = self._get(incl_url)

        # Parse onclick="escolher(ID)" + link text
        types: list[DocumentType] = []
        tsoup = BeautifulSoup(rtype.text, "lxml")
        for a in tsoup.find_all("a"):
            onclick = a.get("onclick", "")
            m = re.match(r"escolher\((-?\d+)\)", onclick)
            if m:
                types.append(DocumentType(
                    id_serie=m.group(1),
                    nome=a.text.strip(),
                ))
        return types

    def create_document(
        self,
        id_procedimento: str,
        tipo: str,
        *,
        nivel_acesso: str = "0",  # 0=Público, 1=Restrito, 2=Sigiloso
        texto_inicial: str = "N",  # N=Nenhum, T=Texto Padrão, D=Documento Modelo
        descricao: str = "",
        interessados: str = "",
    ) -> DocumentCreated:
        """Create a new document inside a process.

        Args:
            id_procedimento: Process ID.
            tipo: Document type key (e.g. 'despacho', 'oficio') or numeric id_serie.
            nivel_acesso: '0' (Público), '1' (Restrito), '2' (Sigiloso).
            texto_inicial: 'N' (Nenhum), 'T' (Texto Padrão), 'D' (Documento Modelo).
            descricao: Optional description field.
            interessados: Optional interested party.

        Returns:
            DocumentCreated with id_documento and editor URL.
        """
        # Resolve tipo to id_serie
        id_serie = self.DOC_TYPES.get(tipo.lower().replace(" ", "_"), tipo)

        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            raise RuntimeError("Não foi possível acessar a árvore do processo")

        # Step 1: Get 'Incluir Documento' URL
        href_match = re.search(
            r'href="([^"]+)"[^>]*>\s*<img\s+[^>]*documento_incluir',
            arvore_html,
        )
        if not href_match:
            raise RuntimeError("Link 'Incluir Documento' não encontrado na árvore")

        incl_url = urljoin(self._sei_url(""), href_match.group(1))
        rtype = self._get(incl_url)

        # Step 2: Submit type selection form (escolher(id_serie))
        tsoup = BeautifulSoup(rtype.text, "lxml")
        form = tsoup.find("form", id="frmDocumentoEscolherTipo")
        if not form:
            raise RuntimeError("Formulário de escolha de tipo não encontrado")

        form_action = urljoin(self._sei_url(""), form["action"])
        fdata: dict[str, str] = {}
        for inp in form.find_all("input"):
            n = inp.get("name", "")
            if n:
                fdata[n] = inp.get("value", "")
        fdata["hdnIdSerie"] = id_serie

        rcadastro = self._post(form_action, fdata)
        csoup = BeautifulSoup(rcadastro.text, "lxml")

        # Step 3: Fill creation form (frmDocumentoCadastro)
        cform = csoup.find("form", id="frmDocumentoCadastro")
        if not cform:
            raise RuntimeError(
                "Formulário de cadastro não encontrado. "
                f"Tipo '{tipo}' (id_serie={id_serie}) pode não estar disponível."
            )

        cform_action = urljoin(self._sei_url(""), cform["action"])
        cdata: dict[str, str] = {}
        for inp in cform.find_all("input"):
            n = inp.get("name", "")
            if n:
                cdata[n] = inp.get("value", "")
        for sel in cform.find_all("select"):
            n = sel.get("name", "")
            if n:
                selected = sel.find("option", selected=True)
                cdata[n] = selected["value"] if selected else ""

        # Set our values
        # CRITICAL: submeter() JS sets hdnFlagDocumentoCadastro='2' before submit.
        # Without this, SEI just re-renders the form instead of creating the doc.
        cdata["hdnFlagDocumentoCadastro"] = "2"
        cdata["rdoTextoInicial"] = texto_inicial
        cdata["rdoNivelAcesso"] = nivel_acesso
        cdata["rdoFormato"] = "N"  # Nato-digital
        if descricao:
            cdata["txtDescricao"] = descricao
        if interessados:
            cdata["txtInteressado"] = interessados

        # Submit creation
        rcreated = self._post(cform_action, cdata)

        # After creation, SEI redirects to the editor page or back to arvore.
        # The response should contain the new document ID.
        self._control_html = None

        # Parse the response for the new document
        created_soup = BeautifulSoup(rcreated.text, "lxml")

        # If redirected to editor_montar, extract doc ID from URL
        id_doc = ""
        editor_url = None
        url_str = str(rcreated.url)
        id_doc_match = re.search(r"id_documento=(\d+)", url_str)
        if id_doc_match:
            id_doc = id_doc_match.group(1)
            editor_url = url_str

        # Also check the HTML for id_documento
        if not id_doc:
            id_doc_match = re.search(r"id_documento=(\d+)", rcreated.text)
            if id_doc_match:
                id_doc = id_doc_match.group(1)

        # Extract editor URL if present
        if not editor_url:
            editor_match = re.search(
                r'controlador\.php\?acao=editor_montar[^"\']+id_documento=' + id_doc,
                rcreated.text,
            )
            if editor_match:
                editor_url = urljoin(self._sei_url(""), editor_match.group())

        tipo_nome = next(
            (dt.nome for dt in [DocumentType(id_serie, tipo)]
             if dt.id_serie == id_serie),
            tipo,
        )

        return DocumentCreated(
            id_documento=id_doc,
            id_procedimento=id_procedimento,
            tipo=tipo_nome,
            editor_url=editor_url,
        )

    def get_editor_sections(
        self, id_documento: str, id_procedimento: str
    ) -> tuple[str, list[EditorSection]]:
        """Load the editor page for a document and return its sections.

        Returns:
            Tuple of (editor_save_url, list of EditorSection).
            Each section has name, content (HTML), and section_id.
        """
        editor_url = self._get_editor_url(id_documento, id_procedimento)
        if not editor_url:
            raise RuntimeError(
                f"Editor URL não encontrada para documento {id_documento}"
            )

        re_edit = self._get(editor_url)

        # Check if document is signed (not editable)
        if "assinado" in re_edit.text and "não pode" in re_edit.text:
            raise RuntimeError("Documento já assinado — não pode ser editado")

        # Extract form action (editor_salvar URL with infra_hash)
        form_match = re.search(
            r'action="(editor/editor_processar\.php\?acao=editor_salvar[^"]+)"',
            re_edit.text,
        )
        if not form_match:
            raise RuntimeError("URL de salvamento do editor não encontrada")
        save_url = urljoin(self._sei_url(""), form_match.group(1))

        # Extract textarea sections
        sections: list[EditorSection] = []
        for m in re.finditer(
            r'<textarea[^>]*name="(txaEditor_(\d+))"[^>]*>(.*?)</textarea>',
            re_edit.text,
            re.DOTALL,
        ):
            sections.append(EditorSection(
                name=m.group(1),
                content=m.group(3),
                section_id=m.group(2),
            ))

        # Extract hidden fields too (needed for save)
        self._editor_hiddens: dict[str, str] = {}
        esoup = BeautifulSoup(re_edit.text, "lxml")
        form = esoup.find("form", id="frmEditor")
        if form:
            for inp in form.find_all("input", {"type": "hidden"}):
                n = inp.get("name", "")
                if n:
                    self._editor_hiddens[n] = inp.get("value", "")

        return save_url, sections

    def save_document(
        self,
        save_url: str,
        sections: list[EditorSection],
    ) -> bool:
        """Save document content by POSTing the editor form.

        Args:
            save_url: The editor_salvar URL (from get_editor_sections).
            sections: List of EditorSection with modified content.

        Returns:
            True if save succeeded.
        """
        data: dict[str, str] = {}

        # Include hidden fields from editor form
        data.update(getattr(self, "_editor_hiddens", {}))

        # Add all sections as textarea values
        for sec in sections:
            data[sec.name] = sec.content

        r = self._post(save_url, data)

        # editor_salvar typically returns a small page loaded into ifrEditorSalvar
        # with a success indicator or error message
        self._control_html = None

        # Check for errors
        if "erro" in r.text.lower() or "falha" in r.text.lower():
            return False

        return True

    def view_document_html(
        self, id_documento: str, id_procedimento: str
    ) -> str:
        """View a document's rendered HTML (works for signed documents too).

        Uses documento_imprimir_web which renders the full document
        including signed ones that can't be opened in the editor.

        Args:
            id_documento: Internal document ID.
            id_procedimento: Process ID containing the document.

        Returns:
            Raw HTML content of the document body.
        """
        # Navigate to the process tree to establish session context
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            raise RuntimeError(
                f"Processo {id_procedimento} não encontrado"
            )

        # Find the documento_imprimir_web URL with infra_hash from the tree
        print_match = re.search(
            rf'(controlador\.php\?acao=documento_imprimir_web[^"]*'
            rf'id_documento={id_documento}[^"]*)',
            arvore_html,
        )

        if not print_match:
            # Fallback: try documento_visualizar
            vis_match = re.search(
                rf'(controlador\.php\?acao=documento_visualizar[^"]*'
                rf'id_documento={id_documento}[^"]*)',
                arvore_html,
            )
            if vis_match:
                r = self._get(self._sei_url(vis_match.group(1)))
                if "login.php" not in str(r.url):
                    return r.text
            raise RuntimeError(
                f"Link de visualização não encontrado para documento {id_documento}"
            )

        r = self._get(self._sei_url(print_match.group(1)))

        # Check for login redirect
        if "login.php" in str(r.url) or "pwdSenha" in r.text:
            raise RuntimeError(
                "Session expired viewing document. Re-login needed."
            )

        return r.text

    def view_document(
        self, id_documento: str, id_procedimento: str
    ) -> str:
        """View a document as plain text (works for signed documents too).

        Args:
            id_documento: Internal document ID.
            id_procedimento: Process ID containing the document.

        Returns:
            Plain text content of the document.
        """
        html = self.view_document_html(id_documento, id_procedimento)
        soup = BeautifulSoup(html, "lxml")

        # Remove timbre/header images
        for img in soup.find_all("img"):
            img.decompose()

        # Remove navigation/chrome elements
        for tag_id in ["divInfraAreaGlobal", "navInfraBarraNavegacao"]:
            tag = soup.find(id=tag_id)
            if tag:
                tag.decompose()

        return soup.get_text("\n", strip=True)

    def view_document_sections(
        self, id_documento: str, id_procedimento: str
    ) -> list[EditorSection]:
        """Extract document sections from the print view (works for signed docs).

        Returns sections similar to get_editor_sections() but read-only,
        extracted from the rendered HTML rather than the editor form.

        Args:
            id_documento: Internal document ID.
            id_procedimento: Process ID.

        Returns:
            List of EditorSection with content (HTML of each section).
        """
        html = self.view_document_html(id_documento, id_procedimento)
        soup = BeautifulSoup(html, "lxml")

        sections: list[EditorSection] = []

        # documento_imprimir_web renders sections as divs with id="txaEditor_NNN"
        # or directly as content divs
        for div in soup.find_all(
            lambda tag: tag.get("id", "").startswith("txaEditor_")
                        or tag.get("name", "").startswith("txaEditor_")
        ):
            sec_id = re.search(r'(\d+)', div.get("id", div.get("name", "")))
            if sec_id:
                inner = "".join(str(child) for child in div.children)
                sections.append(EditorSection(
                    name=f"txaEditor_{sec_id.group(1)}",
                    content=inner,
                    section_id=sec_id.group(1),
                ))

        # Fallback: if no txaEditor divs found, extract from the print layout
        if not sections:
            # The print view has the document body in a specific structure
            # Look for the main content area
            body = soup.find("body")
            if body:
                inner = "".join(str(child) for child in body.children)
                sections.append(EditorSection(
                    name="body",
                    content=inner,
                    section_id="0",
                ))

        return sections

    def read_document(
        self, id_documento: str, id_procedimento: str
    ) -> str:
        """Read a document's body content as plain text.

        Tries the editor first (for unsigned docs), falls back to
        the print view (for signed docs).
        """
        from html import unescape as _unescape
        try:
            save_url, sections = self.get_editor_sections(
                id_documento, id_procedimento
            )
            if not sections:
                raise RuntimeError("empty")
            body = max(sections, key=lambda s: len(s.content))
            content = _unescape(body.content)
            soup = BeautifulSoup(content, "lxml")
            for img in soup.find_all("img"):
                img.decompose()
            return soup.get_text("\n", strip=True)
        except RuntimeError:
            # Fallback: signed document — use print view
            return self.view_document(id_documento, id_procedimento)

    def read_relatorio(
        self, id_documento: str, id_procedimento: str
    ) -> RelatorioServico:
        """Read and parse a Relatório de Serviço Operacional.

        Returns a structured RelatorioServico with personnel, vehicles,
        occurrences, etc.
        """
        from html import unescape as _unescape
        save_url, sections = self.get_editor_sections(id_documento, id_procedimento)
        if not sections:
            raise RuntimeError(f"Documento {id_documento} não tem conteúdo")

        # The body is typically the section with most content (not timbre/footer)
        # Find it — exclude very short sections (title, footer)
        body_candidates = [s for s in sections if len(s.content) > 1000]
        if not body_candidates:
            body_candidates = sections

        # Pick the one that contains "RELATÓRIO" or "Fiscal" keywords
        body_sec = None
        for s in body_candidates:
            if "Fiscal" in s.content or "RELAT" in s.content:
                body_sec = s
                break
        if not body_sec:
            body_sec = max(body_candidates, key=lambda s: len(s.content))

        return parse_relatorio(body_sec.content)

    def batch_read_relatorios(
        self,
        id_procedimento: str,
        unit: str = "OP 3",
    ) -> dict[str, Any]:
        """Read and summarize all relatório-like documents from a process."""
        if unit:
            self.switch_unit(unit)

        docs = self.get_process_documents(id_procedimento)
        rel_docs = [
            d for d in docs
            if any(
                k in (d.nome or "").upper()
                for k in ("RELAT", "LIVRO", "FISCAL")
            )
        ]

        parsed: list[RelatorioServico] = []
        failures: list[dict[str, str]] = []
        for doc in rel_docs:
            if not doc.id_documento:
                continue
            try:
                parsed.append(self.read_relatorio(doc.id_documento, id_procedimento))
            except Exception as exc:
                failures.append(
                    {
                        "id_documento": doc.id_documento,
                        "nome": doc.nome,
                        "erro": str(exc),
                    }
                )

        md = summarize_batch(parsed)
        return {
            "id_procedimento": id_procedimento,
            "unit": unit,
            "total_documentos": len(docs),
            "relatorios_encontrados": len(rel_docs),
            "relatorios_lidos": len(parsed),
            "falhas": failures,
            "resumo_markdown": md,
            "relatorios": [r.__dict__ for r in parsed],
        }

    def _navigate_to_arvore(self, id_procedimento: str) -> str | None:
        """Navigate to a process and return the arvore HTML.

        Tries multiple strategies:
        1. Direct link from control page (recebidos/gerados)
        2. Search in Acompanhamento Especial
        3. Pesquisa Rápida fallback
        """
        html = self._ensure_control()
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: Direct link from control page
        proc_link = None
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if "procedimento_trabalhar" in href and id_procedimento in href:
                proc_link = urljoin(self._sei_url(""), href)
                break

        if not proc_link:
            # Strategy 2: Try Acompanhamento Especial
            proc_link = self._find_in_acompanhamento(id_procedimento)

        if not proc_link:
            return None

        rp = self._get(proc_link)
        psoup = BeautifulSoup(rp.text, "lxml")
        iframe = psoup.find("iframe", {"name": "ifrArvore"})
        if not iframe or not iframe.get("src"):
            return None

        arvore_url = urljoin(self._sei_url(""), iframe["src"])
        ra = self._get(arvore_url)
        self._control_html = None
        return ra.text

    def _find_in_acompanhamento(self, id_procedimento: str) -> str | None:
        """Search for a process link in Acompanhamento Especial."""
        html = self._ensure_control()
        soup = BeautifulSoup(html, "lxml")

        acomp_url = None
        for a in soup.find_all("a", href=True):
            if "acompanhamento_listar" in a["href"]:
                acomp_url = urljoin(self._sei_url(""), a["href"])
                break

        if not acomp_url:
            return None

        r = self._get(acomp_url)
        asoup = BeautifulSoup(r.text, "lxml")

        for a in asoup.find_all("a", href=True):
            href = a["href"]
            if "procedimento_trabalhar" in href and id_procedimento in href:
                self._control_html = None
                return urljoin(self._sei_url(""), href)

        self._control_html = None
        return None

    def _get_editor_url(
        self, id_documento: str, id_procedimento: str
    ) -> str | None:
        """Get the editor_montar URL for a document."""
        arvore_html = self._navigate_to_arvore(id_procedimento)
        if not arvore_html:
            return None

        # Find the document's arvore_visualizar URL
        doc_pattern = re.compile(
            rf'controlador\.php\?acao=arvore_visualizar[^"]*id_documento={id_documento}[^"]*'
        )
        doc_match = doc_pattern.search(arvore_html)
        if not doc_match:
            return None

        doc_url = urljoin(self._sei_url(""), doc_match.group())
        rd = self._get(doc_url)

        # Extract linkEditarConteudo
        edit_match = re.search(
            r"var\s+linkEditarConteudo\s*=\s*'([^']+)'", rd.text
        )
        if not edit_match:
            return None

        return urljoin(self._sei_url(""), edit_match.group(1))

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
