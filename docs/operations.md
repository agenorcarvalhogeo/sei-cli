# Operacoes Canonicas e Roadmap de Evolucao

## Objetivo

Transformar o `sei-cli` em uma camada operacional previsivel para uso local
com agentes como Claude Code e OpenClaw, reduzindo improviso da LLM e
centralizando os fluxos corretos no codigo.

A estrategia adotada e:

1. Consolidar **comandos de alto nivel** para as intencoes mais comuns.
2. Padronizar **contratos JSON** estaveis para consumo por skills/agentes.
3. Mapear **workflows declarativos** para orientar o proximo passo valido.
4. Evoluir para MCP apenas depois que a interface operacional estiver madura.

## Principios

- O conhecimento fragil do SEI deve morar no codigo, nao no prompt.
- A skill deve usar sempre a operacao canonica mais especifica disponivel.
- Quando houver comando canonico, o agente nao deve montar fluxo alternativo.
- Toda operacao deve validar pre-condicoes e falhar de forma fechada.
- O output para automacao deve ser JSON versionado e previsivel.
- Workflows YAML devem representar regra de negocio, nao detalhes HTTP.
- Escritas sensiveis devem vir depois, com `preview` + `confirm`.

## Arquitetura Alvo

```text
Skill (OpenClaw / Claude Code)
  -> comandos canonicos do CLI (--json)
    -> camada sei_cli.operations
      -> SEIClient
        -> SEI RN (HTTP puro)
```

### Responsabilidades por camada

#### `sei_cli/client.py`
- Login, cookies, `infra_hash`, redirects, encoding, navegacao e parsing HTTP.
- Metodos tecnicos e reaproveitaveis.

#### `sei_cli/operations/`
- Operacoes orientadas a intencao.
- Resolucao de contexto e IDs.
- Validacao de entradas.
- Sequencia de passos suportada.
- Pos-condicoes e proximas acoes permitidas.
- Contratos JSON estaveis.

#### CLI (`sei_cli/cli.py`)
- Interface humana e automacao local.
- `rich` para leitura humana.
- `--json` para consumo por agentes.

#### `workflows/`
- Mapeamento declarativo do processo de negocio por orgao.
- Referencias sobre atores, etapas, decisoes e transicoes validas.

## Escopo da Primeira Onda

Comecar apenas com operacoes de leitura e navegacao, que oferecem alto ganho
e baixo risco.

### Operacoes iniciais

#### `inbox-snapshot`
Mostra contexto atual da sessao:
- status da sessao
- unidade atual
- total de processos recebidos
- total de processos gerados
- processos novos
- blocos relevantes

#### `process-open`
Abre um processo por numero SEI ou `id_procedimento` e devolve:
- identificadores resolvidos
- metadados basicos
- arvore/lista de documentos
- sugestao de proximas acoes de leitura

#### `process-read`
Le o processo com mais contexto do que `process-open`:
- documentos
- indicadores uteis para triagem
- opcionalmente marcadores, bloco, unidade e resumo simples

#### `document-read`
Le um documento por numero SEI ou IDs internos e devolve:
- IDs resolvidos
- metadados do documento
- texto limpo
- tipo detectado
- proximas acoes sugeridas

#### `relatorio-read`
Le um relatorio operacional e devolve estrutura parseada:
- equipe
- viaturas
- ocorrencias
- observacoes
- resumo legivel

#### `block-review`
Le um bloco e devolve:
- documentos contidos
- status de assinatura
- unidade origem/destino
- proximas acoes de leitura

## Estado Atual da Camada Documental

Esta frente foi considerada estavel para uso real:

- `document-create-preview`
- `document-create-confirm`
- `document-edit-preview`
- `document-edit-confirm`
- `document-quality-check`

Capacidades estabilizadas:

- heranca real de acesso do processo na criacao documental
- resolucao de tipo documental pelo formulario real
- identificacao de secoes `editable` vs `readOnly`
- gravacao na secao editavel correta
- reler documento apos gravacao
- quality-check com sinais de padronizacao e placeholders

