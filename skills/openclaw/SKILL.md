---
name: sei
description: "Gerenciar processos, blocos de assinatura, despachos e documentos no SEI (Sistema Eletrônico de Informações). Use quando o usuário pedir para: ver um processo, ler documento em bloco, assinar, criar bloco de assinatura, fazer despacho, encaminhar processo para outra unidade, verificar caixa/inbox, buscar processos, mudar de unidade SEI, ler relatório do fiscal ou qualquer ação sobre documentos militares no SEI."
---

> **Nota para Agentes/Contribuidores:** 
> Esta skill é mantida no repositório `sei-cli/skills/openclaw/SKILL.md`.
> Para instalá-la no seu workspace, faça o symlink:
> `ln -sf ~/Projects/sei-cli/skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/sei/SKILL.md`
> Toda vez que a API pública mudar, atualize ESTE arquivo no repositório.


## Architecture: 100% HTTP via sei-cli

**sei-cli** (`~/Projects/sei-cli/`) handles ALL operations via pure HTTP (~2-5s per op).
Browser automation is NO LONGER NEEDED for any standard workflow.

```
sei-cli (HTTP)
├── Login (~2s)
├── List processes / Search / Check new
├── Switch units (10 available) + auto-unit-switch (transparent)
├── List/view blocks
├── Sign blocks ✍️ / Sign documents ✍️
├── Authenticate external documents ✅
├── Create documents 📝 (21 types)
├── Edit document content ✏️
├── Delete unsigned documents 🗑️
├── Alter process metadata (description/observations) 📋
├── Acompanhamento Especial (list/create groups, add processes) 📁
├── Get available actions (process or document level) 🔍
├── Set/remove marcadores with descriptions 🏷️
├── Dar ciência em documentos/processos 👁️
├── Upload documento externo (PDF) 📎
├── Download process PDF 📄 (7-step native flow)
├── Download individual document PDF 📄
└── Auto-unit-switch for restricted/cross-unit processes 🔄
```

## Action Menus (iframe arvore_visualizar)

SEI exposes **two different action menus** depending on whether you click
the **process** or a **document** in the tree. Actions are JS variables
(`var linkXxx = 'url'`) extracted from `arvore_visualizar`.

### Process-Level Actions (26 toolbar buttons)

| Action | `acao=` | Method |
|--------|---------|--------|
| Incluir Documento | `documento_escolher_tipo` | — |
| Iniciar Processo Relacionado | `procedimento_escolher_tipo_relacionado` | — |
| **Consultar/Alterar Processo** | `procedimento_alterar` | `alter_process()` |
| Acompanhamento Especial | `acompanhamento_gerenciar` | — |
| Ciência | (JS) | — |
| **Enviar Processo** | `procedimento_enviar` | `enviar_processo()` |
| Atualizar Andamento | `procedimento_atualizar_andamento` | — |
| Atribuir Processo | `procedimento_atribuicao_cadastrar` | — |
| Adicionar aos Favoritos | `protocolo_modelo_gerenciar` | — |
| Duplicar Processo | `procedimento_duplicar` | — |
| Enviar Email | (JS) | — |
| Relacionamentos | `procedimento_relacionar` | — |
| Incluir em Bloco | (JS) | — |
| Ordenar Árvore | `arvore_ordenar` | — |
| Acesso Externo | `acesso_externo_gerenciar` | — |
| Anotações | `anotacao_registrar` | — |
| Sobrestar Processo | `procedimento_sobrestar` | — |
| Anexar Processo | `procedimento_anexar` | — |
| **Concluir Processo** | `procedimento_concluir` | — |
| Gerar PDF do Processo | `procedimento_gerar_pdf` | `download_pdf()` / `download_document_pdf()` |
| Gerar ZIP do Processo | `procedimento_gerar_zip` | — |
| Comentários | `comentario_listar` | — |
| **Gerenciar Marcador** | `andamento_marcador_gerenciar` | `set_marcador()` |
| Controle de Prazo | `controle_prazo_definir` | — |
| Controle de Processos | (JS) | — |
| Pesquisar no Processo | `procedimento_pesquisar` | — |

### Document-Level Actions (via JS link variables)

