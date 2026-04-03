---
name: sei
description: "Operar o SEI via canônicas do sei-cli: leitura de processos/documentos, criação/edição de rascunhos, marcadores, triagem de ambiente, blocos de assinatura, finalização, encaminhamento, conclusão, reabertura e geração de PDFs."
---

> Fonte desta skill: `~/Projects/sei-cli/skills/openclaw/SKILL.md`
> Instalação local: `ln -sf ~/Projects/sei-cli/skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/sei/SKILL.md`

## Regra principal

Use **sempre as canônicas do CLI** quando houver uma para a tarefa. Não prefira métodos brutos do `SEIClient` nem comandos legados se a superfície canônica já existir.

## Superfície canônica atual

### Leitura

- `sei inbox-snapshot --json`
- `sei process-open <processo> --json`
- `sei process-read <processo> --json`
- `sei process-summary <processo> --json`
- `sei process-report <processo> --json`
- `sei document-read <documento> --process-id <processo> --json`
- `sei relatorio-read <documento> --process-id <processo> --json`

### Criação e edição de rascunho

- `sei process-create-preview ... --json`
- `sei process-create-confirm ... --confirm --json`
- `sei document-create-preview ... --json`
- `sei document-create-confirm ... --confirm --json`
- `sei document-edit-preview ... --json`
- `sei document-edit-confirm ... --confirm --json`
- `sei document-quality-check ... --json`

### PDF nativo

- `sei process-pdf-preview <processo> --json`
- `sei process-pdf-confirm <processo> --json`
- `sei document-pdf-preview <documento> --process-id <processo> --json`
- `sei document-pdf-confirm <documento> --process-id <processo> --json`

### Marcadores e triagem

- `sei marker-catalog --json`
- `sei process-marker-preview <processo> --json`
- `sei process-marker-read <processo> --json`
- `sei process-marker-history <processo> --json`
- `sei process-marker-set-preview <processo> --marker <nome-ou-id> --json`
- `sei process-marker-set-confirm <processo> --marker <nome-ou-id> --confirm --json`
- `sei process-marker-update-preview <processo> --text "<texto>" --json`
- `sei process-marker-update-confirm <processo> --text "<texto>" --confirm --json`
- `sei process-marker-remove-preview <processo> --json`
- `sei process-marker-remove-confirm <processo> --confirm --json`
- `sei environment-triage-preview [--mode fast|contextual|deep] --json`
- `sei environment-triage-apply ... --confirm --json`

### Encaminhamento, conclusão e reabertura

- `sei process-forward-preview <processo> <destinos...> --json`
- `sei process-forward-confirm <processo> <destinos...> --confirm --json`
- `sei process-conclude-preview <processo> --json`
- `sei process-conclude-confirm <processo> --confirm --json`
- `sei process-reopen-preview <processo> [--unit <unidade>] --json`
- `sei process-reopen-confirm <processo> [--unit <unidade>] --confirm --json`

### Finalização de documentos de um processo

- `sei process-finalize-preview <processo> [docs...] --json`
- `sei process-finalize-confirm <processo> [docs...] --confirm --json`

### Blocos de assinatura

- `sei signature-block-list --json`
- `sei signature-block-read <bloco> --json`
- `sei signature-block-review <bloco> --json`
- `sei signature-block-add-document-preview <bloco> <doc> --json`
- `sei signature-block-add-document-confirm <bloco> <doc> --confirm --json`
- `sei signature-block-recall-preview <bloco> --json`
- `sei signature-block-recall-confirm <bloco> --confirm --json`
- `sei signature-block-refresh-preview <bloco> ... --json`
- `sei signature-block-refresh-confirm <bloco> ... --confirm --json`
- `sei signature-block-sign-preview <bloco> --json`
- `sei signature-block-sign-confirm <bloco> --confirm --json`

## Comandos legados: não preferir

Se existir canônica equivalente, **não** use por padrão:

- `encaminhar`
- `concluir`
- `reabrir`
- `sign`
- `authenticate`
- `read-doc`
- `read-relatorio`
- `block-add`
- `block-create`
- `block-disponibilizar`
- `block-cancelar`
- `block-delete`
- `block-devolver`
- `block-remove`

Esses comandos só entram se o usuário pedir explicitamente o legado ou se houver alguma lacuna real na canônica.

## Política de confirmação

### Exigem confirmação explícita do usuário

- assinar documento
- assinar bloco
- autenticar/certificar documento externo
- encaminhar processo para outra unidade
- concluir processo
- reabrir processo
- cancelar, excluir ou remover artefatos consolidados

### Não exigem segunda confirmação se o pedido do usuário já for explícito