Observacao importante:

- `empty_body_check` continua sendo heuristico
- o proximo refinamento desejado e expor `document_version`
- com isso, o contrato deve ganhar `is_pristine_document`
- para documento "zero bala", o sinal principal deve ser a versao, nao o conteudo do template

## Proximo Escopo: Blocos de Assinatura

Depois da camada documental, a proxima frente prioritaria e blocos de assinatura.

### Objetivo

Permitir fluxo canonico de:

1. listar blocos relevantes
2. revisar documentos pendentes no bloco
3. disponibilizar/cancelar disponibilizacao
4. incluir/remover documento do bloco
5. assinar documentos do bloco com preflight de unidade
6. reler status apos assinatura

### Ordem recomendada

#### Fase 1. Leitura e triagem

- `signature-block-list`
- `signature-block-read`
- `signature-block-review`

Essas canônicas devem devolver:

- numero do bloco
- estado
- unidade origem
- unidade destino
- documentos contidos
- quantos estao assinados
- quantos estao pendentes
- proximas acoes validas

#### Fase 2. Mutacoes seguras de bloco

- `signature-block-create-preview`
- `signature-block-create-confirm`
- `signature-block-add-document-preview`
- `signature-block-add-document-confirm`
- `signature-block-remove-document-confirm`
- `signature-block-disponibilizar-confirm`
- `signature-block-cancel-confirm`
- backlog: `signature-block-update-destinations-preview`
- backlog: `signature-block-update-destinations-confirm`

Todas com `preview` + `confirm` quando houver risco operacional.

Backlog adicional de bloco:

- permitir adicionar/remover unidades destino de um bloco de assinatura de forma canônica
- usar isso para cenários de assinatura por unidade destinatária sem recriar bloco
- manter leitura/revisão de destinos antes de mutar o bloco
- suportar ciclo de vida reutilizável do bloco:
  - ir para a unidade dona do bloco
  - cancelar disponibilizacao quando o bloco estiver disponibilizado
  - ajustar o conjunto de documentos no bloco
  - disponibilizar novamente para a unidade destinataria
  - usar isso para preparar um bloco reutilizavel com novos documentos pendentes
- backlog: `signature-block-recall-preview`
- backlog: `signature-block-recall-confirm`
- backlog: `signature-block-refresh-preview`
- backlog: `signature-block-refresh-confirm`

#### Fase 3. Assinatura canonica

- `signature-block-sign-preview`
- `signature-block-sign-confirm`

Pre-condicoes obrigatorias:

- unidade correta acessivel
- documento realmente pendente
- cargo/filiacao validos para assinatura
- credenciais validas

Pos-condicoes obrigatorias:

- confirmar novo status de assinatura
- devolver documentos assinados
- reler bloco apos assinatura

### Contrato minimo sugerido para blocos

```json
{
  "schema_version": "1",
  "ok": true,
  "operation": "signature-block-read",
  "context": {},
  "resolved_ids": {
    "block_numero": "774681"
  },
  "data": {
    "block": {},
    "documents_total": 0,
    "signed_total": 0,
    "pending_total": 0
  },
  "next_actions": [],
  "warnings": [],
  "error": null
}
```

### Riscos a tratar desde o inicio

- bloco em unidade sem acesso
- documento ja assinado
- documento sem link valido de assinatura
- cargo divergente no formulario
- assinatura parcial com falha no meio do lote
- retorno do bloco apos assinatura
- bloco disponibilizado em outra unidade exigindo recolhimento antes de manutencao
- parser da arvore do processo marcando `assinado=false` para documentos ja assinados

## Proximo Escopo: Marcadores de Processo

Esta frente agora passa a ter uma camada canônica inicial focada no fluxo por processo específico.

### Objetivo