| JS Variable | `acao=` | Method |
|-------------|---------|--------|
| `linkEditarConteudo` | `editor_montar` | `get_editor_sections()` + `save_document()` |
| `linkAssinarDocumento` | `documento_assinar` | `sign_document()` |
| `linkExcluirDocumento` | `documento_excluir` | `delete_document()` |

**Signed docs** lose Edit/Delete/Sign buttons; may gain Cancel button.

### How to discover actions
```python
# Process-level
actions = c.get_actions("48218772")
# Document-level
actions = c.get_actions("48218772", id_documento="48218774")
# Returns dict: {"linkExcluirDocumento": "controlador.php?acao=...", ...}
```

## Setup & Credentials

Config file: `~/.config/sei/credentials.json`

```json
{
  "usuario": "<CPF>",
  "senha": "<senha do vault 'sei'>",
  "orgao": "CBM",
  "login_url": "https://sei.rn.gov.br/sip/login.php?sigla_orgao_sistema=SEAD&sigla_sistema=SEI"
}
```

⚠️ **Armadilha comum:** O parâmetro `sigla_orgao_sistema` DEVE ser `SEAD` (Secretaria de Administração do RN), **não** `RN` ou `CBMRN`. Usar valor errado resulta em "Sistema inválido" ou redirect infinito para a página de login. O `orgao` no JSON (`CBM`) é o órgão do **usuário** dentro do SEI, que é diferente do `sigla_orgao_sistema` (que identifica a **instância do SIP/SEI**).

Credenciais no Bitwarden: vault item `SEI SISBOM RN CBMRN` (alias `sei`).

## Security Rules

1. **Never sign/create documents without Leo's explicit approval** — list first, show what's pending, wait for go-ahead
2. Credentials sourced from Bitwarden vault (`sei` alias)

## Quick Reference — sei-cli Python API

```python
from sei_cli.client import SEIClient

with SEIClient() as c:
    status = c.login()
    # status.unidade_sigla, status.usuario, status.ultimo_acesso

    # --- Read operations ---
    procs = c.list_processes()          # .recebidos, .gerados
    novos = c.check_new_processes()     # unread only
    html = c.search("08810116")         # quick search
    units = c.list_units()
    c.switch_unit("SAT")               # keyword match
    docs = c.get_full_document_tree(id_procedimento, expand_all=True)

    # --- Blocks ---
    blocks = c.list_blocks()
    block_docs = c.get_block_documents("774681")

    # --- Sign (needs Leo's approval) ---
    result = c.sign_block("774681")
    result = c.sign_document(id_documento, id_procedimento)
    # → {'signed': [...], 'already_signed': [...], 'errors': [...]}

    # --- Create document (needs Leo's approval) ---
    types = c.list_document_types(id_procedimento)  # 21 types available
    created = c.create_document(
        id_procedimento,
        tipo="despacho",          # or "oficio", "parte_generica", etc.
        nivel_acesso="0",         # 0=Público
        texto_inicial="N",        # N=Nenhum (blank doc)
    )
    # created.id_documento, created.editor_url

    # --- Edit document content ---
    save_url, sections = c.get_editor_sections(id_documento, id_procedimento)
    # sections: [EditorSection(name, content, section_id), ...]
    # Typical sections:
    #   txaEditor_404 → Timbre/header (DO NOT EDIT)
    #   txaEditor_405 → Title (e.g. "DESPACHO")
    #   txaEditor_406 → BODY — main content goes here
    #   txaEditor_408 → Footer/reference (DO NOT EDIT)

    # Modify body section:
    body = next(s for s in sections if s.name == "txaEditor_406")
    body.content = '<p class="Texto_Justificado_Recuo_Primeira_Linha">Novo conteúdo</p>'
    c.save_document(save_url, sections)

    # --- Download PDFs ---
    c.download_pdf(id_procedimento, '/tmp/processo.pdf')        # full process
    c.download_document_pdf(id_doc, id_proc, '/tmp/doc.pdf')    # single doc

    # --- Authenticate external docs ---
    c.authenticate_document(id_documento, id_procedimento)
    c.authenticate_documents([id1, id2], id_procedimento)  # batch

    # --- Dar ciência ---
    c.give_notice_document(id_doc, id_proc)    # ciência em doc específico
    c.give_notice_process(id_proc)             # ciência no processo inteiro

    # --- Upload documento externo ---
    doc_id = c.upload_external_document(
        id_procedimento,
        '/path/to/file.pdf',
        tipo='anexo',                    # or any doc type
        nivel_acesso='0',                # 0=Público
        descricao='Página 42 do BGCB',
        data_elaboracao='21/03/2026',    # DD/MM/YYYY (default: today)
        tipo_conferencia='4',            # 4=Original, 1=Cópia Simples
        numero='',                       # optional doc number
    )

    # --- Auto-unit-switch (transparent) ---
    # download_pdf, download_document_pdf, view_document_html,
    # sign_document, authenticate_document auto-detect when a
    # process is in another unit and switch transparently.
    # Two scenarios handled:
    #   1. "Processo aberto somente na unidade X" → switch to X
    #   2. Restricted access (about:blank docs) → find accessible unit
    #      via procedimento_consultar_historico → switch → execute → restore
```

