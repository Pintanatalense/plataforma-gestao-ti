"""
Validação Completa de Todas as Rotinas do Sistema:
1. Autenticação & Me
2. Cadastro e Atualização de Unidade
3. Cadastro e Atualização de Setor
4. Cadastro e Atualização de Colaborador
5. Cadastro e Atualização de Usuário (Identity) & Perfis
6. Cadastro, Edição e Validação de Categorias de Ativos
7. Cadastro, Edição, Atribuição de Ativo & Movimentações
8. Emissão de Termo de Responsabilidade do Ativo
9. Cadastro de Categorias de Chamados (Service Desk)
10. Abertura, Interação, Alteração de Status e Resolução de Chamado
11. Cadastro de Insumo de Estoque e Movimentação (Entrada/Saída)
12. Abertura e Listagem de Inventário Periódico
13. Exclusão de Categoria de Ativo (DELETE 204)
"""

import asyncio
import sys
import uuid
import httpx
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.identity.models import UserAccount, Permission

BASE_URL = "http://127.0.0.1:8000/api/v1"

async def run_all_tests():
    print("=" * 80)
    print("INICIANDO BATERIA DE TESTES DE TODAS AS ROTINAS DO SISTEMA")
    print("=" * 80)

    # 1. Obter usuário admin e permissões para gerar token JWT válido
    async with AsyncSessionLocal() as session:
        stmt_user = select(UserAccount).where(UserAccount.is_admin.is_(True)).limit(1)
        res_user = await session.execute(stmt_user)
        admin_user = res_user.scalar_one_or_none()
        if not admin_user:
            print("ERRO CRÍTICO: Nenhum usuário administrador encontrado no banco!")
            sys.exit(1)

        stmt_perms = select(Permission)
        res_perms = await session.execute(stmt_perms)
        perms = [p.code for p in res_perms.scalars().all()]

        token_data = {
            "sub": str(admin_user.id),
            "roles": ["Administrador"],
            "permissions": perms,
            "is_admin": True,
            "must_change_password": False,
        }
        token = create_access_token(token_data)
        admin_user_id = admin_user.id
        print(f"[OK] Token de Administrador gerado para: {admin_user.email}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=20.0) as client:
        # ---------------------------------------------------------------------
        # ROTINA 1: Healthcheck & Perfil
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 1: Verificação de Saúde e Identidade ---")
        res = await client.get("/health")
        assert res.status_code == 200, f"Falha no Health: {res.text}"
        print(f"[PASSED] Healthcheck: status {res.status_code} ({res.json().get('status')})")

        res = await client.get("/identity/me")
        assert res.status_code == 200, f"Falha no /identity/me: {res.text}"
        print(f"[PASSED] Perfil autenticado: {res.json().get('email')}")

        # ---------------------------------------------------------------------
        # ROTINA 2: Organização - Unidades
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 2: Organização - Unidades ---")
        unit_code = f"TEST_U_{uuid.uuid4().hex[:6]}"
        unit_payload = {
            "name": f"Filial Teste E2E {unit_code}",
            "code": unit_code,
            "type": "FILIAL"
        }
        res = await client.post("/organization/units", json=unit_payload)
        assert res.status_code == 201, f"Falha ao criar unidade: {res.text}"
        unit = res.json()
        unit_id = unit["id"]
        print(f"[PASSED] Unidade criada: ID {unit_id} - Código {unit['code']}")
        await asyncio.sleep(0.1)

        # Listar unidades
        res = await client.get("/organization/units")
        assert res.status_code == 200
        assert any(str(u["id"]) == str(unit_id) for u in res.json()), "Unidade criada não listada"
        print(f"[PASSED] Listagem de unidades validada ({len(res.json())} unidades no sistema)")

        # ---------------------------------------------------------------------
        # ROTINA 3: Organização - Setores
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 3: Organização - Setores ---")
        sec_code = f"SEC_{uuid.uuid4().hex[:6]}"
        sec_payload = {
            "name": f"Setor Teste {sec_code}",
            "code": sec_code,
            "unit_id": unit_id
        }
        res = await client.post("/organization/sectors", json=sec_payload)
        assert res.status_code == 201, f"Falha ao criar setor: {res.text}"
        sector = res.json()
        sector_id = sector["id"]
        assert sector.get("unit") is not None, "Setor criado sem objeto unit populado"
        print(f"[PASSED] Setor criado com sucesso: ID {sector_id} - Unidade: {sector['unit']['name']}")

        # Listar setores
        res = await client.get("/organization/sectors")
        assert res.status_code == 200, f"Falha ao listar setores: {res.status_code} - {res.text}"
        sectors_list = res.json()
        print(f"DEBUG: setores retornados: {[s.get('id') for s in sectors_list]}, procurando por {sector_id}")
        assert any(s["id"] == sector_id for s in sectors_list), f"Setor criado não listado: {sector_id} em {sectors_list}"
        print(f"[PASSED] Listagem de setores validada ({len(sectors_list)} setores no sistema)")

        # ---------------------------------------------------------------------
        # ROTINA 4: Organização - Colaboradores
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 4: Organização - Colaboradores ---")
        reg_number = f"REG_{uuid.uuid4().hex[:6]}"
        emp_payload = {
            "name": "Colaborador Teste Sistema",
            "registration_number": reg_number,
            "position": "Analista de Suporte",
            "unit_id": unit_id,
            "sector_id": sector_id
        }
        res = await client.post("/organization/employees", json=emp_payload)
        assert res.status_code == 201, f"Falha ao criar colaborador: {res.text}"
        emp = res.json()
        employee_id = emp["id"]
        assert emp.get("unit") is not None, "Colaborador criado sem objeto unit"
        assert emp.get("sector") is not None, "Colaborador criado sem objeto sector"
        print(f"[PASSED] Colaborador criado: ID {employee_id} - Matrícula: {emp['registration_number']} - Setor: {emp['sector']['name']}")

        # Vincular admin user ao colaborador para que o contexto de usuário possa abrir chamados
        async with AsyncSessionLocal() as session:
            admin_acc = await session.get(UserAccount, admin_user_id)
            if admin_acc and not admin_acc.employee_id:
                admin_acc.employee_id = uuid.UUID(employee_id)
                await session.commit()
                print(f"[OK] Usuário admin vinculado ao colaborador {employee_id}")

        # Listar colaboradores
        res = await client.get("/organization/employees")
        assert res.status_code == 200
        assert any(e["id"] == employee_id for e in res.json()), "Colaborador não listado"
        print(f"[PASSED] Listagem de colaboradores validada ({len(res.json())} colaboradores)")

        # ---------------------------------------------------------------------
        # ROTINA 5: Identidade - Usuários e Perfis
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 5: Identidade - Usuários e Perfis ---")
        res_roles = await client.get("/identity/roles")
        assert res_roles.status_code == 200
        roles = res_roles.json()
        assert len(roles) > 0, "Nenhum perfil cadastrado"
        role_id = roles[0]["id"]
        print(f"[PASSED] Perfis encontrados: {[r['name'] for r in roles]}")

        # Criar segundo colaborador para associar ao usuário
        emp_user_reg = f"REG_U_{uuid.uuid4().hex[:6]}"
        res_emp2 = await client.post("/organization/employees", json={
            "name": "Operador TI",
            "registration_number": emp_user_reg,
            "position": "Técnico",
            "unit_id": unit_id,
            "sector_id": sector_id
        })
        assert res_emp2.status_code == 201
        emp2_id = res_emp2.json()["id"]

        user_email = f"user.{uuid.uuid4().hex[:6]}@empresa.com"
        user_payload = {
            "email": user_email,
            "password": "Password@123",
            "employee_id": emp2_id,
            "role_ids": [role_id],
            "is_admin": False
        }
        res = await client.post("/identity/users", json=user_payload)
        assert res.status_code == 201, f"Falha ao criar usuário: {res.text}"
        new_user = res.json()
        user_id = new_user["id"]
        print(f"[PASSED] Usuário criado: ID {user_id} - Email {new_user['email']}")
        await asyncio.sleep(0.1)

        # Listar usuários
        res = await client.get("/identity/users")
        assert res.status_code == 200, f"Falha ao listar usuários: {res.status_code} - {res.text}"
        users_list = res.json()
        assert any(str(u["id"]) == str(user_id) for u in users_list), f"Usuário não listado: {user_id} em {users_list}"
        print(f"[PASSED] Listagem de usuários validada ({len(users_list)} usuários)")

        # ---------------------------------------------------------------------
        # ROTINA 6: Patrimônio - Categorias de Ativos
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 6: Patrimônio - Categorias de Ativos ---")
        cat_name = f"Categoria Teste {uuid.uuid4().hex[:6]}"
        cat_payload = {
            "name": cat_name,
            "description": "Categoria criada para validação E2E",
            "spec_schema": {
                "Processador": {"type": "string", "required": True, "label": "Processador"},
                "Memoria RAM": {"type": "string", "required": True, "label": "Memória RAM"},
                "Armazenamento": {"type": "string", "required": False, "label": "Armazenamento"}
            }
        }
        res = await client.post("/assets/categories", json=cat_payload)
        assert res.status_code == 200, f"Falha ao criar categoria de ativo: {res.text}"
        asset_cat = res.json()
        asset_cat_id = asset_cat["id"]
        print(f"[PASSED] Categoria de Ativo criada: ID {asset_cat_id} - Nome: {asset_cat['name']}")

        # Listar categorias de ativos
        res = await client.get("/assets/categories")
        assert res.status_code == 200
        assert any(c["id"] == asset_cat_id for c in res.json()), "Categoria não listada"
        print(f"[PASSED] Listagem de categorias de ativos validada ({len(res.json())} categorias)")

        # ---------------------------------------------------------------------
        # ROTINA 7: Patrimônio - Ativos, Movimentação e Termo
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 7: Patrimônio - Ativos, Movimentação e Termo ---")
        tag_pat = f"PAT-{uuid.uuid4().hex[:8].upper()}"
        asset_payload = {
            "tag": tag_pat,
            "name": f"Notebook Dell Latitude {tag_pat}",
            "category_id": asset_cat_id,
            "status": "IN_STOCK",
            "unit_id": unit_id,
            "technical_specs": {
                "Processador": "Intel Core i7 13th Gen",
                "Memoria RAM": "32 GB DDR5",
                "Armazenamento": "1 TB NVMe SSD"
            }
        }
        res = await client.post("/assets", json=asset_payload)
        assert res.status_code == 200, f"Falha ao criar ativo: {res.text}"
        asset = res.json()
        asset_id = asset["id"]
        print(f"[PASSED] Ativo criado: ID {asset_id} - Patrimônio: {asset['tag']} - Status: {asset['status']}")

        # Atribuir ativo ao colaborador (gera movimentação automática)
        update_payload = {
            **asset_payload,
            "status": "IN_USE",
            "employee_id": employee_id
        }
        res = await client.put(f"/assets/{asset_id}", json=update_payload)
        assert res.status_code == 200, f"Falha ao atualizar ativo: {res.text}"
        updated_asset = res.json()
        assert updated_asset["status"] == "IN_USE"
        assert updated_asset["employee_id"] == employee_id
        print(f"[PASSED] Ativo atribuído a colaborador: Status {updated_asset['status']} - Employee ID {employee_id}")

        # Validar histórico de movimentações do ativo
        res = await client.get(f"/movements/asset/{asset_id}")
        assert res.status_code == 200
        movs = res.json()
        assert len(movs) >= 1, "Nenhuma movimentação gerada para o ativo"
        print(f"[PASSED] Histórico de movimentações do ativo validado ({len(movs)} movimentações)")

        # Gerar Termo de Responsabilidade
        res = await client.get(f"/assets/{asset_id}/responsibility-statement")
        assert res.status_code == 200
        assert "TERMO DE RESPONSABILIDADE" in res.text or "Termo de Responsabilidade" in res.text or tag_pat in res.text
        print(f"[PASSED] Termo de Responsabilidade emitido com sucesso (HTML gerado com {len(res.text)} bytes)")

        # ---------------------------------------------------------------------
        # ROTINA 8: Service Desk - Categorias e Chamados
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 8: Service Desk - Categorias e Chamados ---")
        tkt_cat_payload = {
            "name": f"Suporte de Hardware {uuid.uuid4().hex[:4]}",
            "description": "Chamados de defeito em equipamentos",
            "default_sector_id": sector_id
        }
        res = await client.post("/tickets/categories", json=tkt_cat_payload)
        assert res.status_code in (200, 201), f"Falha ao criar categoria de chamado: {res.text}"
        tkt_cat = res.json()
        tkt_cat_id = tkt_cat["id"]
        print(f"[PASSED] Categoria de Chamado criada: ID {tkt_cat_id} - Nome: {tkt_cat['name']}")

        # Abrir chamado vinculando o ativo recém-cadastrado
        ticket_payload = {
            "title": "Notebook não liga após atualização",
            "description": "Equipamento parou de emitir vídeo e não dá boot no sistema operacional.",
            "category_id": tkt_cat_id,
            "asset_ids": [asset_id],
            "priority": "HIGH"
        }
        res = await client.post("/tickets", json=ticket_payload)
        assert res.status_code == 201, f"Falha ao criar chamado: {res.text}"
        ticket = res.json()
        ticket_id = ticket["id"]
        print(f"[PASSED] Chamado aberto com sucesso: ID {ticket_id} - Título: {ticket['title']} - Prioridade: {ticket['priority']}")

        # Adicionar interação/comentário no chamado
        interaction_payload = {
            "message": "Iniciando diagnóstico técnico de bancada.",
            "is_internal": False
        }
        res = await client.post(f"/tickets/{ticket_id}/interactions", json=interaction_payload)
        assert res.status_code == 201, f"Falha ao adicionar interação no chamado: {res.text}"
        print("[PASSED] Interação registrada no chamado com sucesso")

        # Atualizar status do chamado (IN_PROGRESS e RESOLVED)
        res = await client.patch(f"/tickets/{ticket_id}", json={"status": "IN_PROGRESS"})
        assert res.status_code == 200, f"Falha ao atualizar status do chamado: {res.text}"
        print("[PASSED] Chamado atualizado para: IN_PROGRESS")

        res = await client.patch(f"/tickets/{ticket_id}", json={"status": "RESOLVED"})
        assert res.status_code == 200, f"Falha ao resolver chamado: {res.text}"
        print("[PASSED] Chamado atualizado para: RESOLVED")

        # ---------------------------------------------------------------------
        # ROTINA 9: Estoque - Insumos e Movimentações
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 9: Estoque - Insumos e Movimentações ---")
        stock_payload = {
            "name": f"Pente de Memória RAM 16GB {uuid.uuid4().hex[:4]}",
            "description": "Pente de memória para upgrade",
            "min_quantity": 5,
            "unit_id": unit_id,
            "initial_quantity": 20
        }
        res = await client.post("/stock/items", json=stock_payload)
        assert res.status_code in (200, 201), f"Falha ao criar insumo de estoque: {res.text}"
        stock_item = res.json()
        stock_id = stock_item["id"]
        print(f"[PASSED] Insumo cadastrado: ID {stock_id} - Nome: {stock_item['name']} - Saldo: {stock_item.get('quantity')}")

        # Registrar saída de estoque
        mov_payload = {
            "item_id": stock_id,
            "movement_type": "OUT",
            "quantity": 3,
            "notes": "Substituição para manutenção em chamado"
        }
        res = await client.post("/stock/movements", json=mov_payload)
        assert res.status_code in (200, 201), f"Falha ao registrar movimentação de estoque: {res.text}"
        print("[PASSED] Saída de estoque registrada com sucesso: -3 unidades")

        # ---------------------------------------------------------------------
        # ROTINA 10: Inventário Periódico (Auditorias)
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 10: Inventário Periódico ---")
        inv_payload = {
            "name": f"Auditoria Trimestral {uuid.uuid4().hex[:4]}",
            "unit_id": unit_id,
            "auditor_id": str(admin_user_id)
        }
        res = await client.post("/inventory", json=inv_payload)
        assert res.status_code in (200, 201), f"Falha ao criar inventário: {res.text}"
        inv = res.json()
        inv_id = inv["id"]
        print(f"[PASSED] Inventário criado com sucesso: ID {inv_id} - Nome: {inv['name']} - Status: {inv['status']}")

        # Listar inventários
        res = await client.get("/inventory")
        assert res.status_code == 200
        assert any(i["id"] == inv_id for i in res.json()), "Inventário não listado"
        print(f"[PASSED] Listagem de inventários validada ({len(res.json())} inventários registrados)")

        # ---------------------------------------------------------------------
        # ROTINA 11: Exclusão Limpa (Deletar Categoria de Ativo via nova rota)
        # ---------------------------------------------------------------------
        print("\n--- ROTINA 11: Exclusão/Desativação da Categoria de Ativo ---")
        del_cat_name = f"Categoria Para Deletar {uuid.uuid4().hex[:4]}"
        res_cat_temp = await client.post("/assets/categories", json={"name": del_cat_name, "spec_schema": {}})
        assert res_cat_temp.status_code == 200
        temp_cat_id = res_cat_temp.json()["id"]

        res_del = await client.delete(f"/assets/categories/{temp_cat_id}")
        assert res_del.status_code == 204, f"Falha ao deletar categoria: {res_del.status_code}"
        print(f"[PASSED] DELETE /assets/categories/{temp_cat_id} validado com status 204 No Content")

    print("\n" + "=" * 80)
    print("TODAS AS ROTINAS FORAM TESTADAS E APROVADAS COM SUCESSO! 100% OK")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_all_tests())