- contextualizar rapidamente do que trata o processo
- sugerir texto curto de marcador a partir da leitura canônica do processo
- aplicar marcador ao processo com `preview` + `confirm`
- remover marcador pelo fluxo atual do processo

### Primeira leva implementada

- `marker-catalog`
- `process-marker-preview`
- `process-marker-set-preview`
- `process-marker-set-confirm`
- `process-marker-remove-preview`
- `process-marker-remove-confirm`

### Regra de uso nesta fase

- usar apenas processos de teste para validação real
- a sugestão de texto do marcador é derivada de `process-summary`
- a canônica atual cobre o fluxo dentro do processo específico

### Segunda fase planejada

- gestão granular de múltiplos marcadores no mesmo processo
- leitura do histórico de marcadores
- alteração de texto de marcador existente
- mutação em lote pelo Controle de Processos:
  - selecionar um ou mais processos
  - adicionar marcador
  - remover marcador
- leitura mais precisa de prazo/manifestações para enriquecer a sugestão do texto do marcador

### Fluxo canonico adicional: bloco reutilizavel

Este fluxo ficou validado como necessidade operacional real.

Objetivo:

- reaproveitar o mesmo bloco de assinatura ao longo do processo
- recolher o bloco quando necessario
- trocar os documentos contidos
- redisponibilizar para a unidade que vai assinar

Sequencia desejada:

1. `signature-block-read`
2. `signature-block-recall-preview`
3. `signature-block-recall-confirm`
4. `signature-block-add-document-preview`
5. `signature-block-add-document-confirm`
6. `signature-block-remove-document-confirm`
7. `signature-block-disponibilizar-confirm`
8. `signature-block-sign-preview`
9. `signature-block-sign-confirm`

Pre-condicoes importantes:

- a manutencao do bloco deve ocorrer na unidade dona do bloco
- se o bloco estiver disponibilizado, a canônica deve orientar recolhimento/cancelamento antes da mutacao
- a canônica deve deixar claro quando a unidade atual só pode assinar e quando pode administrar o bloco

### Regra operacional: assinatura local vs assinatura por bloco

Existem dois fluxos distintos e eles nao devem ser misturados:

1. Assinatura por bloco disponibilizado

- usar quando o signatario nao tem acesso a unidade geradora do documento
- o documento e colocado em bloco de assinatura
- o bloco e disponibilizado para a outra unidade
- a assinatura deve ocorrer na unidade destinataria, pelo fluxo `signature-block-sign-*`

2. Assinatura local da unidade geradora

- usar quando o proprio usuario da unidade geradora vai assinar
- se o documento estiver em bloco disponibilizado, primeiro e necessario cancelar a disponibilizacao do bloco
- depois disso a assinatura deve ocorrer no ambiente da unidade geradora, pelo fluxo normal de assinatura de documento
- nesse caso, nao usar `signature-block-sign-*`

Consequencias para testes e canônicas:

- todo teste de `signature-block-sign-*` precisa considerar a unidade destinataria do bloco disponibilizado
- todo teste de assinatura local precisa garantir que o bloco nao esteja disponibilizado
- quando houver erro de assinatura, o diagnostico deve primeiro verificar se o fluxo escolhido bate com a logistica do bloco

### Backlog imediato acoplado a esta fase

1. Expor `document_version` nas canônicas documentais.
2. Adicionar `is_pristine_document` ao `document-quality-check`.
3. Rebaixar `empty_body_check` para heuristica auxiliar.
4. Usar `is_pristine_document` como sinal principal antes de assinatura/PDF.

## Contrato JSON Padrao

Toda operacao canonica deve expor um contrato estavel com esta estrutura:

```json
{
  "schema_version": "1",
  "ok": true,
  "operation": "document-read",
  "context": {
    "unidade_sigla": "OP 3",
    "usuario": "Fulano"
  },
  "resolved_ids": {
    "numero_processo": "08810058.000128/2026-69",
    "id_procedimento": "47607237",
    "numero_documento": "39860248",
    "id_documento": "48568466"
  },
  "data": {},
  "next_actions": [
    {
      "action": "process-open",
      "label": "Abrir processo relacionado"
    }
  ],
  "warnings": [],
  "error": null
}
```