## Document Types Available (21)

| Key | Name | SEI ID |
|-----|------|--------|
| `despacho` | Despacho | 5 |
| `oficio` | Ofício | 11 |
| `parte_generica` | Parte Genérica | 292 |
| `informacao` | Informação | 92 |
| `encaminhamento` | Encaminhamento | 327 |
| `memorando` | Memorando | 12 |
| `declaracao` | Declaração | 83 |
| `autorizacao` | Autorização | 305 |
| `parecer` | Parecer | 191 |
| `minuta_portaria` | Minuta de Portaria | 235 |
| `solicitacao` | Solicitação | 178 |
| `solicitacao_providencias` | Sol. de Providências | 347 |
| `relatorio_viagem` | Relatório de Viagem | 326 |
| `plano_trabalho` | Plano de Trabalho | 669 |
| `analise_riscos` | Análise de Riscos | 220 |
| `despacho_diligencial` | Despacho Diligencial | 377 |
| `dfd` | Doc. Formalização Demanda | 970 |
| `etp` | Estudo Técnico Preliminar | 1170 |
| `justificativa` | Justificativa | 307 |
| `termo_referencia` | Termo de Referência | 214 |
| `externo` | Externo (PDF upload) | -1 |

## Workflows

### 1. Check processes & blocks
```
c.login() → c.list_processes() → c.list_blocks()
For each block: c.get_block_documents(num)
```

### 2. Sign (needs approval)
```
Show pending blocks/docs to Leo → wait for "assina bloco X"
c.sign_block(numero) or c.sign_document(id_doc, id_proc)
```

### 3. Create document (needs approval)
```
1. Leo says "faz um despacho no processo X dizendo Y"
2. c.login()
3. created = c.create_document(id_proc, "despacho")
4. save_url, sections = c.get_editor_sections(created.id_documento, id_proc)
5. Modify body section with content
6. c.save_document(save_url, sections)
7. Show preview to Leo → wait for "assina"
8. c.sign_document(created.id_documento, id_proc)
```

### 4. Full despacho workflow (end-to-end)
```
1. c.switch_unit("PABM APODI")
2. procs = c.list_processes()  → find the target process
3. docs = c.get_full_document_tree(id_proc, expand_all=True) → read existing docs for context
4. created = c.create_document(id_proc, "despacho")
5. save_url, sections = c.get_editor_sections(created.id_documento, id_proc)
6. Fill body with formatted HTML (use CSS classes below)
7. c.save_document(save_url, sections)
8. Report to Leo: "Despacho criado no processo X. Conteúdo: ..."
9. Wait for Leo's approval → c.sign_document(...)
```

### 5. Alter process metadata
```python
# Add description and observations to a process
c.alter_process(
    "48218772",
    descricao="Diárias de viagem - II COPA 2026",
    observacoes="Solicitação de diárias - 02 a 13/03/2026"
)
# NOTE: alter_process auto-fills hdnAssuntos and hdnInteressadosProcedimento
# from selects if they're empty (required by SEI validation).
```

