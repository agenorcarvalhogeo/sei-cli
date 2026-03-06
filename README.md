# sei-cli

CLI Python para interagir com o SEI (RN) por HTTP (sem browser).

## Instalação

```bash
pip install -e .
```

## Uso

```bash
sei login
sei status
sei processes
```

## API adicionada (cliente Python)
- `create_document()`, `get_editor_sections()`, `save_document()`, `read_document()`
- `enviar_processo()` / `tramitar_processo()`
- `list_marcadores()`, `set_marcador()`, `remove_marcador()`
- `read_relatorio()` e `batch_read_relatorios()`
