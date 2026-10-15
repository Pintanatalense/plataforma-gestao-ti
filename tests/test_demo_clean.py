"""
Teste automatizado para o fluxo de Limpeza Segura de Demonstração e Re-Seed Idempotente.
"""

import httpx

client = httpx.Client(base_url="http://localhost", timeout=25.0)

# 1. Login Admin
r = client.post("/api/v1/identity/login", data={"username": "admin@empresa.com.br", "password": "Demo@2026"})
assert r.status_code == 200, f"Falha no login admin: {r.text}"
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Status inicial
status_init = client.get("/api/v1/system/demo/status", headers=headers).json()
print("1. Status Inicial:", status_init["system_mode"], "| Registros Demo:", status_init["total_demo_records"])

# 3. Teste de rejeição por frase errada
bad_clean = client.post("/api/v1/system/demo/clean", json={"confirmation_phrase": "frase errada"}, headers=headers)
assert bad_clean.status_code == 400, "Deveria ter rejeitado com 400"
print("2. Rejeição com frase inválida: OK (400)")

# 4. Limpeza segura com frase correta
clean_resp = client.post("/api/v1/system/demo/clean", json={"confirmation_phrase": "LIMPAR DADOS DE DEMONSTRACAO"}, headers=headers)
assert clean_resp.status_code == 200, f"Falha na limpeza: {clean_resp.text}"
print("3. Limpeza executada com sucesso:", clean_resp.json()["summary"])

# 5. Validação de estado limpo
st_after = client.get("/api/v1/system/demo/status", headers=headers).json()
print("4. Status pós-limpeza:", st_after["system_mode"], "| Registros Demo:", st_after["total_demo_records"])
assert st_after["total_demo_records"] == 0
assert st_after["system_mode"] == "PRODUCTION"

# 6. Admin continua ativo e funcional
r_admin = client.post("/api/v1/identity/login", data={"username": "admin@empresa.com.br", "password": "Demo@2026"})
assert r_admin.status_code == 200
print("5. Login do Administrador após limpeza: 200 OK")

# 7. Re-seeding da demonstração
seed_resp = client.post("/api/v1/system/demo/seed", headers=headers)
assert seed_resp.status_code == 201, f"Falha no re-seed: {seed_resp.text}"
print("6. Re-seed executado:", seed_resp.json()["message"])

# 8. Validação de retorno ao modo Demo
st_seed = client.get("/api/v1/system/demo/status", headers=headers).json()
print("7. Status pós-re-seed:", st_seed["system_mode"], "| Registros Demo:", st_seed["total_demo_records"])
assert st_seed["total_demo_records"] > 0
assert st_seed["system_mode"] == "DEMO"

print("\n>>> ALL 7 DEMO MANAGEMENT & SAFE CLEANING CHECKS PASSED SUCCESSFULLY! <<<")