### 6. Organize processes (marcadores + descrições)
```
1. c.list_processes() → get all processes in unit
2. For each: c.alter_process(id, descricao="...") → add clear title
3. c.set_marcador(id, marcador_id="64956", texto="...") → categorize
4. Available marcadores: ALMOX, Armamento, CURSOS, Diárias, Equipamentos,
   Escala Especial, Férias/Dispensas, Informações, LIVROS,
   Materiais Quartel, Suprimento, Transferência, Zen On
```

## Formatação de Documentos & Produção Textual

→ **Single source of truth:** Skill `oda` (Oficial de Documentos Administrativos).
Ao criar ou editar qualquer documento SEI, carregar `skills/oda/SKILL.md` para padrões de formatação (classes CSS, espaçamento, tabelas, encoding, nome de guerra, assinaturas).

### Referências Técnicas Rápidas (SEI-specific)

- **Encoding:** Tudo no SEI é ISO-8859-1. POST com `quote(valor, safe='', encoding='latin-1')`.
- **`save_document` content = HTML cru.** Nunca `html.escape()`. Double-escape = tags visíveis.
- **Hyperlinks SEI:** `<a class="ancora_sei" id="lnkSei{id_documento}">{protocolo}</a>` em `<span contenteditable="false">`. Nunca `href` externo.
- **QOEM/QOEMBM** — correto. **QOCBM** — PROIBIDO.

## Available Units (10)

| Keyword | Descrição |
|---------|-----------|
| `PABM APODI` | ⭐ Comando PABM Apodi (default) |
| `SAT` | Secretaria 1ª SAT Pau dos Ferros |
| `CHEFIA` | Chefia 1ª SAT |
| `OP 3` | Operacional 3º GBM |
| `1º CAT` | 1º CAT Mossoró |

## ⚠️ Gotchas — Armadilhas Comuns

### 1. Processos com subpastas: sempre expandir lazy-loading
Processos grandes (ex: Livro de Fiscal) organizam documentos em subpastas (PASTA1, PASTA2...). A listagem padrão **não carrega** o conteúdo dessas pastas — documentos ficam invisíveis.
```python
# ❌ Errado — pode faltar documentos
tree = c.get_full_document_tree(proc_id)

# ✅ Correto — expande todas as subpastas
tree = c.get_full_document_tree(proc_id, expand_all=True)
```

### 2. Documentos em rascunho: trocar para a unidade dona do processo
Documentos **assinados** são visíveis de qualquer unidade. Documentos **em rascunho** (não assinados) só são visíveis quando logado na unidade que os criou.
```python
# Se precisa ler rascunhos do Livro de Fiscal (criado em OP 3ºGBM):
c.switch_unit('OP 3')  # trocar ANTES de listar/ler
tree = c.get_full_document_tree(proc_id, expand_all=True)
```
Sem isso, `get_editor_sections` e leituras via `src_url` falham com "Editor URL not found".

### 3. Criação de processos: sempre setar visibilidade explícita
O campo `rdoNivelAcesso` não tem default confiável. Sem setá-lo, a criação pode falhar silenciosamente (SEI fica na página "Iniciar Processo" sem redirecionar).
```python
# Sempre incluir:
rdoNivelAcesso = '0'  # 0=Público, 1=Restrito, 2=Sigiloso
```

### 4. Tipo de processo: consultar lista antes de criar
Os IDs de tipo (`selTipoProcedimento`) variam por instalação SEI. Usar o tipo errado cria o processo com classificação incorreta. Verificar a lista disponível na unidade antes de criar.

### 5. Ícones de assinatura na árvore do processo
Na lista de documentos do processo, o SEI usa ícones de caneta para indicar o estado de assinatura:
- **🖊️ Caneta preta** (`assinatura2.svg`) → documento **assinado e travado** (não editável)
- **✏️ Caneta amarela** → documento **assinado mas ainda editável** (minuta assinada que permite correções)
- **Sem caneta** → documento **não assinado** (rascunho)

Mesma lógica para **PDFs certificados**: ícone amarelo = recém-certificado, ícone preto = certificado há mais tempo.

Se editar um documento com caneta amarela, a assinatura é **removida automaticamente** pelo SEI. Caneta preta = final, sem volta.

