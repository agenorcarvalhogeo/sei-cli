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

### Endurecimento da canônica

**Data:** 2026-04-23

A canônica `document-edit-*` agora reforça a regra no próprio `save_document()`:

- todas as seções `txaEditor_*` são normalizadas para HTML cru antes do POST
- tags estruturais escapadas (`&lt;p&gt;`, `&lt;strong&gt;`, `&lt;table&gt;`, etc.) são revertidas para tags reais
- caracteres fora de ISO-8859-1 são convertidos para entidades numéricas (`&#nnn;`)
- `&nbsp;` é preservado como entidade HTML
- a edição continua substituindo apenas a seção alvo, preservando as demais seções do documento

Isso cobre também as seções não editadas que voltam do editor em forma escapada e seriam repostadas junto com o corpo.

### Documento Modelo na criação canônica

**Data:** 2026-04-23

A canônica `document-create-*` agora aceita `--documento-modelo <numero_sei>`:

- o contrato força `texto_inicial=D` quando há documento modelo
- o POST preenche `txtProtocoloDocumentoTextoBase` com o número SEI informado
- `hdnIdDocumentoTextoBase` permanece vazio no fluxo por número digitado
- `document-edit-preview` evita cabeçalho, metadados e rodapé em documentos multi-seção

No teste real de Encaminhamento, a seção correta de corpo foi `1062`; as seções `1059`, `1060`, `1061` e `1064` correspondiam a timbre/título/metadados/rodapé.

### Matriz real de seção editável por tipo

**Data:** 2026-04-23

Teste executado no processo `08810254.000138/2026-88` / `49286513`, criando e editando cada tipo com marcador único. Todos os documentos validados por `document-read` sem ocorrência de `&lt;p`, `&amp;lt;`, `&lt;br` ou `&amp;amp;lt`.

| Tipo | Seção de corpo validada |
| --- | --- |
| Parecer | `601` |
| Ordem de Serviço | `341` |
| Parte Genérica | `341` |
| Despacho | `220` |
| Memorando | `341` |
| Autorização | `341` |
| Despacho Diligencial | `220` |
| Informação | `422` |
| Justificativa | `873` |
| Relatório de Viagem | `3690` |
| Minuta de Portaria | `616` |
| Solicitação de Providências | `341` |
| Solicitação | `4499` |

Observações:

- `1062` é padrão do Encaminhamento testado, não padrão global.
- Justificativa expõe `875` como tabela de referência/metadados; a seção de corpo real é `873`.
- Famílias tipo memorando/ofício/solicitação tendem a usar `341`, mas a canônica deve continuar inferindo pelo conteúdo das seções, não por id fixo.

---

## Fix: `_execute_sign_form` usa credenciais hardcoded do desenvolvedor

**Data:** 2026-03-25
**Arquivo:** `sei_cli/client.py` — método `_execute_sign_form`

### Problema

O método `_execute_sign_form` tinha `txtUsuario = "LEO ZENON TASSI"` e `hdnIdUsuario = "100066959"` hardcoded — credenciais do desenvolvedor original. A tentativa de assinatura falhava silenciosamente: o SEI retornava o formulário novamente (erro de autenticação) mas a lógica de fallback interpretava isso como sucesso.

Além disso, `selCargoFuncao` era hardcoded como `"2\xba Tenente QOEM BM"` e não havia como configurar o cargo do usuário.

### Correção

1. Remover o override de `txtUsuario` e `hdnIdUsuario` — o SEI pré-preenche esses campos no formulário com os dados do usuário logado na sessão.
2. Adicionar campos `cargo` e `id_usuario` ao `credentials.json` (opcionais).
3. O `selCargoFuncao` agora vem de `creds.cargo` (lido do `credentials.json`).
4. O `selOrgao` agora usa `orgao_to_value(creds.orgao)` em vez de `"28"` hardcoded.
5. Adicionado comando `sei sign <id_procedimento> <doc1> ...` ao CLI.

### Configuração necessária

Adicionar ao `~/.config/sei/credentials.json`:

```json
{
  "cargo": "Tenente-Coronel QOEM BM",
  "id_usuario": "100039182"
}
```

O valor de `cargo` deve corresponder exatamente a uma das opções do `<select name="selCargoFuncao">` no formulário de assinatura do SEI. Caractere `º` deve ser o ordinal latin1 correto (não precisa de escape — Python codifica como ISO-8859-1 no POST).

### Regra geral

- `txtUsuario` e `hdnIdUsuario` vêm do formulário (pré-preenchidos pelo SEI com o usuário da sessão ativa) — **não sobrescrever**.
- `selCargoFuncao` configurar em `credentials.json` (campo `"cargo"`).
- O POST é enviado com `encoding="iso-8859-1"` para suportar o caractere `º`.

---

## Observação: `_current_unit_id` não persiste entre processos

**Data:** 2026-03-25

Após o `sei login`, o `_current_unit_id` fica `None` no `session.json` (`unit_id: null`), pois a persitência só salva o `unit_id` depois de um `switch_unit` explícito.

Na correção acima, o `ctrl_url` sem `infra_unidade_atual` ainda funciona porque o SEI usa a unidade padrão do usuário autenticado. Porém, para usuários com múltiplas unidades, seria ideal persistir o `unit_id` logo após o login.
