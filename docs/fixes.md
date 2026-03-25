# Correções e Problemas Conhecidos

## Fix: `sei processes` falha após `sei login` (sessão restaurada)

**Data:** 2026-03-25
**Arquivo:** `sei_cli/client.py` — método `_try_inicializar`

### Problema

Ao executar `sei login` seguido de `sei processes` em processos separados (o caso normal de uso via CLI), o comando `processes` lançava:

```
RuntimeError: Página de controle de processos não encontrada (tabelas ausentes).
Verifique se a sessão está ativa e na unidade correta.
```

### Causa raiz

O método `_try_inicializar` faz GET em `inicializar.php` e espera ser redirecionado para a página de controle de processos (`acao=procedimento_controlar`), que contém as tabelas `tblProcessosRecebidos` e `tblProcessosGerados`.

Porém, quando a sessão é restaurada de disco (cookie salvo pelo `sei login`), o `inicializar.php` redireciona para `acao=principal` — o **frameset principal** do SEI — que contém o texto "Controle de Processos" no título, mas **não** as tabelas de processos (essas são carregadas em um iframe separado).

O check original era:
```python
if r2.status_code == 200 and "Controle de Processos" in r2.text:
    return r2.text  # ERRADO: retorna o frameset, sem tabelas
```

### Correção

Após confirmar que estamos no frameset (`acao=principal` na URL ou ausência de `tblProcessosRecebidos`), navegamos explicitamente para `acao=procedimento_controlar` com o `infra_unidade_atual` correto:

```python
if "acao=principal" in str(r2.url) or "tblProcessosRecebidos" not in r2.text:
    unit_id = self._current_unit_id or ""
    ctrl_url = self._sei_url(
        "controlador.php?acao=procedimento_controlar&infra_sistema=100000100"
        + (f"&infra_unidade_atual={unit_id}" if unit_id else "")
    )
    r3 = self.client.get(ctrl_url)
    if r3.status_code == 200 and "tblProcessosRecebidos" in r3.text:
        return r3.text
    return None
```

### Observação

O comportamento do `inicializar.php` parece variar conforme o estado da sessão no servidor:
- **Login fresco** (sem cookie salvo): redireciona direto para `acao=procedimento_controlar`
- **Sessão restaurada** (cookie de disco): redireciona para `acao=principal`

A correção lida com ambos os casos.

---

---

## Fix: `edit_document_section` causa double-escape no editor SEI

**Data:** 2026-03-25
**Arquivo:** `sei_cli/client.py` — método `edit_document_section`

### Problema

Ao usar `edit_document_section(id_doc, id_proc, section_id, raw_html)`, o conteúdo salvo no SEI aparecia com escape duplo: os tags HTML apareciam como texto literal (`&lt;p class=...&gt;`) em vez de renderizarem normalmente.

### Causa raiz

`edit_document_section` chama `self.escape_for_sei(new_raw_html)` antes de atribuir ao `target.content`. O `escape_for_sei` converte `<p>` em `&lt;p&gt;`. Em seguida, `save_document` usa `_post` → `urlencode`, que URL-codifica o `&` de `&lt;p&gt;` para `%26lt%3Bp`, fazendo o servidor armazenar `&lt;p` como valor da textarea — em vez de `<p>` (HTML cru).

Resultado: CKEditor lê `&lt;p` como texto, exibindo literalmente `<p class="X">` no documento.

### Correção

Passar HTML **cru** (sem nenhum `html.escape()`) diretamente ao `save_document`, acessando as sections manualmente:

```python
save_url, sections = client.get_editor_sections(id_documento, id_procedimento)
for s in sections:
    if s.section_id == section_id:
        s.content = raw_html  # HTML cru — sem escape
        break
client.save_document(save_url, sections)
```

### Regra geral

- ✅ `s.content = raw_html` — HTML com tags reais (`<p>`, `<strong>`)
- ❌ `s.content = html.escape(raw_html)` — gera double-escape
- ❌ `edit_document_section(...)` com `escape_for_sei` — mesmo problema

Ao **ler** conteúdo existente de uma section use `html.unescape(s.content)` para obter o HTML cru.

---

## Observação: `_current_unit_id` não persiste entre processos

**Data:** 2026-03-25

Após o `sei login`, o `_current_unit_id` fica `None` no `session.json` (`unit_id: null`), pois a persitência só salva o `unit_id` depois de um `switch_unit` explícito.

Na correção acima, o `ctrl_url` sem `infra_unidade_atual` ainda funciona porque o SEI usa a unidade padrão do usuário autenticado. Porém, para usuários com múltiplas unidades, seria ideal persistir o `unit_id` logo após o login.
