# Marcadores

## API
- `SEIClient.list_marcadores() -> list[Marcador]`
- `SEIClient.set_marcador(id_procedimento, marcador_id, texto="") -> bool`
- `SEIClient.remove_marcador(id_procedimento) -> bool`

## Parsers adicionados
- `parse_marcadores_list(html, base_url)`
- `parse_marcador_form(html, base_url, current_url)`

## Fluxo implementado
### Listar catalogo
1. Abrir tela de controle.
2. Encontrar link `marcador_listar` no menu.
3. Parsear tabela de marcadores (id, nome, descricao e cor por icone SVG).

### Definir marcador no processo
1. Confirmar que o processo aparece na caixa da unidade atual (`recebidos` ou `gerados`).
2. Abrir pagina/gerenciamento do processo visivel na unidade atual.
3. Encontrar acao `andamento_marcador_gerenciar` (fallback: `..._cadastrar`).
4. Parsear formulario de marcador.
5. POST com `marcador_id` e texto opcional.

Regra canonica:

- marcador e por ambiente/unidade
- processo visivel na caixa da unidade atual pode ser marcado ali, mesmo que tenha sido criado em outra unidade
- o mesmo processo pode ter marcadores diferentes em unidades diferentes
- falha de `process-read` nao bloqueia marcacao; ela so reduz a qualidade da classificacao/sugestao de texto
- a investigacao padrao para sugestao de texto e `contextual`; usar `fast` so por escolha explicita ou fallback, e `deep`/`all` so quando o usuario pedir aprofundamento
- no modo `contextual`, processos grandes com varias unidades devem preservar os documentos iniciais e priorizar documentos CBM quando a arvore indicar `UNIDADE_GERADORA`

### Remover marcador
1. Abrir processo.
2. Encontrar acao `andamento_marcador_remover`.
3. Executar GET e, se houver formulario de confirmacao, POST com campos hidden.

## Parse de marcador na lista de processos
O campo `Process.marcador` ja era preenchido no parser por `aria-label` do icone de marcador.

## Teste online
Nao executado neste ambiente por bloqueio de rede/DNS para `sei.rn.gov.br`.
