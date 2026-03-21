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
- O login form usa campo `hdnToken` que muda a cada request
- Rate limiting informal: não fazer mais de ~5 req/s ou a sessão cai
