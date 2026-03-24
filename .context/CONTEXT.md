# SEI CLI — Project Context

> Leia este arquivo antes de modificar qualquer coisa neste projeto.

## Arquitetura

- **Stack:** Python 3.12 + httpx + BeautifulSoup + click + rich
- **Entry point:** `sei` CLI (pip install -e .)
- **Client:** `sei_cli/client.py` — toda lógica HTTP centralizada aqui
- **Parser:** `sei_cli/relatorio_parser.py` — extração de dados de relatórios do Livro de Fiscal

## Padrões Obrigatórios

### Sessão HTTP
- `_ensure_session()` valida sessão antes de qualquer operação (GET antes de POST)
- `batch_mode()` context manager para operações em lote (evita re-login)
- `_navigate_with_retry()` faz retry automático em caso de sessão expirada
- `_harvest_hashes()` coleta `infra_hash` de toda resposta HTML — SEI usa hashes em TODAS as URLs

### Auth
- Credenciais vêm do Bitwarden (alias `sei` / `sisbom`)
- NUNCA hardcodar credenciais
- Auto-login: se sessão expirou, re-login transparente + retry 1x

### Ambientes (Unidades)
- Para editar/assinar/encaminhar: DEVE estar no ambiente correto
- `sei switch <unidade>` ou `--unit` no goto
- Pesquisa rápida funciona de qualquer ambiente
- `trocar_unidade(id_or_name)` / `switch_unit()` — troca sessão SEI programaticamente
- `listar_unidades_usuario()` — navega form `infra_trocar_unidade`, POSTs com orgão CBM (28), parseia `selecionarUnidade(id)` do resultado
- **Form parsing:** O SEI usa `selecionarUnidade(ID)"/>` + `<td>SIGLA</td>` (input, não anchor)

### Comando `goto`
- SEMPRE usar `sei goto <numero>` para navegar (aceita doc ou processo)
- `--read` lê conteúdo inline
- Evitar percorrer listas manualmente

## Convenções de Código

- Tipo annotations em todas as funções públicas
- Docstrings em português para comandos CLI, inglês para internals
- Erros HTTP: logar com `rich.console` e retornar gracefully (não crashar)
- Novos comandos: adicionar em `sei_cli/commands/` como click group

## Testes

- `pytest` com fixtures de HTML mockado
- Testar parsing de HTML do SEI (muda entre versões)

## Armadilhas Conhecidas

- SEI muda `infra_hash` entre requests — nunca cachear hashes entre sessões
- Blocos disponibilizados: cancelar antes de editar/assinar docs neles
- **`chkSinManterAberto`:** Checkbox de "manter aberto" no enviar processo usa valor `"on"`, NÃO `"S"`. Confirmado no código-fonte SEI (sei-ev/sei.js)
- **`enviar_processo`:** Aceita lista de unidades. `selUnidades` = primeira, `hdnUnidades` = comma-separated IDs
- **`reabrir_processo`:** 3-tier strategy (Nos[0] href → full HTML search → AJAX). O JS `reabrirProcesso()` é gerado inline SOMENTE quando o processo está fechado na unidade atual — não existe em JS externo
- **Troca de unidade:** Form `frmInfraSelecaoUnidade` com POST `selInfraOrgaoUnidade=28` (CBM) lista sub-unidades, depois POST `selInfraUnidades=ID` efetua a troca
- O login form usa campo `hdnToken` que muda a cada request
- Rate limiting informal: não fazer mais de ~5 req/s ou a sessão cai