- criar processo de teste
- criar documento rascunho
- editar conteúdo do rascunho
- rodar `document-quality-check`
- gerar PDF
- ler e resumir processos/documentos
- aplicar/atualizar marcador em triagem organizacional

## Regras operacionais por fluxo

### 1. Documento: criar e redigir

Fluxo padrão:

1. `document-create-preview`
2. `document-create-confirm`
3. `document-edit-preview`
4. `document-edit-confirm`
5. `document-quality-check`
6. `document-read`

Não parar para pedir uma segunda autorização entre criar e salvar rascunho se o usuário já pediu explicitamente o documento.

### 2. Assinatura local vs assinatura por bloco

São fluxos diferentes.

- **Assinatura local:** assinar na unidade geradora com `process-finalize-*` ou `sign_document`, depois de recolher o bloco se ele estiver disponibilizado.
- **Assinatura por bloco:** usar `signature-block-sign-*` apenas na unidade destinatária do bloco disponibilizado.

Cenário de referência validado: `CMDO PABM APODI -> PAD-PDF`.

### 3. `process-finalize`

Use para finalizar um processo misto com PDFs externos + documentos internos.

Regras:

- PDFs externos vão para autenticação.
- Documentos internos só vão para assinatura se:
  - o formulário de assinatura confirmar o usuário/cargo atual
  - e o final do texto for compatível com o signatário esperado
- ambiguidade no rodapé -> `skip` por padrão
- `--force-sign` só quando a checagem do formulário bater

### 4. Encaminhamento

`process-forward-*` tem duas famílias de campo distintas:

- `retorno programado`
  - `--retorno-em`
  - `--retorno-dias`
  - `--retorno-dias-uteis`
- `reabertura programada`
  - `--reabrir-em`
  - `--reabrir-dias`
  - `--reabrir-dias-uteis`

Regras:

- `reabertura programada` só faz sentido quando o processo fecha na origem (`--fechar`)
- não misturar data e dias na mesma família
- se o destino for ambíguo, falhar fechado e pedir que o usuário escolha a unidade certa

### 5. Conclusão

Use `process-conclude-*`.

Modos:

- definitivo
- com reabertura programada por data
- com reabertura programada por dias

No formulário real:

- `rdoConcluir=S` -> definitivo
- `rdoConcluir=V` -> concluir com reabertura programada

### 6. Reabertura

Use `process-reopen-*`.

Regras:

- a unidade que consegue reabrir é a que concluiu o processo
- `--unit` é preferência, não garantia
- o preview tenta:
  1. unidade pedida
  2. unidade atual
  3. unidades do histórico que o usuário acessa
- se encontrar outra unidade válida, deve informar `candidate_unit`
- não assumir sucesso só porque a árvore mostra `linkReabrirProcesso`; a fonte de verdade é `procedimento_visualizar`

### 7. Triagem de ambiente

`environment-triage-preview`:

- `fast`: só metadados
- `contextual`: default, lê no máximo 1 documento-chave por processo
- `deep`: casos difíceis, mais lento

Selecionar processos por:

- novo
- com mudança recente
- sem marcador
- opcionalmente revisão de marcador já existente

Aplicação definitiva deve preferir pelo menos `contextual`.

### 8. Marcadores

Texto do marcador deve refletir:

- assunto do processo
- estado atual
- se exige manifestação
- prazo, se houver
- militares envolvidos, quando fizer sentido

Formato preferido: `assunto - status atual`

Exemplos:

- `Ofício externo da SEAD - responder até 05/04`
- `Férias Sd Vinicius - reaprazamento solicitado`
- `Suprimento serviços Apodi - empenho emitido`

## Armadilhas importantes

### Unidade ambígua

Se mais de uma unidade combinar com o texto informado, não escolher sozinho. Pedir definição do usuário.

### Troca de unidade

Evitar `switch` redundante. Preferir as canônicas com preflight/restore interno.

### Rascunho vs documento assinado

Documento em rascunho pode exigir unidade dona do processo. Documento assinado é mais acessível entre unidades.

### Editor

- não aplicar `html.escape()` no corpo
- preservar HTML cru
- se a seção template-lock não aceitar conteúdo, usar a seção editável seguinte

### Sessão/login

Quando o fluxo estiver correto, o SEI não deve forçar relogin. Se aparecer relogin, tratar como bug de navegação/rota, não como comportamento normal.

## Padrão de decisão do agente

Para qualquer tarefa SEI:

1. descobrir a canônica correspondente
2. usar `preview`
3. validar contexto/unidade/destino/signatário
4. pedir confirmação só se a política exigir
5. executar `confirm`
6. reler/verificar resultado

## Referências internas

- `docs/operations.md` — backlog e decisões operacionais
- `docs/plan.md` — visão mais ampla do projeto
- `skills/oda/SKILL.md` — formatação documental

