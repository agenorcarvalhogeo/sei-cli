# Changelog

## 0.6.0 — Canônicas documentais e Documento Modelo

### Destaques

- Adiciona suporte a criação de documento interno a partir de Documento Modelo do SEI.
- Endurece a edição canônica para evitar HTML escapado ou duplamente escapado ao salvar documentos.
- Melhora a escolha automática da seção real de corpo em documentos com múltiplas seções editáveis.
- Consolida as canônicas de criação/edição documental e os atalhos de fluxo usados por agentes.

### Criação por Documento Modelo

- `document-create-preview` e `document-create-confirm` agora aceitam `--documento-modelo <numero_sei>`.
- Ao informar `--documento-modelo`, a canônica força `texto_inicial=D`.
- O POST de criação preenche `txtProtocoloDocumentoTextoBase` com o número SEI informado.
- O contrato JSON passa a expor `texto_inicial` e `documento_modelo` em `payload_preview` e `created_document`.

Exemplo:

```bash
sei document-create-preview 49286513 despacho --documento-modelo 40842131 --json
sei document-create-confirm 49286513 despacho --documento-modelo 40842131 --confirm --json
```

### Edição sem escape HTML

- `save_document()` normaliza todas as seções `txaEditor_*` para HTML cru antes do POST.
- Tags estruturais escapadas, inclusive multi-escapadas como `&amp;amp;lt;p`, são desescapadas antes do envio.
- O fluxo preserva as seções não editadas, mas evita repostar conteúdo estrutural escapado.
- Caracteres fora de ISO-8859-1 continuam sendo convertidos para entidades numéricas para compatibilidade com o editor legado do SEI.
- `document-edit-confirm` retorna sinais de validação em `save_validation`.

### Seção correta de corpo

- `document-edit-preview` evita selecionar cabeçalho, timbre, metadados e rodapé como seção de corpo.
- A heurística foi validada em documentos multi-seção, incluindo Encaminhamento e Justificativa.
- Matriz real validada no processo de teste `08810254.000138/2026-88` / `49286513`:

| Tipo | Seção de corpo validada |
| --- | --- |
| Encaminhamento | `1062` |
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

### Canônicas e CLI

- O catálogo de workflows passa a tratar `criar_processo`, `criar_documento`, `despachar` e `encaminhar` como fluxos canônicos suportados.
- O CLI aceita `--text` como alias de `--texto` nos pontos de edição aplicáveis.
- A skill OpenClaw foi atualizada com a regra de Documento Modelo e com a regra de salvar HTML cru no editor.

### Validação

- Suíte local: `pytest tests/ -q`.
- Checagem de diff: `git diff --check`.
- Validação real no SEI, unidade `CMDO PABM APODI`, usuário `LEO ZENON TASSI`.
- Validação independente do Lago no Slack:
  - fontes lidas com sucesso: `40851082`, `40842124`, `40842131`
  - cópias por Documento Modelo lidas com sucesso: `40851470`, `40851104`, `40851127`
  - nenhum documento mostrou HTML escapado literal como `&lt;p&gt;`, `&amp;lt;p`, `&lt;strong&gt;` ou `&lt;table`
  - os pares de conteúdo foram equivalentes por leitura textual:
    - `40851082` -> `40851470`
    - `40842124` -> `40851104`
    - `40842131` -> `40851127`

### Observações

- A prova independente confirmou a camada textual extraída pelo SEI; não houve prova visual por browser/CDP nessa sessão.
- Justificativa expõe uma tabela de referência em `875`; a seção de corpo real validada é `873`.
- `1062` é o corpo do Encaminhamento testado, não um padrão global para todos os tipos.
