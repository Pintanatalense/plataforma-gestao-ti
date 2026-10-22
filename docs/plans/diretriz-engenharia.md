# Diretriz de Engenharia — Profissionalização e Evolução da Plataforma de Gestão de TI

> Requisitos do responsável do projeto (2026-10-21). O plano de execução está em [plano-diretor.md](plano-diretor.md).

1. Objetivo geral
Com base na análise técnica realizada e nos problemas identificados, quero iniciar uma etapa estruturada de profissionalização, estabilização e evolução da Plataforma de Gestão de TI.
O objetivo não é apenas corrigir os defeitos existentes, mas estabelecer uma base de engenharia de software que garanta segurança, confiabilidade, manutenibilidade, testabilidade, observabilidade, escalabilidade e organização do repositório.
Quero que o projeto evolua seguindo práticas profissionais de desenvolvimento, com decisões arquiteturais justificadas, documentação atualizada, testes automatizados e entregas incrementais.
Não quero soluções paliativas, implementações improvisadas, funcionalidades incompletas apresentadas como concluídas ou aumento desnecessário da complexidade tecnológica.
Toda decisão relevante deverá considerar o impacto no sistema existente e ser fundamentada tecnicamente.
2. Auditoria técnica e definição da stack oficial
Antes de iniciar novas funcionalidades, realize um levantamento da arquitetura e das tecnologias efetivamente utilizadas.
Analise:
Frontend, backend e banco de dados.
Frameworks, bibliotecas e suas versões.
Gerenciamento de dependências e arquivos de lock.
Autenticação, autorização e gerenciamento de sessões.
Estrutura de diretórios e organização dos módulos.
Migrations e consistência dos models.
Containers, Dockerfiles e infraestrutura.
Pipeline de CI/CD e execução de testes.
Configuração, variáveis de ambiente e gerenciamento de segredos.
Logs, monitoramento e tratamento de exceções.
Documentação técnica e operacional.
A partir desse levantamento, defina e documente a stack oficial do projeto, distinguindo tecnologias consolidadas, dependências transitórias e componentes que devem ser substituídos ou removidos.
Crie registros de decisões arquiteturais (ADRs) para escolhas significativas.
Priorize a consolidação da stack existente quando ela atender adequadamente aos requisitos. Não introduza novas tecnologias apenas por preferência pessoal ou tendência de mercado.
As decisões devem considerar manutenção, segurança, compatibilidade, custos operacionais, desempenho, disponibilidade e facilidade de implantação.
3. Estabilização e mitigação dos defeitos existentes
Utilize a análise anterior como ponto de partida e execute uma nova verificação do repositório para identificar outros problemas.
Considere o PR #11 (fix/review-glpi-import-e-estoque-categorias) e seu estado atual. Verifique os checks de CI antes de recomendar integração, não duplique correções já implementadas e não realize merge sem autorização.
Priorize:
Vulnerabilidades de segurança, riscos de perda de dados e problemas de integridade.
Falhas críticas de autenticação, autorização e regras de negócio.
Inconsistências entre models, migrations e banco de dados.
Erros que comprometem operações do usuário, especialmente falhas silenciosas de carregamento.
Problemas de infraestrutura, dependências, containers e pipeline.
Funcionalidades existentes, porém incompletas ou inacessíveis.
Lacunas de testes, estados de interface e documentação.
Melhorias de organização, desempenho e experiência de uso.
Implemente tratamento consistente de carregamento, erro, estado vazio e tentativa de recuperação nas páginas aplicáveis.
Uma falha de comunicação com o backend nunca deve ser apresentada ao usuário como uma lista vazia de resultados.
Revise também as funcionalidades identificadas como ausentes, incluindo perfil institucional/logo, auditoria e relatórios de chamados, verificando primeiro quais contratos e capacidades já existem no backend.
Quero que o inventário das páginas seja atualizado com critérios objetivos de conclusão, evidências de testes e pendências reais. Aumentar o percentual de conclusão não deve ser o objetivo isolado; o foco é entregar funcionalidades corretas e utilizáveis.
4. Implementação do módulo de SLA
Quero introduzir um módulo de Service Level Agreement (SLA) configurável, integrado ao gerenciamento de chamados e vinculado às categorias.
4.1. Regra inicial obrigatória
Toda categoria de chamado deverá possuir a possibilidade de associação a uma política de SLA.
O comportamento padrão será:
SLA: Não se aplica
Isso significa que categorias sem política configurada não terão cobrança automática de prazos de SLA.
O sistema não deve criar prazos artificiais nem considerar chamados sem SLA como atrasados.
À medida que o catálogo de categorias for desenvolvido, poderemos associar políticas específicas a cada uma.
4.2. Administração das políticas
Projete uma interface administrativa que permita cadastrar, editar, consultar, ativar, desativar e associar políticas de SLA às categorias.
Avalie a necessidade dos seguintes parâmetros:
Nome, descrição e situação da política.
Tempo para primeira resposta.
Tempo para resolução.
Calendário de atendimento e horário comercial.
Dias úteis, finais de semana e feriados.
Regras de suspensão e retomada da contagem.
Comportamento durante reabertura de chamados.
Associação com categoria e, quando justificável, prioridade.
Alertas de proximidade de vencimento.
Registro e histórico de violações.
Defina explicitamente a diferença entre primeira resposta, atendimento e resolução, evitando interpretações ambíguas.
4.3. Regras de negócio e arquitetura
Antes de implementar, apresente uma proposta técnica para o mecanismo de cálculo de SLA.
O planejamento deve resolver:
Quando a contagem começa e termina.
Quais situações pausam a contagem.
Como são tratados chamados reabertos.
O que acontece quando uma categoria ou sua política é alterada.
Como preservar o histórico de prazos já aplicados.
Como evitar recálculos incorretos e problemas de fuso horário.
Como garantir consistência em processamento concorrente.
Como representar corretamente a ausência de SLA.
Avalie se o mecanismo precisa de processamento assíncrono, tarefas agendadas ou se pode ser implementado de maneira mais simples.
Não introduza filas, serviços adicionais ou microsserviços sem demonstrar necessidade concreta.
Inclua testes de regras de negócio, limites de horário, suspensão, vencimento, reabertura e ausência de política.
Planeje indicadores de cumprimento de SLA e sua futura utilização em dashboards e relatórios.
5. Configuração de recuperação de senha por e-mail
Quero preparar a plataforma para permitir a recuperação de senha por e-mail corporativo.
Entretanto, o servidor de e-mail da empresa ainda será configurado.
Por isso, a solução deve ser implementada de forma configurável e inicialmente desabilitada, podendo ser ativada posteriormente por configuração administrativa ou operacional apropriada.
Requisitos
Suporte à configuração de SMTP ou outro provedor de envio tecnicamente justificado.
Configurações externas ao código-fonte.
Armazenamento seguro das credenciais.
Suporte a conexão criptografada e validação de certificados.
Verificação controlada da configuração de envio.
Fluxo de solicitação de recuperação de senha.
Token criptograficamente seguro, temporário e de uso único.
Invalidação do token após utilização.
Proteção contra enumeração de contas e abuso de solicitações.
Registro auditável dos eventos relevantes, sem exposição de senhas ou tokens.
Tratamento apropriado para indisponibilidade do serviço de e-mail.
Testes automatizados utilizando serviços simulados, sem dependência do SMTP corporativo real.
O mecanismo deve permanecer desabilitado enquanto a infraestrutura de envio não estiver homologada.
Não envie credenciais, tokens ou informações sensíveis para logs ou repositórios.
Avalie também as implicações de segurança relacionadas a sessões ativas após uma alteração de senha.
6. Organização e governança do repositório
Revise a estrutura do repositório e estabeleça padrões formais de desenvolvimento.
Inclua:
Organização coerente dos módulos, componentes, serviços e testes.
Convenções de nomes e formatação.
Ferramentas de linting, análise estática e verificação de tipos, conforme a stack.
Padrão de branches, commits e pull requests.
Política de revisão de código e proteção da branch principal.
CI executando os testes e verificações de qualidade.
Migrations versionadas e verificadas.
Dependências controladas e imagens Docker com versões fixadas.
Arquivos .env.example sem credenciais reais.
Documentação de instalação, configuração, desenvolvimento, testes e deploy.
Registros de decisões arquiteturais e documentação das regras de negócio.
Procedimentos de backup, restauração e recuperação de falhas.
Avalie o .gitignore e o diretório docs/plans/ existentes localmente antes de decidir sua incorporação ao repositório. Preserve o conteúdo pertinente e não inclua arquivos pessoais, temporários ou sensíveis.
Aplique princípios como SOLID, DRY, KISS, separação de responsabilidades e baixo acoplamento quando forem úteis à solução, sem transformar padrões arquiteturais em complexidade desnecessária.
7. Planejamento obrigatório para tarefas complexas
Quero que você adote um processo em que funcionalidades complexas sejam planejadas tecnicamente antes da implementação.
Para cada mudança significativa, apresente:
Problema e impacto identificado.
Objetivo e critérios de aceite.
Arquitetura proposta e componentes afetados.
Alternativas consideradas e justificativa da escolha.
Alterações previstas em API, banco de dados e frontend.
Regras de negócio e casos de borda.
Implicações de segurança e desempenho.
Estratégia de testes e validação.
Riscos, dependências e possibilidade de rollback.
Divisão da implementação em etapas verificáveis.
Identifique quais decisões precisam de aprovação antes de qualquer implementação irreversível ou mudança significativa de arquitetura.
Alterações pequenas, localizadas e de baixo risco podem seguir um fluxo mais simples, desde que sejam testadas.
8. Estratégia de execução e priorização
Não execute todas as mudanças simultaneamente.
Elabore um roadmap técnico organizado por prioridade, dependência e risco.
A sequência inicial deve seguir esta orientação:
Fase 1 — Diagnóstico e governança: auditoria do estado real do projeto, validação do PR existente, definição da stack oficial e identificação dos riscos.
Fase 2 — Estabilização: correção dos problemas críticos, integridade de dados, segurança, migrations, infraestrutura e falhas de funcionamento.
Fase 3 — Qualidade funcional: tratamento de erros, indicadores de carregamento, estados vazios, testes e recuperação das funcionalidades incompletas.
Fase 4 — Novas capacidades: planejamento e implementação do mecanismo de SLA e do fluxo configurável de recuperação de senha.
Fase 5 — Consolidação: documentação operacional, observabilidade, indicadores de qualidade, homologação e preparação para implantação.
Essa ordem pode ser ajustada quando as dependências técnicas justificarem, mas qualquer alteração significativa de prioridade deve ser explicada.
Separe as entregas em PRs pequenos e coesos, evitando misturar refatorações extensas, mudanças de banco de dados e funcionalidades independentes na mesma revisão.
9. Critérios de qualidade e aceite
Uma atividade não deverá ser considerada concluída apenas porque o código compila ou a interface aparece na tela.
Exijo, conforme a natureza da mudança:
Código revisável, legível e compatível com a arquitetura aprovada.
Testes automatizados apropriados, incluindo cenários de falha.
Build e verificações de CI aprovados.
Integração validada entre frontend, backend e banco de dados.
Autorização e validação de entradas verificadas.
Migrations testadas, com avaliação de compatibilidade e recuperação.
Ausência de regressões conhecidas nos fluxos afetados.
Mensagens de erro compreensíveis e estados de interface consistentes.
Documentação atualizada.
Evidência objetiva da validação realizada.
Preserve os testes existentes e use o resultado atual como linha de base, investigando qualquer regressão.
Não considere a correspondência entre URLs de frontend e backend como prova suficiente de integração: contratos, payloads, respostas, permissões e cenários de erro também devem ser validados.
Não declare uma funcionalidade como integralmente concluída quando existirem limitações relevantes não documentadas.
10. Entregáveis esperados
Antes de iniciar as implementações de maior complexidade, apresente:
A. Diagnóstico técnico: arquitetura atual, tecnologias realmente utilizadas, defeitos confirmados, dívidas técnicas e riscos.
B. Stack oficial: tecnologias e versões adotadas, responsabilidades de cada componente e justificativa das decisões, documentadas em ADRs quando necessário.
C. Roadmap priorizado: atividades organizadas da maior criticidade para a menor, com dependências, esforço estimado e critérios de conclusão.
D. Proposta de SLA: modelo de dados, regras de cálculo, integração com categorias, interface administrativa e estratégia de testes.
E. Proposta de recuperação de senha: arquitetura de configuração do serviço de e-mail, segurança do fluxo e estratégia de ativação futura.
F. Plano de governança: organização do repositório, convenções, testes, CI/CD, documentação e padrões de revisão.
G. Plano de execução: divisão em issues, branches e PRs independentes, com entregas incrementais e validações demonstráveis.
Ao final de cada PR, apresente um resumo das alterações, testes executados, resultados, limitações, riscos residuais e próximos passos.
11. Diretriz final
Quero evoluir este projeto para uma plataforma corporativa de gestão de TI, preparada para manutenção contínua, implantação segura e crescimento funcional.
Priorize a confiabilidade sobre a velocidade, a simplicidade sobre a complexidade desnecessária e a consistência arquitetural sobre soluções isoladas.
Não quero apenas que as funcionalidades funcionem no ambiente de desenvolvimento. Quero que sejam verificáveis, seguras, documentadas e sustentáveis em produção.
Comece pelo diagnóstico técnico e pelo roadmap de execução. Planeje formalmente os componentes mais complexos antes de implementá-los e avance de maneira incremental, da maior criticidade para a menor, demonstrando evidências de qualidade a cada entrega.
Não realize merges, alterações irreversíveis ou mudanças arquiteturais significativas sem aprovação prévia.