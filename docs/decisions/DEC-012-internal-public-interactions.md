# DEC-012: Separação de Interações Públicas e Internas no Service Desk

## Contexto e Problema
Dentro das operações de suporte de TI (Service Desk), os técnicos costumam se deparar com a necessidade de registrar informações altamente técnicas e sensíveis durante a investigação de um incidente (ex: trechos de logs contendo IPs, credenciais provisórias ou debates internos sobre quem causou o problema).

Se o sistema utilizar um único fluxo linear de mensagens, o colaborador (solicitante final) seria bombardeado com jargões ou dados confidenciais cada vez que a TI registrasse uma atualização. Nós precisamos de um mecanismo no MOD-04 que impeça o vazamento dessas informações enquanto mantém a integridade do histórico do chamado para auditoria.

## Decisão
Decidimos adicionar o conceito estrito de **Visibilidade da Interação**.

1. O modelo `TicketInteraction` (Interação de Chamado) conterá uma flag booleana obrigatória: `is_internal` (padrão: `False`).
2. **API do Colaborador (Pública):** As rotas de leitura consumidas por colaboradores padrão deverão filtrar obrigatoriamente a query: `.where(TicketInteraction.is_internal == False)`. As interações internas jamais deixarão o backend na visão do solicitante.
3. **API Técnica (Interna):** Usuários com a permissão (ex: `service_desk.tickets.read_internal`) receberão todas as interações. O frontend técnico renderizará as interações internas com um design visual distinto (ex: um fundo amarelado/destacado com um ícone de cadeado) para ficar óbvio para o técnico de que se trata de uma nota privada.
4. **Notificações:** O serviço de envio de notificações por email/push (MOD-11 futuro) deve ignorar qualquer interação criada com `is_internal = True` para evitar disparos aos solicitantes finais.

## Consequências
- **Positivas:**
  - Melhora a segurança da informação, mantendo dados críticos confidenciais à equipe técnica.
  - Oferece uma comunicação mais limpa e focada na solução (para o colaborador).
  - Preserva todo o processo investigativo documentado na base para treinamento ou auditoria de SLAs.
- **Negativas:**
  - Aumenta levemente a complexidade das consultas de repositório e regras de autorização no backend.
  - Exige clareza de UX no frontend dos técnicos para que não marquem acidentalmente uma resposta ao cliente como nota interna (ou pior, vice-versa).