### 6. Escape HTML acumulativo ao salvar documentos
O editor SEI retorna conteúdo das textareas com 1 nível extra de HTML escaping (ex: `&lt;p&gt;` no lugar de `<p>`). Se você salvar `sec.content` sem unescape, **cada save adiciona 1 camada de escape**, corrompendo o documento progressivamente.
```python
# ✅ Correto — unescape 1x TODAS as sections antes de salvar
from html import unescape
for sec in sections:
    sec.content = unescape(sec.content)
# agora modificar o conteúdo desejado, depois salvar
client.save_document(save_url, sections)
```
Sem isso, após 2-3 saves o corpo do documento aparece com tags HTML raw visíveis.

## Technical Notes

- **ISO-8859-1**: Sign form encodes cargo with `\xba` for º
- **infra_hash**: Session-bound hash on every URL. Navigate through the UI, never direct URLs
- **Cookie flow**: Login → SIP PHPSESSID → inicializar.php → NEW SEI PHPSESSID (hop-by-hop)
- **Editor sections**: Textarea names (e.g. `txaEditor_406`) vary by document type — always list first
- **After navigation**: Control page cache invalidates. Methods handle re-login automatically

### ⚠️ Editor Save — Seções Template-Locked

Algumas seções do editor (ex: `txaEditor_217` em despachos) **não aceitam conteúdo via HTTP POST** — o servidor retorna "OK N" mas não persiste a alteração. Isso afeta seções com variáveis de template (`@interessados_virgula_espaco@`).

**Workaround:** Colocar corpo + assinatura na **seção seguinte** (ex: `txaEditor_220`). Sempre testar qual seção aceita conteúdo antes de montar o documento.

### Marcadores — IDs PABM APODI

| ID | Nome |
|----|------|
| 64528 | Férias / Dispensas |
| 64956 | Diárias |
| 65235 | ALMOX |
| 65236 | LIVROS |
| 65237 | Equipamentos Operacional |
| 65263 | CURSOS ESPECIALIZAÇÃO |
| 65836 | Transferência de Unidade |
| 66042 | Materiais Quartel |
| 66043 | Armamento |
| 66186 | Escala Especial |
| 66588 | Informações |
| 72961 | Zen On |

**Aplicar:** POST no form `andamento_marcador_gerenciar` (URL via arvore page) com `selMarcador=<id>` + `txaTexto=<texto>` + `hdnIdMarcador=<id>` em Latin-1.

## Acompanhamento Especial (Arquivo Ativo)

Conceito: "gavetas de armário" — processo sai da caixa ativa (concluído) mas fica indexado por categoria. Descrições devem ser específicas (nome do militar, município, datas).

### Métodos sei-cli

```python
# Listar grupos existentes
grupos = c.listar_grupos_acompanhamento()  # [(id, nome), ...]

# Criar novo grupo
c.criar_grupo_acompanhamento("Pessoal")

# Adicionar processo ao acompanhamento
c.add_acompanhamento_especial(
    id_procedimento="48145432",
    grupo_id="148243",
    observacao="Reaprazamento ferias - CB Antonio - Dez/2025"
)
```

### Grupos Padrão (por unidade)

| Grupo | O que guarda |
|-------|-------------|
| Pessoal | Férias, dispensas, licenças, reaprazamentos, dados servidores |
| Operacional | Diárias operacionais, escalas, viaturas |
| Administrativo | Ofícios, suprimento de fundos, comunicados, convênios |
| Fiscalizacao | Denúncias, interdições, autos de infração |
| Atividades Tecnicas | Vistorias, pareceres, laudos técnicos |
| Normativos | Resoluções, portarias, diretrizes |
| Capacitacao | Cursos, treinamentos, COMSOC |
| Demandas Externas | MP, TCE, SENASP, outros órgãos |

### Fluxo HTTP (3 hops)

```
1. _ensure_control() → procedimento_trabalhar?id_procedimento=X
2. GET iframe src (procedimento_visualizar)
3. Regex acompanhamento_gerenciar na visualização
4. GET gerenciar → form frmAcompanhamentoCadastro
5. POST com selGrupoAcompanhamento + txaObservacao + hdnIdProtocolo
```

