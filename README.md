# sei-cli

CLI Python para interagir com o SEI (RN) por HTTP puro (httpx, sem browser).

> **🤝 Colaboradores:** Push direto na `main` está bloqueado. Leia o [CONTRIBUTING.md](CONTRIBUTING.md) antes de começar. Bugs e sugestões → **Issue primeiro**, fix via **branch + PR**.

## Instalação

```bash
pip install -e .
```

## Comandos CLI

### Autenticação & Status
```bash
sei login                          # Login e mostra status
sei status                         # Status da sessão atual
sei switch "CFAP - DA"             # Trocar unidade ativa
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

### Tramitação / Encaminhamento
```bash
sei encaminhar <id_proc> "DPSGP SECRETARIA"                        # Enviar para 1 unidade
sei encaminhar <id_proc> "CMDO 4CIA/4BBM" "SEC 4CIA/4BBM"          # Enviar para múltiplas
sei encaminhar <id_proc> "COBM SECRETARIA" --fechar                # Enviar e fechar na unidade atual
sei encaminhar 08810254.000108/2026-71 "CMDO 3GBM"                 # Aceita número do processo
```

> **Nota:** Por padrão, o processo é mantido aberto na unidade atual.
> Use `--fechar` para fechá-lo após o envio.

### Assinatura
```bash
sei assinar <id_doc> <id_proc>     # Assinar documento
sei assinar-lote <id_proc> <id1> <id2> ...  # Assinar múltiplos docs
sei dar-ciencia <id_doc> <id_proc> # Dar ciência em documento
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
    
    # Encaminhar (1 ou múltiplas unidades, manter aberto por padrão)
    c.enviar_processo("48218772", "CMDO 3GBM")
    c.enviar_processo("48218772", ["CMDO 4CIA/4BBM", "SEC 4CIA/4BBM"], manter_aberto=True)
    
    # Assinar documentos
    c.assinar_documento("48568466", "48568435")
    
    # Dar ciência
    c.dar_ciencia("48568466", "48568435")
    
    # Marcadores
    c.set_marcador("48218772", "123", "texto opcional")
    c.remove_marcador("48218772")
    
    # Relatórios
    rel = c.read_relatorio("48218774", "48218772")
```

## Credenciais & Segurança

### Opção 1: Variáveis de Ambiente (rápido pra testar)
```bash
export SEI_USUARIO="seu_usuario"
export SEI_SENHA="sua_senha"
export SEI_ORGAO="CBM"
export SEI_LOGIN_URL="https://sei.rn.gov.br/sip/login.php"
```

### Opção 2: Arquivo de Configuração (razoável)
```bash
mkdir -p ~/.config/sei
cat > ~/.config/sei/credentials.json << 'EOF'
{
  "usuario": "seu_usuario",
  "senha": "sua_senha",
  "orgao": "CBM",
  "login_url": "https://sei.rn.gov.br/sip/login.php"
}
EOF
chmod 600 ~/.config/sei/credentials.json
```

### Opção 3: Bitwarden (recomendado) 🔒

As opções acima funcionam pra um primeiro teste, mas credenciais em texto plano são frágeis — ficam no histórico do shell, em backups, expostas a qualquer processo que leia o filesystem.

A abordagem recomendada é usar o [Bitwarden CLI](https://bitwarden.com/help/cli/) como gerenciador de segredos:

```bash
# Instalar e logar
npm install -g @bitwarden/cli
bw login

# Criar um item no vault com suas credenciais SEI
bw create item '{
  "name": "SEI",
  "login": { "username": "seu_usuario", "password": "sua_senha" },
  "notes": "SEI_ORGAO=CBM\nSEI_LOGIN_URL=https://sei.rn.gov.br/sip/login.php"
}'

# Exportar para variáveis de ambiente no início da sessão
export BW_SESSION=$(bw unlock --raw)
export SEI_USUARIO=$(bw get username "SEI")
export SEI_SENHA=$(bw get password "SEI")
export SEI_ORGAO="CBM"
export SEI_LOGIN_URL="https://sei.rn.gov.br/sip/login.php"
```

**Vantagens:**
- Credenciais encriptadas no vault, não no disco
- Funciona em múltiplas máquinas via sync
- Rotação de senha = atualizar num lugar só
- Se usar com agente de IA (Claude Code, etc.), o agente acessa via CLI sem ver a senha em texto

> É assim que o maintainer do projeto gerencia credenciais. Nenhuma senha toca o filesystem em texto plano.

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
