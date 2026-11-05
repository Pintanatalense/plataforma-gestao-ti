"""
Gatilho que garante o registro do criador do chamado (``sd_ticket.created_by_user_id``).

A ``CHECK`` da tabela exige criador OU a marca ``creator_unknown``; este gatilho garante que a marca só exista nos
chamados antigos que a migration ``e5f6a7b8c9d0e`` identificou sem criador: um INSERT não pode trazê-la, e um UPDATE
não pode ligá-la (só desligá-la, quando alguém preenche o criador). Uma regra por data seria contornada por uma
inserção com ``created_at`` retroativo.

V1 congelada: a migration usa estas constantes. Mudar o comportamento exige nova versão e nova migration.
"""

CREATOR_GUARD_DDL_V1: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION sd_ticket_creator_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' AND NEW.creator_unknown THEN
            RAISE EXCEPTION 'chamado novo precisa registrar quem o abriu (creator_unknown só vale para registros antigos)'
                USING ERRCODE = 'check_violation';
        END IF;
        IF TG_OP = 'UPDATE' AND NEW.creator_unknown AND NOT OLD.creator_unknown THEN
            RAISE EXCEPTION 'não é permitido marcar um chamado como "criador desconhecido"'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$
    """,
    """
    CREATE TRIGGER sd_ticket_creator_guard
        BEFORE INSERT OR UPDATE OF creator_unknown ON sd_ticket
        FOR EACH ROW EXECUTE FUNCTION sd_ticket_creator_guard()
    """,
)

CREATOR_GUARD_DROP_V1: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS sd_ticket_creator_guard ON sd_ticket",
    "DROP FUNCTION IF EXISTS sd_ticket_creator_guard()",
)

CURRENT = CREATOR_GUARD_DDL_V1
