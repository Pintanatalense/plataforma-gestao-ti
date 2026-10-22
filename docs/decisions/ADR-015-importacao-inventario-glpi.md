# ADR-015 — Importação de inventário do GLPI Agent (XML)

**Status:** Implementado em parte (PR de origem em `a57c8f4`, endurecido no PR #11)  
**Data:** 2026-10-21  

## Contexto

O inventário de máquinas já é coletado pelo GLPI Agent / FusionInventory, que gera um XML por equipamento. Digitar CPU, memória, disco e sistema à mão é lento e propenso a erro. O desenho original está em [`docs/plans/importacao-inventario-glpi.md`](../plans/importacao-inventario-glpi.md).

## Decisão (o que existe no código)

Um assistente de 3 passos em **Patrimônio & Ativos → Importar Inventário (GLPI)** (`/assets/import-glpi`, permissão `assets.write`):

1. **Envio** de um ou mais `.xml` (até 20 arquivos de 5 MB; nomes não podem repetir).
2. **Prévia** (`POST /assets/glpi-import/analyze`): cada arquivo é *Novo* (série ainda não cadastrada), *Já cadastrado* (série igual à de um ativo) ou *Erro*.
3. **Execução** (`POST /assets/glpi-import/execute`): por arquivo, *criar*, *atualizar* ou *ignorar*; um erro numa linha não derruba as demais.

Regras:
- **Chave de casamento:** `assets.serial_number` (único, indexado; migration `p6f7a8b9c0d1`). Série placeholder do BIOS cai para o número de série da placa-mãe.
- **Criação:** reaproveita `AssetService.create_asset` (valida patrimônio único e gera a movimentação `INITIAL_STOCK`); status `IN_STOCK`, sem colaborador; nome sugerido vem do modelo do equipamento, não do hostname.
- **Atualização:** só mescla as especificações técnicas informadas pelo GLPI em `technical_specs` (CPU, memória, armazenamento, SO, MAC, hostname), preservando o que foi cadastrado à mão; não gera movimentação.
- **Série em conflito** (ativo inativo, outro ativo, repetida no lote) é erro da linha, nunca erro 500 (PR #11).
- **Dados sensíveis não são gravados:** chave do Windows, licenças, variáveis de ambiente, usuários/grupos locais e lista de softwares.
- O XML real de exemplo (`docs/INVENTARIO_MODELO.xml`) contém dados sensíveis e fica **fora do Git** (`.gitignore`).

## Divergências em relação ao plano original

| Previsto no plano | Situação |
|---|---|
| Casamento em cascata série → hostname/tag → UUID | **Não implementado** (só série) |
| Colunas `inventory_data` e `last_inventory_at`; cartão “Inventário GLPI” no detalhe do ativo | **Não implementado** |
| Integração com auditoria de inventário (marcar itens `FOUND`) e botão na tela de Inventário Periódico | **Não implementado** (o assistente fica em Ativos) |
| Parser com `defusedxml` | **Não adotado**: usa `xml.etree` (stdlib); upload exige `assets.write` e o expat atual limita expansão de entidades. Reavaliar se a importação for aberta a mais perfis |
| Seção no guia do usuário | Pendente; o roteiro de testes ganhou a Etapa 4b |

Estas pendências só devem ser retomadas por decisão explícita.

## Consequências

- Importar de novo o mesmo XML é seguro (aparece como já cadastrado).
- Dois equipamentos com a mesma série real (ex.: série genérica de fabricante) exigem tratamento manual.
- O índice único vale também para ativos inativos: reativar ou resolver o cadastro antes de importar.
