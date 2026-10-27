"""
Catálogo único de permissões (Plano de Evolução, Fase 0 PR 5; S5/A2).

Fonte da verdade de código, módulo, rótulo em português, descrição e risco de cada permissão. O seed sincroniza a
tabela ``permissions`` com este catálogo a cada inicialização; nenhum outro lugar declara permissões.

Permissão **crítica**: só vale por concessão explícita e individual (``user_critical_grants``), nunca por perfil e
nunca pelo simples ``is_admin``. Quem concede precisa de ``identity.critical.grant``. A concessão inicial é feita no
assistente de instalação; a recuperação, pelo comando ``python -m app.cli grant-critical`` no servidor.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

RISK_LABELS = {
    "leitura": "Leitura",
    "alteracao": "Alteração",
    "aprovacao": "Aprovação",
    "execucao": "Execução",
    "administracao": "Administração",
}

MODULE_LABELS = {
    "organization": "Organização",
    "identity": "Usuários e perfis",
    "assets": "Patrimônio e ativos",
    "stock": "Estoque",
    "inventory": "Inventário",
    "audit": "Auditoria",
    "service_desk": "Chamados",
    "system": "Sistema, dados e backups",
    "notifications": "Notificações",
    "integrations": "Integrações",
}


@dataclass(frozen=True)
class PermissionSpec:
    code: str
    label: str
    description: str
    risk: str
    critical: bool = False

    @property
    def module(self) -> str:
        return self.code.split(".", 1)[0]


CATALOG: tuple[PermissionSpec, ...] = (
    # Organização
    PermissionSpec("organization.company.read", "Ver dados da empresa", "Ler dados da empresa", "leitura"),
    PermissionSpec("organization.company.create", "Cadastrar a empresa", "Inicializar a empresa", "alteracao"),
    PermissionSpec("organization.company.update", "Editar a empresa", "Editar dados da empresa, logo e modelo do termo", "alteracao"),
    PermissionSpec("organization.units.read", "Ver unidades", "Ler unidades", "leitura"),
    PermissionSpec("organization.units.create", "Criar unidades", "Criar unidades", "alteracao"),
    PermissionSpec("organization.units.update", "Editar unidades", "Editar e excluir unidades", "alteracao"),
    PermissionSpec("organization.sectors.read", "Ver setores", "Ler setores", "leitura"),
    PermissionSpec("organization.sectors.create", "Criar setores", "Criar setores", "alteracao"),
    PermissionSpec("organization.sectors.update", "Editar setores", "Editar e excluir setores", "alteracao"),
    PermissionSpec("organization.employees.read", "Ver colaboradores", "Ler colaboradores", "leitura"),
    PermissionSpec("organization.employees.create", "Cadastrar colaboradores", "Criar colaboradores", "alteracao"),
    PermissionSpec("organization.employees.update", "Editar colaboradores", "Editar e excluir colaboradores", "alteracao"),
    # Usuários e perfis
    PermissionSpec("identity.users.read", "Ver usuários", "Ler usuários e suas concessões", "leitura"),
    PermissionSpec("identity.users.create", "Criar usuários", "Criar usuários", "administracao"),
    PermissionSpec("identity.users.update", "Editar usuários", "Editar, desativar e redefinir senha de usuários", "administracao"),
    PermissionSpec("identity.roles.read", "Ver perfis", "Ler perfis e permissões", "leitura"),
    PermissionSpec("identity.roles.create", "Criar perfis", "Criar perfis", "administracao"),
    PermissionSpec("identity.roles.update", "Editar perfis", "Editar e excluir perfis", "administracao"),
    PermissionSpec(
        "identity.critical.grant",
        "Conceder permissões críticas",
        "Conceder e revogar permissões críticas de outros usuários (auditado e avisado aos administradores)",
        "administracao",
        critical=True,
    ),
    # Patrimônio e ativos
    PermissionSpec("assets.read", "Ver patrimônio", "Ler patrimônio e ativos", "leitura"),
    PermissionSpec("assets.write", "Cadastrar e editar ativos", "Criar e editar ativos e seus anexos", "alteracao"),
    PermissionSpec("assets.categories.manage", "Gerenciar categorias de ativos", "Criar, editar e excluir categorias de ativos", "alteracao"),
    PermissionSpec(
        "assets.movements.write",
        "Movimentar ativos",
        "Reservar, entregar, devolver, inspecionar e cancelar reserva de ativos",
        "alteracao",
    ),
    PermissionSpec("assets.import", "Importar inventário (GLPI)", "Analisar e executar a importação de ativos do GLPI", "execucao"),
    PermissionSpec("assets.read_own", "Ver os próprios ativos", "Visualizar próprios ativos e equipamentos vinculados", "leitura"),
    # Estoque
    PermissionSpec("stock.read", "Ver estoque", "Ler estoque e insumos", "leitura"),
    PermissionSpec("stock.write", "Gerenciar estoque", "Criar/editar insumos e movimentações de estoque", "alteracao"),
    # Inventário
    PermissionSpec("inventory.read", "Ver inventários", "Ler inventários periódicos", "leitura"),
    PermissionSpec("inventory.write", "Conduzir inventários", "Criar e conduzir inventários periódicos", "alteracao"),
    # Auditoria
    PermissionSpec("audit.read", "Ver auditoria", "Visualizar logs de auditoria e trilha de conformidade", "leitura"),
    # Chamados
    PermissionSpec("service_desk.tickets.manage", "Atender chamados", "Atender e gerenciar chamados (técnico/setorial)", "alteracao"),
    PermissionSpec(
        "service_desk.categories.manage",
        "Gerenciar categorias de chamados",
        "Criar e editar categorias de chamados e o setor padrão de cada uma",
        "alteracao",
    ),
    # Hoje informativas: abrir e ver os próprios chamados depende só do vínculo com um colaborador (teste em
    # tests/access_control). Exigi-las é decisão à parte, porque tiraria o acesso de quem não tem perfil.
    PermissionSpec("service_desk.tickets.create", "Abrir chamados", "Abrir novos chamados de suporte", "alteracao"),
    PermissionSpec("service_desk.tickets.read", "Ver os próprios chamados", "Visualizar próprios chamados", "leitura"),
    PermissionSpec("service_desk.tickets.read_all", "Ver todos os chamados", "Visualizar todos os chamados da organização (Gestão)", "leitura"),
    PermissionSpec("service_desk.reports.read", "Ver relatórios de chamados", "Acessar relatórios e métricas de desempenho/SLA", "leitura"),
    PermissionSpec("service_desk.interactions.internal", "Notas internas", "Registrar e visualizar notas internas no chamado", "alteracao"),
    PermissionSpec(
        "service_desk.sla.manage",
        "Gerenciar SLA",
        "Criar e editar calendários e políticas de SLA, escolher o SLA de cada categoria e reabrir chamados fora do prazo",
        "alteracao",
    ),
    # Sistema, dados e backups
    PermissionSpec("system.data.export", "Exportar dados", "Exportar dados do sistema em formato CSV", "leitura"),
    PermissionSpec(
        "system.data.import",
        "Importar dados",
        "Importar dados no sistema via CSV (escrita em massa)",
        "execucao",
        critical=True,
    ),
    PermissionSpec(
        "system.backup.manage",
        "Gerenciar backups",
        "Gerar, listar, verificar e excluir backups",
        "execucao",
        critical=True,
    ),
    PermissionSpec(
        "system.demo.manage",
        "Dados de demonstração e de QA",
        "Carregar e limpar dados de demonstração e a carga de QA",
        "execucao",
        critical=True,
    ),
    PermissionSpec(
        "system.data.reset",
        "Zerar a base",
        "Apagar todos os dados de trabalho, mantendo usuários, perfis e configurações",
        "execucao",
        critical=True,
    ),
    PermissionSpec(
        "system.backup.download",
        "Baixar backups",
        "Baixar arquivos de backup (cópia completa do banco)",
        "execucao",
        critical=True,
    ),
    # Notificações e integrações
    PermissionSpec(
        "notifications.manage",
        "Administrar notificações",
        "Administrar o hub de notificações: entregas, regras, canais e agenda",
        "administracao",
    ),
    PermissionSpec(
        "notifications.messages.send",
        "Enviar mensagens",
        "Enviar mensagens pela Central de Mensagens a pessoas do próprio setor (com Administrar notificações, a qualquer pessoa)",
        "alteracao",
    ),
    PermissionSpec(
        "notifications.messages.read",
        "Ver histórico de mensagens",
        "Ver todos os envios da Central de Mensagens, não só os próprios",
        "leitura",
    ),
    PermissionSpec("integrations.whatsapp.manage", "Administrar WhatsApp", "Configurar e gerenciar bot do WhatsApp", "administracao"),
)

BY_CODE: dict[str, PermissionSpec] = {spec.code: spec for spec in CATALOG}
CRITICAL_CODES: frozenset[str] = frozenset(spec.code for spec in CATALOG if spec.critical)


def is_critical(code: str) -> bool:
    return code in CRITICAL_CODES


def effective_access(user) -> list[dict]:
    """
    O que a conta pode, permissão a permissão, com a origem: perfis (só as comuns), concessão individual (críticas)
    e "Administrador" (todas as comuns). É a mesma regra do login e de ``require_permission``.
    """
    granted = set(user.critical_permissions)
    result = []
    for spec in CATALOG:
        if spec.critical:
            sources = ["Concessão individual"] if spec.code in granted else []
        else:
            sources = [f"Perfil {role.name}" for role in user.roles if any(p.code == spec.code for p in role.permissions)]
            if user.is_admin:
                sources.append("Administrador")
        if sources:
            result.append(
                {
                    "code": spec.code,
                    "label": spec.label,
                    "description": spec.description,
                    "module": spec.module,
                    "module_label": MODULE_LABELS.get(spec.module, spec.module),
                    "risk": spec.risk,
                    "risk_label": RISK_LABELS[spec.risk],
                    "is_critical": spec.critical,
                    "sources": sources,
                }
            )
    return result


async def sync_permission_catalog(session: AsyncSession) -> None:
    """
    Cria as permissões que faltam, atualiza rótulo/risco/criticidade e tira as críticas de todos os perfis.

    Tirar dos perfis é a defesa do S5: mesmo que alguém grave uma crítica num perfil direto no banco, ela não
    chega a ninguém por perfil (o token também ignora críticas vindas de perfil).
    """
    from app.identity.models import Permission, role_permission_association

    existing = {p.code: p for p in (await session.execute(select(Permission))).scalars()}
    for spec in CATALOG:
        perm = existing.get(spec.code)
        if perm is None:
            perm = Permission(code=spec.code)
            session.add(perm)
        perm.description = spec.description
        perm.label = spec.label
        perm.module = spec.module
        perm.risk = spec.risk
        perm.is_critical = spec.critical
    await session.flush()

    critical_ids = select(Permission.id).where(Permission.is_critical.is_(True))
    await session.execute(
        delete(role_permission_association).where(role_permission_association.c.permission_id.in_(critical_ids))
    )
    await session.flush()
