# Org Workflows

Fluxos de processos específicos de cada organização.

Cada organização tem um diretório com arquivos YAML declarativos que mapeiam as etapas de processos comuns.

## Estrutura

```
workflows/
  cbmrn/
    reaprazamento.yaml     # Reaprazamento de férias
    sindicancia.yaml       # Fluxo de sindicância
    suprimento.yaml        # Suprimento de fundos
  ibama/
    licenciamento.yaml     # Licenciamento ambiental
```

## Formato

```yaml
nome: Nome do Fluxo
orgao: cbmrn
descricao: Breve descrição do fluxo

etapas:
  - ator: solicitante
    acao: criar_processo
    tipo: "Tipo de Documento SEI"
    destino: proximo_ator
    
  - ator: proximo_ator
    acao: despachar
    decisao: [aprovar, indeferir]
    destino_aprovado: secretaria
    destino_indeferido: solicitante
    
  - ator: secretaria
    acao: acostar_autos
    destino: bg
```

## Como Usar

Esses workflows são carregados pelo CLI quando o usuário configura seu `orgao` no profile. O agente de IA pode usar esses fluxos para guiar operações complexas passo a passo.

## Contribuindo

1. Abra uma Issue descrevendo o fluxo do seu órgão
2. Mapeie as etapas: quem faz o quê, pra onde vai, quais decisões
3. O maintainer cria o YAML e valida com a equipe
