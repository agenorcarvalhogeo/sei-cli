"""Browser-based document editor for SEI.

Uses Playwright to open the CKEditor, inject formatted HTML content,
and save. This is needed because SEI's editor_salvar endpoint requires
the save to come from within the CKEditor iframe context.

Flow:
1. Login via HTTP (fast, reuse existing SEIClient session)
2. Transfer cookies to Playwright browser
3. Navigate to editor_montar URL
4. Wait for CKEditor to initialize
5. Inject content via CKEDITOR.instances[name].setData()
6. Click Save button
7. Wait for save confirmation
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from sei_cli.client import SEIClient


def _get_ckeditor_instance_names(page_html: str) -> list[str]:
    """Extract CKEditor textarea names from editor page HTML."""
    names = []
    for m in re.finditer(r'<textarea[^>]*name="(txaEditor_\d+)"', page_html):
        names.append(m.group(1))
    return names


def _identify_body_section(sections: dict[str, str]) -> str | None:
    """Identify the main body section (not timbre, title, footer, reference).
    
    Heuristic: the body section contains template variables like
    'Processo' or 'interessado', OR is the middle editable section.
    """
    candidates = list(sections.keys())
    if len(candidates) <= 2:
        return candidates[-1] if candidates else None
    
    # Skip first (timbre) and last (reference/footer)
    middle = candidates[1:-1]
    
    for name in middle:
        content = sections[name].lower()
        if "processo" in content and "interessado" in content:
            return name
    
    # Fallback: pick the one that looks like body text
    # (not the title section which is short)
    for name in middle:
        if len(sections[name]) > 200:
            return name
    
    return middle[0] if middle else None


def html_from_docx(docx_path: str) -> str:
    """Convert a .docx file to HTML preserving formatting.
    
    Uses pandoc for conversion. The resulting HTML uses inline styles
    that SEI's CKEditor will accept.
    """
    result = subprocess.run(
        ["pandoc", docx_path, "-f", "docx", "-t", "html", "--standalone"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed: {result.stderr}")
    
    html = result.stdout
    # Extract just the body content
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
    if m:
        html = m.group(1).strip()
    
    return html


def format_for_sei(content: str, css_class: str = "Texto_Justificado_Recuo_Primeira_Linha") -> str:
    """Wrap plain text or simple HTML in SEI-compatible paragraph tags.
    
    If content already has <p> tags with SEI classes, returns as-is.
    Otherwise wraps each paragraph in the specified CSS class.
    """
    if "Texto_Justificado" in content or "Texto_Centralizado" in content:
        return content
    
    # Split into paragraphs and wrap
    paragraphs = content.split("\n\n") if "\n\n" in content else content.split("\n")
    wrapped = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith("<p"):
            wrapped.append(p)
        else:
            wrapped.append(f'<p class="{css_class}">{p}</p>')
    
    return "\n\n".join(wrapped)


def edit_document_browser(
    client: SEIClient,
    id_documento: str,
    id_procedimento: str,
    content: str,
    section_name: str | None = None,
    *,
    timeout_ms: int = 30000,
) -> bool:
    """Edit a document using browser automation via Playwright.
    
    Args:
        client: Authenticated SEIClient (cookies will be transferred).
        id_documento: Document ID to edit.
        id_procedimento: Process ID containing the document.
        content: HTML content to inject into the body section.
        section_name: Specific textarea name (e.g. 'txaEditor_217').
                     If None, auto-detects the body section.
        timeout_ms: Max wait time for CKEditor to load.
    
    Returns:
        True if save succeeded.
    """
    from playwright.sync_api import sync_playwright
    
    # Try to get editor URL via HTTP; fall back to building it
    editor_url = None
    try:
        editor_url = client._get_editor_url(id_documento, id_procedimento)
    except Exception:
        pass
    
    # Get cookies from httpx client
    cookies = []
    for cookie in client.client.cookies.jar:
        cookies.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or "sei.rn.gov.br",
            "path": cookie.path or "/",
        })
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        
        # Transfer cookies
        context.add_cookies(cookies)
        
        page = context.new_page()
        
        if editor_url:
            # Direct navigation to editor
            page.goto(editor_url, wait_until="networkidle", timeout=timeout_ms)
        else:
            # Full navigation: login page → control → process → doc → editor
            # First check if cookies give us a valid session
            page.goto(
                f"{client.base_url}/sei/controlador.php?acao=procedimento_trabalhar"
                f"&id_procedimento={id_procedimento}",
                wait_until="networkidle",
                timeout=timeout_ms,
            )
            
            # If redirected to login, do browser login
            if "login" in page.url.lower():
                from sei_cli.config import load_credentials
                creds = load_credentials()
                page.goto(
                    f"{client.base_url}/sei/controlador.php?acao=usuario_login",
                    wait_until="networkidle",
                    timeout=timeout_ms,
                )
                page.fill("#txtUsuario", creds.usuario)
                page.fill("#pwdSenha", creds.senha)
                # Select orgao
                page.select_option("select[name='selOrgao']", creds.orgao)
                page.click("button[name='sbmLogin'], input[type='submit']")
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
                
                # Navigate to process
                page.goto(
                    f"{client.base_url}/sei/controlador.php?acao=procedimento_trabalhar"
                    f"&id_procedimento={id_procedimento}",
                    wait_until="networkidle",
                    timeout=timeout_ms,
                )
            
            # Find the document in the tree iframe and get its editor link
            tree_frame = page.frame("ifrArvore")
            if tree_frame:
                # Click on the document to open it
                doc_link = tree_frame.locator(f"a[href*='id_documento={id_documento}']").first
                doc_link.click()
                page.wait_for_timeout(2000)
                
                # Now find and click the edit button in the visualization frame
                vis_frame = page.frame("ifrVisualizacao")
                if vis_frame:
                    edit_btn = vis_frame.locator("a[href*='editor_montar'], img[alt*='Editar']").first
                    edit_btn.click()
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
        
        # At this point we should be on the editor page
        # Wait for CKEditor to be ready
        page.wait_for_function(
            "() => typeof CKEDITOR !== 'undefined' && Object.keys(CKEDITOR.instances).length > 0",
            timeout=timeout_ms,
        )
        
        # Get CKEditor instance names
        instances = page.evaluate("() => Object.keys(CKEDITOR.instances)")
        
        if not instances:
            browser.close()
            raise RuntimeError("No CKEditor instances found")
        
        # Determine which section to edit
        if section_name and section_name in instances:
            target = section_name
        else:
            # Auto-detect body section
            sections_content = page.evaluate("""() => {
                const result = {};
                for (const name of Object.keys(CKEDITOR.instances)) {
                    result[name] = CKEDITOR.instances[name].getData();
                }
                return result;
            }""")
            target = _identify_body_section(sections_content) or section_name
            if not target:
                target = instances[1] if len(instances) > 1 else instances[0]
        
        # Inject content
        page.evaluate(f"""(content) => {{
            CKEDITOR.instances['{target}'].setData(content);
        }}""", content)
        
        # Small delay for CKEditor to process
        page.wait_for_timeout(500)
        
        # Click Save via CKEditor command (more reliable than clicking button)
        page.evaluate(f"""() => {{
            CKEDITOR.instances['{target}'].execCommand('save');
        }}""")
        
        # Wait for save response in iframe
        page.wait_for_timeout(3000)
        
        # Check if save succeeded by looking at iframe content
        try:
            iframe_content = page.evaluate("""() => {
                try {
                    const iframe = document.getElementById('ifrEditorSalvar');
                    if (iframe && iframe.contentWindow) {
                        return iframe.contentWindow.document.body.textContent || '';
                    }
                } catch(e) {}
                return '';
            }""")
            success = iframe_content.strip().startswith("OK")
        except Exception:
            success = True  # Assume success if we can't check
        
        browser.close()
        return success


def edit_document_with_docx(
    client: SEIClient,
    id_documento: str,
    id_procedimento: str,
    docx_path: str,
    section_name: str | None = None,
) -> bool:
    """Edit document using content from a .docx file.
    
    Converts docx to HTML, wraps in SEI CSS classes, then injects
    via browser automation.
    """
    html = html_from_docx(docx_path)
    sei_html = format_for_sei(html)
    return edit_document_browser(
        client, id_documento, id_procedimento, sei_html, section_name
    )