### Regras do contrato

- `schema_version` deve existir desde a primeira versao.
- `ok` indica sucesso ou falha.
- `operation` identifica a operacao executada.
- `context` traz contexto minimo da sessao atual.
- `resolved_ids` concentra toda resolucao de identificadores.
- `data` contem a carga util da operacao.
- `next_actions` limita o proximo passo recomendado.
- `warnings` registra desvios nao fatais.
- `error` descreve o problema quando `ok=false`.

### Estrutura recomendada de erro

```json
{
  "code": "document_not_found",
  "message": "Documento 39860248 nao encontrado na unidade atual.",
  "retryable": false,
  "details": {}
}
```

Codigos iniciais sugeridos:
- `auth_required`
- `session_invalid`
- `unit_not_found`
- `process_not_found`
- `document_not_found`
- `block_not_found`
- `unsupported_state`
- `workflow_violation`
- `network_error`
- `parse_error`

## Regras Operacionais para Skills

As skills devem seguir estas regras:

1. Usar sempre o comando canonico mais especifico disponivel.
2. Preferir `--json` em todas as chamadas automatizadas.
3. Nunca montar URLs do SEI manualmente.
4. Nunca montar fluxos alternativos quando houver comando canonico.
5. Respeitar `next_actions` como guia do passo seguinte.
6. Em caso de falha, relatar `error.message` e nao improvisar.
7. Em operacoes sensiveis futuras, exigir confirmacao explicita do usuario.

## Evolucao dos Workflows YAML

Os YAMLs em `workflows/` devem deixar de descrever apenas a historia do
processo e passar a apontar para operacoes canonicas.

### Forma atual
- Focada em etapas de negocio.
- Boa para documentacao.
- Ainda nao esta diretamente conectada ao CLI.

### Forma desejada

Exemplo conceitual:

```yaml
nome: Reaprazamento de Ferias
orgao: cbmrn

etapas:
  - ordem: 1
    id: abrir_processo
    operation: process-open
    requires: []
    allowed_next:
      - ler_requerimento

  - ordem: 2
    id: ler_requerimento
    operation: document-read
    requires:
      - abrir_processo
    allowed_next:
      - ler_despacho
```

### Campos novos recomendados

- `id`
- `operation`
- `requires`
- `allowed_next`
- `approval_required`
- `notes`
- `examples`

### Regra

Workflow YAML deve dizer:
- qual operacao usar
- em que ordem
- quais dependencias existem
- quais proximas etapas sao permitidas

Nao deve dizer:
- qual URL chamar
- qual `infra_hash` usar
- qual POST tecnico reproduzir

## Estrutura de Codigo Proposta

```text
sei_cli/
  operations/
    __init__.py
    contracts.py
    errors.py
    reading.py
    workflows.py
```

### `contracts.py`
- dataclasses ou TypedDicts dos contratos de operacao
- serializacao consistente para JSON

### `errors.py`
- erros semanticos da camada de operacoes
- mapeamento para `error.code`

### `reading.py`
- operacoes iniciais de leitura
- orquestracao sobre o `SEIClient`

### `workflows.py`
- carga e validacao dos YAMLs
- resolucao de proxima etapa valida

## Backlog por Arquivo

### 1. `docs/operations.md`
Responsabilidade:
- ser a referencia viva da superficie canonica

Entregas:
- catalogo de operacoes
- contrato JSON
- criterios de aceite

### 2. `sei_cli/operations/contracts.py`
Responsabilidade:
- definir estruturas padrao de resposta

Entregas:
- `OperationResult`
- `OperationError`
- `NextAction`
- helpers para serializacao

### 3. `sei_cli/operations/errors.py`
Responsabilidade:
- padronizar erros da camada de operacoes

