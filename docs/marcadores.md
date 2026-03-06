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
1. Abrir pagina do processo (`procedimento_trabalhar`).
2. Encontrar acao `andamento_marcador_gerenciar` (fallback: `..._cadastrar`).
3. Parsear formulario de marcador.
4. POST com `marcador_id` e texto opcional.

### Remover marcador
1. Abrir processo.
2. Encontrar acao `andamento_marcador_remover`.
3. Executar GET e, se houver formulario de confirmacao, POST com campos hidden.

## Parse de marcador na lista de processos
O campo `Process.marcador` ja era preenchido no parser por `aria-label` do icone de marcador.

## Teste online
Nao executado neste ambiente por bloqueio de rede/DNS para `sei.rn.gov.br`.
