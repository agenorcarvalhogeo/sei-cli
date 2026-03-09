# sei-cli

CLI Python para interagir com o SEI (RN) por HTTP puro (httpx, sem browser).

## Instalação

```bash
pip install -e .
```

## Comandos CLI

### Autenticação & Status
```bash
sei login                          # Login e mostra status
sei status                         # Status da sessão atual
sei switch "CMDO PABM APODI"      # Trocar unidade ativa
sei units                          # Listar unidades disponíveis
```

### Processos
```bash
sei processes                      # Listar processos na unidade
sei search "diárias"               # Pesquisar processos
sei docs <id_procedimento>         # Listar documentos de um processo
sei read-doc <id_doc> <id_proc>    # Ler conteúdo de um documento
```

### Documentos
```bash
sei create-doc <id_proc> <tipo>    # Criar documento em processo
sei save-doc <id_doc> <id_proc>    # Salvar conteúdo de documento
```

### Blocos de Assinatura
```bash
sei blocks                         # Listar blocos de assinatura
sei block <id_bloco>               # Ver documentos de um bloco

# Operações de bloco
sei block-add <id_proc> <id_doc> <bloco>              # Incluir doc em bloco
sei block-add <id_proc> <id_doc> <bloco> --disponibilizar  # Incluir + disponibilizar
sei block-disponibilizar <bloco>                       # Disponibilizar bloco
sei block-cancelar <bloco>                             # Cancelar disponibilização
sei block-remove <id_doc> <bloco>                      # Retirar doc do bloco
sei block-devolver <bloco>                             # Devolver bloco recebido
```

### Tramitação
```bash
sei tramitar <id_proc> <unidade>   # Tramitar processo para unidade
```

### Marcadores
```bash
sei marcadores                     # Listar marcadores disponíveis
```

### Relatórios Operacionais
```bash
sei read-relatorio <id_doc> <id_proc>           # Parsear relatório operacional
sei read-relatorio <id_doc> <id_proc> --summary  # Resumo legível
```

## API Python

```python
from sei_cli.client import SEIClient

with SEIClient() as c:
    c.login()
    c.switch_unit("CMDO PABM APODI")
    
    # Processos
    procs = c.list_processes()
    docs = c.get_process_documents("48218772")
    
    # Documentos
    c.create_document("48218772", "100000506", especificacao="Diárias")
    sections = c.get_editor_sections("48218774", "48218772")
    c.save_document("48218774", "48218772", sections)
    text = c.read_document("48218774", "48218772")
    
    # Blocos de assinatura
    blocks = c.list_blocks()
    c.add_document_to_block("48218772", "48218774", "871299")
    c.add_document_to_block("48218772", "48218774", "871299", disponibilizar=True)
    c.disponibilizar_block("871299")
    c.cancelar_disponibilizacao_block("871299")
    c.remove_document_from_block("48218774", "871303")
    c.devolver_block("869251")
    
    # Tramitação
    c.tramitar_processo("48218772", "CMDO 3ºGBM")
    
    # Marcadores
    c.set_marcador("48218772", "123", "texto opcional")
    c.remove_marcador("48218772")
    
    # Relatórios
    rel = c.read_relatorio("48218774", "48218772")
```

## Regras Importantes

### Blocos Disponibilizados
Documentos em blocos **disponibilizados** não podem ser editados ou assinados.
Fluxo correto:
1. `block-cancelar <bloco>` — cancelar disponibilização
2. Editar/assinar o documento
3. `block-disponibilizar <bloco>` — re-disponibilizar

### Hash de Segurança (infra_hash)
O SEI gera `infra_hash` server-side para cada URL. URLs com hash inválido são
rejeitadas silenciosamente. O cli navega pela cadeia de páginas para obter
hashes válidos automaticamente.

### Estados de Bloco
```
Gerado → Disponibilizado → Recebido → Retornado/Concluído
```
- **Gerado**: criado, ainda não enviado
- **Disponibilizado**: enviado para unidade destino
- **Recebido**: chegou na unidade destino
- **Retornado**: devolvido pela unidade destino
- **Concluído**: finalizado

## Arquitetura

- **`sei_cli/client.py`** — Client HTTP (httpx) com todas as operações
- **`sei_cli/cli.py`** — Interface CLI (click)
- **`sei_cli/auth.py`** — Gerenciamento de credenciais (Bitwarden)
- **`sei_cli/models.py`** — Dataclasses (Process, Document, Block, etc.)
- **`sei_cli/parsers.py`** — Parsers HTML (BeautifulSoup)
- **`sei_cli/config.py`** — Configuração (URLs, timeouts)

## Dependências

- httpx (HTTP client)
- beautifulsoup4 + lxml (HTML parsing)
- click (CLI)
- rich (tabelas formatadas)