Entregas:
- excecoes como `ProcessNotFoundError`, `DocumentNotFoundError`
- conversao para `error.code`

### 4. `sei_cli/operations/reading.py`
Responsabilidade:
- implementar operacoes de leitura

Entregas iniciais:
- `inbox_snapshot(client, ...)`
- `process_open(client, numero_ou_id, ...)`
- `process_read(client, numero_ou_id, ...)`
- `document_read(client, numero_ou_id, ...)`
- `relatorio_read(client, numero_ou_id, ...)`
- `block_review(client, bloco, ...)`

### 5. `sei_cli/operations/workflows.py`
Responsabilidade:
- carregar workflows e resolver proximos passos

Entregas:
- listar workflows por orgao
- abrir workflow
- obter proxima etapa permitida
- validar integridade do YAML

### 6. `sei_cli/cli.py`
Responsabilidade:
- expor comandos canonicos

Entregas iniciais:
- `sei inbox-snapshot`
- `sei process-open`
- `sei process-read`
- `sei document-read`
- `sei relatorio-read`
- `sei block-review`
- output humano enxuto + `--json`

### 7. `tests/`
Responsabilidade:
- garantir estabilidade da interface

Entregas:
- testes unitarios das operacoes
- testes de contrato JSON
- fixtures/minimos para erros e edge cases

## Ordem Recomendada de Implementacao

### Fase 1. Fundacao
- criar `sei_cli/operations/`
- definir contratos em `contracts.py`
- definir erros em `errors.py`

### Fase 2. Primeiras operacoes
- implementar `inbox-snapshot`
- implementar `process-open`
- implementar `document-read`

### Fase 3. Exposicao no CLI
- adicionar comandos novos no `cli.py`
- garantir `--json`
- manter comandos antigos intactos

### Fase 4. Testes de contrato
- golden tests do JSON
- testes de falha controlada
- testes com fixtures offline

### Fase 5. Expansao de leitura
- `process-read`
- `relatorio-read`
- `block-review`

### Fase 6. Integracao com workflows
- loader YAML
- `workflow-show`
- `workflow-next`

### Fase 7. Endurecimento da skill
- atualizar a skill para usar apenas a superficie canonica
- documentar proibicoes de improviso operacional

## Criterios de Aceite por Operacao

Cada operacao nova so entra como canonica quando cumprir:

1. Resolve IDs de forma consistente.
2. Nao exige que a skill conheca detalhes HTTP.
3. Retorna JSON estavel e versionado.
4. Fornece `next_actions`.
5. Falha com `error.code` previsivel.
6. Tem teste offline cobrindo o contrato.
7. Tem pelo menos um exemplo de uso documentado.

## Melhorias de UX para Agentes

### Preferencias de naming
- usar nomes de comandos descritivos e curtos
- evitar verbos tecnicos demais
- preferir `process-open` a `get-process-tree`

### Preferencias de output
- incluir identificadores resolvidos sempre
- nao devolver HTML bruto por padrao
- resumir o contexto da unidade atual
- limitar texto muito longo, com opcao de detalhe quando necessario

### Preferencias de navegacao
- permitir numero SEI ou ID interno quando possivel
- resolver internamente e devolver ambos no resultado
- indicar claramente quando a unidade atual nao tem acesso

## Backlog de Casos Operacionais

### Issue 25. Processo fora da unidade acessivel ou com restricao de acesso

Contexto:
- em alguns casos o usuario conhece o numero do processo, mas nao tem acesso a
  unidade em que ele esta aberto
- nesses casos, documentos nao assinados podem ficar indisponiveis para leitura
- processos/documentos privados, restritos ou sigilosos tambem podem bloquear
  leitura total ou parcial

Objetivo:
- a operacao canonica deve continuar sendo util mesmo quando a leitura completa
  nao for possivel
- o agente precisa saber exatamente o que foi lido, o que nao foi lido e por que

