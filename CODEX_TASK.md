# Codex Task: Fix check_reopen_available() — Wrong Source of Truth

## Context

Read `.context/CONTEXT.md` first for project overview.

We're fixing `check_reopen_available()` and related reopen logic in `sei_cli/client.py`.

## The Bug

`check_reopen_available()` (line ~3088) currently uses `_open_process_page()` which follows the `procedimento_visualizar` iframe. It then searches for `acao=procedimento_reabrir` in that HTML.

**The problem:** `procedimento_visualizar` NEVER contains `acao=procedimento_reabrir` for concluded processes. The reopen action only exists in the `arvore_visualizar` page (a different iframe target loaded via JS). As a result, `check_reopen_available()` ALWAYS returns `false`, making process-reopen completely non-functional.

## Verified SEI Behavior (tested manually 2026-04-02)

### Where actions live:

**`procedimento_visualizar`** (reached via `_open_process_page()`):
- Shows actions for **open** processes only: `concluir`, `enviar`, `sobrestar`, `alterar`, etc.
- For concluded processes: only `consultar`, `consultar_historico`, `controlar`, `gerar_pdf`, `paginar`, `pesquisar`, `visualizar`
- **NEVER shows `procedimento_reabrir`**

**`arvore_visualizar`** (reached via `_navigate_to_arvore()`):
- Contains JS variable: `var linkReabrirProcesso = 'controlador.php?acao=procedimento_reabrir&...'`
- Also has `acao=procedimento_reabrir` in various link/onclick attributes
- **THIS is where the reopen action lives for concluded processes**

### Key discovery about `linkReabrirProcesso`:

