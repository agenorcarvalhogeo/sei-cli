# Correções e Problemas Conhecidos

## Fix: `sei processes` falha após `sei login` (sessão restaurada)

**Data:** 2026-03-25
**Arquivo:** `sei_cli/client.py` — método `_try_inicializar`

### Problema

Ao executar `sei login` seguido de `sei processes` em processos separados (o caso normal de uso via CLI), o comando `processes` lançava:

```
RuntimeError: Página de controle de processos não encontrada (tabelas ausentes).
Verifique se a sessão está ativa e na unidade correta.
```

### Causa raiz

O método `_try_inicializar` faz GET em `inicializar.php` e espera ser redirecionado para a página de controle de processos (`acao=procedimento_controlar`), que contém as tabelas `tblProcessosRecebidos` e `tblProcessosGerados`.

Porém, quando a sessão é restaurada de disco (cookie salvo pelo `sei login`), o `inicializar.php` redireciona para `acao=principal` — o **frameset principal** do SEI — que contém o texto "Controle de Processos" no título, mas **não** as tabelas de processos (essas são carregadas em um iframe separado).

O check original era:
```python
if r2.status_code == 200 and "Controle de Processos" in r2.text:
    return r2.text  # ERRADO: retorna o frameset, sem tabelas
```

### Correção

Após confirmar que estamos no frameset (`acao=principal` na URL ou ausência de `tblProcessosRecebidos`), navegamos explicitamente para `acao=procedimento_controlar` com o `infra_unidade_atual` correto:

```python
if "acao=principal" in str(r2.url) or "tblProcessosRecebidos" not in r2.text:
    unit_id = self._current_unit_id or ""
    ctrl_url = self._sei_url(
        "controlador.php?acao=procedimento_controlar&infra_sistema=100000100"
        + (f"&infra_unidade_atual={unit_id}" if unit_id else "")
    )
    r3 = self.client.get(ctrl_url)
    if r3.status_code == 200 and "tblProcessosRecebidos" in r3.text:
        return r3.text
    return None
```

### Observação

O comportamento do `inicializar.php` parece variar conforme o estado da sessão no servidor:
- **Login fresco** (sem cookie salvo): redireciona direto para `acao=procedimento_controlar`
- **Sessão restaurada** (cookie de disco): redireciona para `acao=principal`

A correção lida com ambos os casos.

---

## Observação: `_current_unit_id` não persiste entre processos

**Data:** 2026-03-25

Após o `sei login`, o `_current_unit_id` fica `None` no `session.json` (`unit_id: null`), pois a persitência só salva o `unit_id` depois de um `switch_unit` explícito.

Na correção acima, o `ctrl_url` sem `infra_unidade_atual` ainda funciona porque o SEI usa a unidade padrão do usuário autenticado. Porém, para usuários com múltiplas unidades, seria ideal persistir o `unit_id` logo após o login.