Comportamento esperado:
- `process-open`, `process-read`, `document-read` e `process-report` devem
  distinguir entre:
  - falta de acesso a unidade geradora
  - documento nao assinado fora da unidade acessivel
  - processo/documento privado ou restrito
  - processo/documento sigiloso
- a resposta JSON deve marcar leitura parcial de forma explicita
- a operacao nao deve mascarar o problema como erro generico de parser

Sinais que devem aparecer no contrato:
- `preflight.access_status`
- `preflight.required_unit`
- `preflight.access_limited`
- `read_summary.partial_read`
- `warnings` com motivo operacional legivel
- `error.code` especifico quando a leitura falhar totalmente

Codigos de erro sugeridos:
- `unit_access_required`
- `document_unavailable_in_current_unit`
- `restricted_access`
- `private_access`
- `classified_access`
- `partial_visibility`

Proximas acoes esperadas:
- informar ao usuario que a unidade atual nao permite leitura completa
- informar se existe unidade acessivel alternativa
- informar quais documentos ficaram ocultos ou nao assinados
- permitir que o restante do processo ainda seja resumido com sinalizacao de
  cobertura parcial

Impacto nas canonicas:
- `process-read` deve conseguir devolver analise parcial do processo
- `process-report` deve propagar lacunas de visibilidade no relatorio final
- `relatorio-read` deve dizer claramente quando o documento existe, mas nao pode
  ser lido naquele contexto operacional

## Riscos Conhecidos

### Risco: duplicar logica entre CLI e operacoes
Mitigacao:
- toda regra nova entra primeiro na camada `operations`
- o CLI so adapta entrada/saida

### Risco: skill continuar improvisando
Mitigacao:
- reduzir a skill
- explicitar comandos canonicos
- padronizar `next_actions`

### Risco: congelar interface cedo demais
Mitigacao:
- comecar com leitura
- observar uso real
- promover a MCP apenas o que ficar estavel

### Risco: workflows virarem burocracia
Mitigacao:
- manter YAML enxuto
- mapear apenas fluxos recorrentes
- nao modelar tudo cedo demais

## Plano de Validacao

### Validacao tecnica
- rodar `pytest tests/ -v`
- adicionar testes de contrato para cada operacao
- validar serializacao JSON

### Validacao operacional
- usar localmente com skill em rotinas reais de leitura
- observar onde a LLM ainda tenta desviar
- ajustar nomes de comandos, payloads e `next_actions`

### Sinais de maturidade para evoluir a MCP
- comandos canonicos estaveis por pelo menos algumas semanas de uso
- poucos ajustes de naming/contrato
- skill usando majoritariamente a superficie nova
- erros bem classificados e previsiveis

## Milestone 1

Objetivo:
- entregar a primeira superficie canonica de leitura

Escopo:
- `inbox-snapshot`
- `process-open`
- `document-read`
- contrato JSON v1
- testes de contrato

Definicao de pronto:
- skill consegue consultar caixa, abrir processo e ler documento sem montar
  fluxo manual
- CLI retorna JSON confiavel
- falhas comuns retornam `error.code` previsivel

## Milestone 2

Objetivo:
- adicionar leitura contextual e workflows

Escopo:
- `process-read`
- `relatorio-read`
- `block-review`
- loader de workflows
- `workflow-show`
- `workflow-next`

## Milestone 3

Objetivo:
- preparar a superficie para futuras mutacoes e MCP

Escopo:
- operacoes de escrita em modo controlado
- `preview` + `confirm`
- consolidacao da skill
- avaliacao formal da migracao para MCP

## Decisao de Arquitetura

Neste momento, a decisao oficial do projeto e:

- **Nao** migrar direto para MCP.
- **Sim** construir primeiro uma camada de operacoes canonicas no CLI.
- **Sim** usar workflows/YAML para guiar o fluxo de negocio.
- **Sim** usar essa camada como futura base de um MCP local, se o uso real
  provar que a interface estabilizou.
