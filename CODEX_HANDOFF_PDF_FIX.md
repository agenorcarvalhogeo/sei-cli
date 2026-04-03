# Codex Handoff: `document-pdf-confirm` Fix

## Status: Fix Applied — Needs Testing

## Root Cause

`_gerar_pdf_flow` in `sei_cli/client.py` (~line 4835) searches for a `procedimento_gerar_pdf&id_documento=X` URL in the process tree HTML. **This URL only exists for the currently-selected document** in the SEI tree (the last one opened). All other documents in the process don't have this link, causing `RuntimeError: Link 'Gerar PDF' não encontrado`.

## Fix Applied (client.py, `_gerar_pdf_flow`)

**What changed:** When `id_documento` is provided and no document-specific `gerar_pdf&id_documento=X` link exists in the tree, the method now falls back to the **process-level** `procedimento_gerar_pdf` URL (without `id_documento`) and POSTs with:
- `rdoTipo=A` (Apenas / "Only these documents")
- `hdnDocumentosApenas=<id_documento>`

This tells SEI to generate a PDF containing only the specified document.

**Key variable:** `use_apenas_mode` (bool) — set to `True` when using the fallback path.

### Before (lines ~4839-4849):
```python
if id_documento:
    for url in candidates:
        if f'id_documento={id_documento}' in url:
            page_url_raw = url
            break
    if page_url_raw is None:
        raise RuntimeError(...)
```

### After:
```python
use_apenas_mode = False

if id_documento:
    for url in candidates:
        if f'id_documento={id_documento}' in url:
            page_url_raw = url
            break
    if page_url_raw is None:
        # Fallback: use process-level URL with rdoTipo=A
        for url in candidates:
            if f'id_procedimento={id_procedimento}' in url and 'id_documento=' not in url:
                page_url_raw = url
                use_apenas_mode = True
                break
    if page_url_raw is None:
        raise RuntimeError(...)
```

And at Step 5 POST:
```python
if use_apenas_mode:
    post_data['rdoTipo'] = 'A'
    post_data['hdnDocumentosApenas'] = id_documento
```

## How SEI's PDF Generation Works (3 modes)

The `procedimento_gerar_pdf` form has 3 radio options:
1. **`rdoTipo=T`** (Todos) — Generate PDF with ALL documents in the process
2. **`rdoTipo=E`** (Exceto) — Generate PDF EXCLUDING specified documents
3. **`rdoTipo=A`** (Apenas) — Generate PDF with ONLY specified documents

The document IDs go in `hdnDocumentosApenas` or `hdnDocumentosExceto` fields.

## Files Changed

- `sei_cli/client.py` — `_gerar_pdf_flow` method (around line 4835-4900)

## Testing Needed

1. **Single doc PDF (with direct link):** `sei document-pdf-confirm <doc_id> --process <proc_id>` where doc IS the currently selected one → should use direct link as before (no regression)
2. **Single doc PDF (fallback):** Same command where doc is NOT the currently selected one → should use `rdoTipo=A` fallback
3. **Process PDF:** `sei process-pdf-confirm <proc_id>` → should work as before (no regression)
4. **Test doc from prior session:** doc `48849195` in its process → was manually verified working with this approach

## Broader Context

This is part of the `document-pdf-confirm` CLI command. The public methods are:
- `download_process_pdf()` (line ~4940) — downloads entire process as PDF
- `download_document_pdf()` (line ~4987) — downloads single document as PDF

Both call `_gerar_pdf_flow()` which is the method that was fixed.

## CLI Commands Mapping
- `sei document-pdf-confirm` → calls `download_document_pdf()`
- `sei process-pdf-confirm` → calls `download_process_pdf()`
