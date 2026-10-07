# ADR-005 — JSONB para Especificações Dinâmicas de Ativos

**Status:** Aceito  
**Data:** 2026-10-02  

## Contexto

Categorias distintas de ativos possuem características diferentes (Notebook: CPU, RAM; Switch: portas, PoE; Celular: IMEI, operadora). É necessário armazenar esses dados sem criar uma tabela por categoria.

## Decisão

As especificações técnicas dos ativos serão armazenadas em coluna JSONB (`technical_specs`). Cada categoria de ativo definirá um schema de validação (`spec_schema`) que descreve os campos esperados.

### Exemplo

```json
// AssetCategory.spec_schema para "Notebook"
{
  "cpu": {"type": "string", "required": true},
  "ram_gb": {"type": "integer", "required": true},
  "storage_gb": {"type": "integer", "required": true},
  "os": {"type": "string", "required": false},
  "hostname": {"type": "string", "required": false},
  "mac_address": {"type": "string", "required": false}
}

// Asset.technical_specs
{
  "cpu": "Intel Core i7-1365U",
  "ram_gb": 16,
  "storage_gb": 512,
  "os": "Windows 11 Pro",
  "hostname": "NB-FIN-042"
}
```

## Justificativa

- PostgreSQL JSONB suporta índices GIN para queries eficientes
- Evita explosão de tabelas ou padrão EAV complexo
- Categorias podem ser adicionadas sem migrações
- Validação no backend via Pydantic dinâmico

## Consequências

- Specs não possuem constraints de banco (validação é no backend)
- Queries em specs específicos requerem operadores JSONB
- Relatórios avançados por spec podem ter performance inferior a colunas nativas
