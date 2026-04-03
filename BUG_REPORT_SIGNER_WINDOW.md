# Bug: `_extract_expected_signer` fails on fragmented HTML footers

## Summary

`_extract_expected_signer()` in `sei_cli/operations/writing.py` (line 96) uses fixed-size tail windows (last 5 and last 12 non-empty lines) to find the signer name+rank in document text. This fails when BeautifulSoup's `get_text("\n")` splits the HTML footer into many single-token lines, pushing the signer's name outside both windows.

## Root Cause

SEI document HTML has structured `<div>` blocks for the signature. When parsed by BeautifulSoup with `get_text("\n")`, each tag boundary becomes a newline, fragmenting the footer:

```
[64] Leo                    ← signer name (3 lines!)
[65] Zenon
[66] Tassi
[67] -                      ← separator
[68] 2º Ten                 ← rank
[69] QOEM
[70] Chefe da 1º Seção de Atividades Técnicas - 1ºSAT/1ºCAT/DAT
[71] Referência:            ← SEI metadata footer starts
[72] Processo nº 08810198.000085/2026-17
[73] SEI nº 40442193
[74] Criado por
[75] 01664314431
[76] , versão 2 por
[77] 01664314431
[78] em 01/04/2026 15:51:48.
```

- **Window of 5** (lines 74-78): only creation metadata → no match
- **Window of 12** (lines 67-78): starts at `"-"` separator → captures `"2º Ten QOEM Chefe da..."` → matches name as "Chefe da" (wrong!)
- **The real name** "Leo Zenon Tassi" is at lines 64-66, which needs a window of 15+ lines

## Fix

Add a **"Referência:" anchor** strategy: find the **last** occurrence of a line starting with `"Referência:"` (the SEI metadata footer marker), then take 12 lines *before* it as a priority window. This is reliable because:

1. Every SEI document ends with `Referência: / Processo nº ... / SEI nº ... / Criado por ...`
2. The signer name+rank always appears just before this metadata block
3. Using the **last** "Referência:" avoids matching body content (documents can have "Referência:" in the body text too — e.g., this doc has it at line 9 in the body AND line 71 in the footer)

### Implementation

In `_extract_expected_signer()` (writing.py, line 96), after building `non_empty_lines`, add the anchor window as the **first** candidate (highest priority):

```python
# Current code (line 112):
candidate_windows = [non_empty_lines[-5:], non_empty_lines[-12:]]

# New code:
candidate_windows = []

# Anchor window: last "Referência:" line, take 12 lines before it
ref_idx = None
for i in range(len(non_empty_lines) - 1, -1, -1):  # reverse search → last occurrence
    if non_empty_lines[i].startswith("Referência"):
        ref_idx = i
        break
if ref_idx is not None and ref_idx > 0:
    start = max(0, ref_idx - 12)
    candidate_windows.append(non_empty_lines[start:ref_idx])

# Keep existing fallback windows
candidate_windows.append(non_empty_lines[-5:])
candidate_windows.append(non_empty_lines[-12:])
```

The anchor window gets priority. If the document doesn't have "Referência:" (unlikely but possible for very old docs), the existing fallback windows still work.

### Expected Result for doc 40442193

Anchor window (lines 59-70, 12 lines before `Referência:` at 71):

```
9 – 9959 - 1091 PRESCRIÇÕES DIVERSAS: 1. Em cada dia referenciado...
2 . A equipe verificará... 3. A equipe visará... Leo Zenon Tassi
- 2º Ten QOEM Chefe da 1º Seção de Atividades Técnicas - 1ºSAT/1ºCAT/DAT
```

Joined `tail_text` contains `"Leo Zenon Tassi - 2º Ten QOEM"` → Pattern 1 (`Name - Rank`) matches correctly with full name.

## Test Update

Update the existing test `test_process_finalize_preview_extracts_fragmented_footer_signer` in `tests/test_operations.py` (line 1354) to include the SEI metadata footer after the fragmented name, which is the realistic scenario:

```python
def read_document(self, id_documento: str, id_procedimento: str) -> str:
    if (id_documento, id_procedimento) == ("48568466", "47607237"):
        return (
            "Despacho de teste.\n"
            "Encaminhar para a secretaria.\n"
            "Leo\n"
            "Zenon\n"
            "Tassi\n"
            "-\n"
            "2º TEN\n"
            "QOEM\n"
            "Referência:\n"
            "Processo nº 08810198.000085/2026-17\n"
            "SEI nº 40442193\n"
            "Criado por\n"
            "01664314431\n"
            ", versão 2 por\n"
            "01664314431\n"
            "em 01/04/2026 15:51:48.\n"
        )
    return super().read_document(id_documento, id_procedimento)
```

Also add a new test for the case where there's no "Referência:" (fallback to existing behavior):

```python
def test_process_finalize_preview_extracts_signer_without_referencia_footer() -> None:
    """Fallback: when no 'Referência:' footer exists, existing windows still work."""
    # (use the current test body unchanged as the fallback test)
```

## Files to Change

1. **`sei_cli/operations/writing.py`** — `_extract_expected_signer()` (line 112): add anchor window logic
2. **`tests/test_operations.py`** — update `test_process_finalize_preview_extracts_fragmented_footer_signer` and add fallback test

## Verification

```bash
cd /Users/zen/Projects/sei-cli
pytest tests/test_operations.py::test_process_finalize_preview_extracts_fragmented_footer_signer -xvs
pytest tests/ -x  # full suite
```
