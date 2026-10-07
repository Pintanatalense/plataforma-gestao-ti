# Visão Geral do Sistema

## Propósito

Plataforma modular para gestão operacional do setor de TI, abrangendo:

- **Service Desk** — abertura, triagem e resolução de chamados
- **Gestão de Ativos** — controle patrimonial de equipamentos
- **Movimentações** — rastreabilidade de entregas, devoluções e transferências
- **Estoque** — controle de insumos por unidade
- **Inventário** — conferências periódicas
- **Contas e Acessos** — registro de sistemas e contas por colaborador
- **Notificações** — alertas em tempo real
- **Auditoria** — registro transversal de ações críticas

## Princípios Arquiteturais

### Monólito Modular

O sistema é um monólito com fronteiras internas rígidas entre módulos. Cada módulo:

1. Possui sua própria documentação
2. Expõe interface pública via `services.py` e `schemas.py`
3. Não acessa diretamente models ou repositórios de outros módulos
4. Emite eventos via barramento interno para comunicação desacoplada

### Contexto Reduzido para IA

A modularização permite que agentes de IA recebam apenas o contexto necessário:

```
contexto global mínimo + documentação do módulo + interfaces das dependências + tarefa
```

### Histórico Permanente

Alterações relevantes preservam histórico e autoria (DEC-004). Exclusão lógica é preferida sobre exclusão física.

## Módulos

| Código | Módulo | Responsabilidade |
|--------|--------|-----------------|
| MOD-01 | Core | Infraestrutura compartilhada |
| MOD-02 | Organização | Empresa, unidades, setores, colaboradores |
| MOD-03 | Identidade | Autenticação, perfis, permissões |
| MOD-04 | Service Desk | Chamados e interações |
| MOD-05 | Ativos | Equipamentos patrimoniais |
| MOD-06 | Movimentações | Ciclo de vida dos ativos |
| MOD-07 | Estoque | Insumos sem patrimônio |
| MOD-08 | Inventário | Conferências periódicas |
| MOD-09 | Contas/Acessos | Sistemas e contas dos colaboradores |
| MOD-10 | Anexos | Armazenamento de arquivos |
| MOD-11 | Notificações | Alertas em tempo real |
| MOD-12 | Auditoria | Registro de ações críticas |

## Perfis de Usuário

| Perfil | Descrição |
|--------|----------|
| COLABORADOR | Abre e acompanha seus chamados |
| GESTOR | Visualiza chamados da equipe |
| TÉCNICO_TI | Gerencia chamados, ativos e estoque |
| ADMINISTRADOR | Acesso completo ao sistema |

## Decisões Consolidadas

Consultar `/docs/decisions/` para ADRs completos.

| # | Decisão |
|---|---------|
| DEC-001 | Uma instalação = uma empresa |
| DEC-002 | Suporte a matriz + N filiais |
| DEC-003 | Autenticação própria (sem AD/LDAP no MVP) |
| DEC-004 | Histórico permanente com autoria |
| DEC-005 | Ativo como entidade central |
| DEC-006 | Chamado associado ao ativo |
| DEC-007 | Arquivos fora do banco |
| DEC-008 | Sem senhas corporativas |
| DEC-009 | Estoque sem compras |
| DEC-010 | Sem módulo financeiro |
| DEC-011 | Notificação local no MVP |
| DEC-012 | Interações públicas e internas |
| DEC-013 | Sistema modular |

## Escopo Fora do MVP

- E-mail e WhatsApp
- Integração com AD/LDAP
- Módulo financeiro
- App mobile
- Expansão para outros departamentos