Previously we thought `linkReabrirProcesso` appearing in `arvore_visualizar` was unreliable (showing up in units that can't actually reopen). **This was wrong.**

**Tested:** For process 48756457 (concluded), `linkReabrirProcesso` appears in:
- CMDO PABM APODI ✅ — successfully reopens
- 1°SAT/1°CAT ✅ — successfully reopens
- PAD-PDF ✅ — successfully reopens  
- CHEFIA SAT ✅ — successfully reopens (even though it never "had" the process in its control queue)

**The false positive we saw before was because the process was already OPEN** — `txaInfraValidacao` returned "Processo já está aberto na unidade atual." The link itself was correct.

**Conclusion:** `linkReabrirProcesso` in `arvore_visualizar` IS reliable for concluded processes. If the link is present, the reopen will work. If the process is already open, SEI returns a validation error.

## Required Changes

### 1. Fix `check_reopen_available()` (client.py ~line 3088)

**Current (broken):**
```python
def check_reopen_available(self, id_procedimento: str) -> bool:
    try:
        proc_html = self._open_process_page(id_procedimento)
    except Exception:
        return False
    return bool(self._extract_action_url(proc_html, "procedimento_reabrir"))
```

**Fix:** Use `_navigate_to_arvore()` and look for `linkReabrirProcesso` JS variable:
```python
def check_reopen_available(self, id_procedimento: str) -> bool:
    """Check if 'Reabrir Processo' is available.

    Source of truth: arvore_visualizar page — look for JS var
    linkReabrirProcesso. This var only appears for concluded processes
    where the current unit has reopen permission.
    """
    try:
        arvore_html = self._navigate_to_arvore(id_procedimento)
    except Exception:
        return False
    if not arvore_html:
        return False
    return bool(re.search(r"var\s+linkReabrirProcesso\s*=\s*'[^']+'", arvore_html))
```

### 2. Fix `reabrir_processo()` (client.py ~line 3105)

The current implementation uses `_open_process_page()` → `_extract_action_url(proc_html, "procedimento_reabrir")` which will never find the URL.

**Fix:** Use `_navigate_to_arvore()` to extract `linkReabrirProcesso`:
```python
def reabrir_processo(self, id_procedimento: str) -> bool:
    """Reopen a concluded process in the current unit.

    Extracts the reopen URL from arvore_visualizar (linkReabrirProcesso JS var),
    executes the GET, validates txaInfraValidacao for errors, and confirms
    the process is actually open after the call.
    """
    arvore_html = self._navigate_to_arvore(id_procedimento)
    if not arvore_html:
        raise RuntimeError(
            f"Não foi possível acessar a árvore do processo {id_procedimento}."
        )

    link_m = re.search(r"var\s+linkReabrirProcesso\s*=\s*'([^']+)'", arvore_html)
    if not link_m:
        raise RuntimeError(
            f"Ação 'Reabrir Processo' não encontrada para o processo {id_procedimento}. "
            "O processo pode já estar aberto nessa unidade ou você não tem permissão."
        )

    reabrir_url = link_m.group(1).replace("&amp;", "&")
    r = self._get(self._sei_url(reabrir_url))
    self._control_html = None

    # Check for SEI validation errors (e.g. "Processo já está aberto na unidade atual.")
    rsoup = BeautifulSoup(r.text, "lxml")
    validation = rsoup.find("textarea", {"id": "txaInfraValidacao"})
    if validation and validation.get_text(strip=True):
        raise RuntimeError(validation.get_text(" ", strip=True))

    # Verify the process is actually open: procedimento_visualizar should now
    # show concluir/enviar actions
    post_html = self._open_process_page(id_procedimento)
    if self._extract_action_url(post_html, "procedimento_concluir") or \
       self._extract_action_url(post_html, "procedimento_enviar"):
        return True

    raise RuntimeError("SEI não confirmou a reabertura do processo.")
```

### 3. Fix or create `_navigate_to_arvore_visualizar()` 

**CRITICAL:** The existing `_navigate_to_arvore()` at line ~5523 is **MISNAMED**. It returns the HTML of `ifrArvore` which is actually `procedimento_visualizar` — NOT `arvore_visualizar`. These are DIFFERENT pages:

- `ifrArvore` iframe → `procedimento_visualizar` (action icons for open processes)
- Inside `procedimento_visualizar`, there's a JS call/link to `arvore_visualizar` (the tree page with `linkReabrirProcesso`)

You need a method that goes one step further. Create `_navigate_to_arvore_visualizar()` (or rename/extend the existing one):

```python
def _navigate_to_arvore_visualizar(self, id_procedimento: str) -> str | None:
    """Navigate to the arvore_visualizar page for a process.
    
    Chain: procedimento_trabalhar → ifrArvore (procedimento_visualizar) → arvore_visualizar
    
    The arvore_visualizar page contains JS variables like:
    - var linkReabrirProcesso = '...'
    - var linkConcluirProcesso = '...' 
    - var linkEncaminharProcesso = '...'
    """
    # Step 1: Get procedimento_visualizar (what _navigate_to_arvore currently returns)
    proc_vis_html = self._navigate_to_arvore(id_procedimento)
    if not proc_vis_html:
        return None
    
    # Step 2: Find arvore_visualizar URL in procedimento_visualizar
    m = re.search(
        r'(controlador\.php\?acao=arvore_visualizar[^"\'\\ ]+)',
        proc_vis_html,
    )
    if not m:
        return None
    
    arv_vis_url = m.group(1).replace("&amp;", "&")
    r = self._get(self._sei_url(arv_vis_url))
    return r.text
```

Then use this in `check_reopen_available()` and `reabrir_processo()` instead of `_navigate_to_arvore()`.

### 4. No changes needed to:

- `list_process_history_units()` — this is fine
- The preflight logic in `process_reopen_preview/confirm` in `writing.py` — this is fine, it correctly tries multiple units
- The `txaInfraValidacao` validation — **keep this**, it catches real errors
- The post-reopen verification — **keep this**, it confirms success

## Test Plan

After fixing, these should work:

```bash
# 1. Conclude process first
sei switch "CMDO PABM APODI"
sei process-conclude-confirm "08810254.000117/2026-62" --confirm --json

# 2. Preview reopen — should show reopen_available=true
sei process-reopen-preview "08810254.000117/2026-62" --unit "CMDO PABM APODI" --json

# 3. Confirm reopen — should succeed
sei process-reopen-confirm "08810254.000117/2026-62" --unit "CMDO PABM APODI" --confirm --json

# 4. Try reopen again (already open) — should fail with txaInfraValidacao error
sei process-reopen-preview "08810254.000117/2026-62" --unit "CMDO PABM APODI" --json
# Expected: reopen_available=false (because linkReabrirProcesso won't be in arvore for open process)
```

## Files to modify

- `sei_cli/client.py`: `check_reopen_available()` (~line 3088) and `reabrir_processo()` (~line 3105)
- Possibly `_navigate_to_arvore()` (~line 5523) if it doesn't reach `arvore_visualizar` correctly