### Grupos criados

**Chefia SAT:** Pessoal(148243), Operacional(148244), Administrativo(148245), Fiscalizacao(148246), AT(148247), Normativos(148248), Capacitacao(148249), Demandas Externas(148250)

**PAD PDF:** Pessoal(148235), Operacional(148236), Administrativo(148237), Fiscalizacao(148238), AT(148239), Normativos(148240), Capacitacao(148241), Demandas Externas(148242)

**Obs:** Grupos são por unidade. A Chefia SAT também tem grupos antigos: DEMANDAS(108965), DESINTERDIÇÃO(108961), INTERDIÇÃO(108963), PARECER TÉCNICO COSERN(108967).

## Reference Files

| File | Content |
|------|---------|
| `references/templates-all.md` | 20 document templates with formatting |
| `references/document-creation.md` | Browser fallback for CKEditor (legacy) |
| `references/sei-pro-analysis.md` | SEI Pro extension reverse-engineering |
| `references/dom-selectors.md` | CSS selectors (browser fallback) |
| `references/js-patterns.md` | JavaScript patterns (browser fallback) |

## sei-cli Project

- **Repo**: `~/Projects/sei-cli/` (~4900 lines: client.py 4070 + cli.py 825)
- **Config**: `~/.config/sei/credentials.json`
- **Deps**: httpx, beautifulsoup4, lxml, click, rich
- **Tests**: 92 tests — `python3 -m pytest tests/ -q`

## Recurring Workflows

**Monthly — Auxílio Alimentação** (PABM Apodi + 1ªSAT):
~5 PDFs to authenticate + 1 Parte Genérica to sign per unit

**As needed — Escalas de serviço**:
Sign via block → download PDF → process with `processar_escala.py`

### 4. Assinatura é Ato Jurídico ⚠️
Nunca assinar um documento sem um pedido **explícito e inequívoco** do usuário (ex: "assine o relatório", "pode assinar"). Assinatura no SEI tem valor jurídico.
Sempre chame `get_block_documents()` (ou `get_full_document_tree` e inspecione `assinado`) **antes** de assinar para checar se já está assinado. O POST de assinatura *sempre* executa sem erro mesmo se já assinado.

### 5. Edição de Documentos e Escape HTML
Ao usar funções que injetam ou editam HTML no SEI (ex: `edit_document_section`), o framework já resolve a maioria dos escapes por causa do *url-encoding* do form POST. **Nunca** aplique escape HTML duplo (ex: `html.escape()`) se a função não pedir expressamente, senão as tags `<b>`, `<p>` aparecerão cruas para o usuário no SEI.

### 6. Troca Redundante de Unidade (`switch_unit`)
Nunca chame `switch_unit('UNIDADE')` se já estiver nela. O SEI pode corromper a sua sessão, fazendo operações subsequentes apontarem para a árvore de outro processo. Antes de trocar, confira em qual unidade você está ou confie no `sei-cli`, que já tem guard rails, mas evite no script.
> Dica de Ouro: `id_procedimento` e `id_documento` são numéricos e **imutáveis**. Apenas `infra_hash` muda por navegação. Se os IDs de um documento sumiram ou trocaram totalmente do nada, sua sessão corrompeu. Não invente que o ID "mudou".

### 7. Classificar Processos (Marcadores/Acompanhamento) "No Escuro"
**Nunca classifique ou adicione marcadores** a um processo lendo apenas o assunto ou a "especificação" da tabela. A especificação costuma ser genérica (ex: "Processos transferidos PARA o PABM" quando eram "DO PABM"). Sempre extraia a árvore de documentos (`get_full_document_tree`) e leia o conteúdo de pelo menos 1 documento (ex: ofício ou requerimento inicial) antes de decidir onde encaixar o processo.

### 8. Acompanhamento Especial: Alterar vs Delete+Re-Add
Para mudar o grupo ou a observação de um processo que **já está** em Acompanhamento Especial, use SEMPRE `c.alterar_acompanhamento_especial()`. Nunca tente remover o processo do acompanhamento para adicionar de novo, pois o formulário de adição depende de comportamentos em JS que quebram o fluxo puramente HTTP.
