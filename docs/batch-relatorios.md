# Batch de Relatorios de Livro de Fiscal

## API
- `SEIClient.batch_read_relatorios(id_procedimento, unit="OP 3") -> dict`
- `relatorio_parser.summarize_batch(relatorios) -> str` (Markdown)

## O que o batch retorna
- total de documentos no processo
- total de documentos com nome de relatorio/livro/fiscal
- total de relatorios lidos
- falhas de parse por documento
- `resumo_markdown`
- lista estruturada dos relatorios parseados

## Resumo semanal (Markdown)
`summary_batch` gera secoes:
- `Escala e Efetivo`: variacoes de extraordinario/permuta entre dias
- `Viaturas`: mudancas de situacao por prefixo, destacando transicao operante -> inoperante
- `Ocorrencias por Dia`: total e tipos por dia
- `Assuntos Gerais (Destaques)`

## Heuristica de selecao dos documentos
No processo, sao considerados relatorios documentos com nome contendo:
- `RELAT`
- `LIVRO`
- `FISCAL`

## Teste em processo real OP 3ºGBM
Nao foi possivel executar neste ambiente devido a indisponibilidade de rede para o host do SEI.

### Script sugerido
```python
from sei_cli.client import SEIClient

with SEIClient() as c:
    c.login()
    result = c.batch_read_relatorios("<id_procedimento>", unit="OP 3")
    print(result["resumo_markdown"])
```
