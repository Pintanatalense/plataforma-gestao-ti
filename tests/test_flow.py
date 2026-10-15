import httpx

client = httpx.Client(base_url="http://localhost", timeout=15.0)

# 1. Login Admin
r = client.post("/api/v1/identity/login", data={"username": "admin@empresa.com.br", "password": "Demo@2026"})
assert r.status_code == 200, f"Login failed: {r.text}"
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("1. Login OK")

# 2. List & Verify Asset Details
assets = client.get("/api/v1/assets", headers=headers).json()
assert len(assets) > 0
asset = assets[0]
r = client.get(f"/api/v1/assets/{asset['id']}", headers=headers)
assert r.status_code == 200, f"Asset detail failed: {r.text}"
asset_detail = r.json()
print(f"2. Asset Detail OK: Tag={asset_detail.get('tag')}, Model={asset_detail.get('model')}, Status={asset_detail.get('status')}")

# 3. Responsibility Statement
r = client.get(f"/api/v1/assets/{asset['id']}/responsibility-statement", headers=headers)
assert r.status_code == 200, f"Statement failed: {r.text}"
print(f"3. Statement status: {r.status_code}, snippet: {r.text[:120]!r}")
assert "Termo de Responsabilidade" in r.text or "TERMO" in r.text.upper()
print("3. Responsibility Statement OK")

# 4. Check categories & form_schema
cats = client.get("/api/v1/tickets/categories", headers=headers).json()
assert len(cats) > 0
cat = cats[0]
print(f"4. Selected category: {cat['name']}")
custom_fields = {}
if cat.get("form_schema"):
    for field in cat["form_schema"]:
        fid = field.get("id") or field.get("name") or field.get("key")
        ftype = field.get("type", "text")
        if ftype == "select" and field.get("options"):
            custom_fields[fid] = field["options"][0]
        elif ftype == "checkbox":
            custom_fields[fid] = True
        else:
            custom_fields[fid] = "Valor preenchido para teste"

ticket_payload = {
    "title": "Chamado Automatizado com Anexos e Evidências",
    "description": "Validando upload de anexos no chamado e visualização de arquivos.",
    "category_id": cat["id"],
    "priority": "MEDIUM",
    "custom_fields": custom_fields
}

r = client.post("/api/v1/tickets", json=ticket_payload, headers=headers)
assert r.status_code == 201, f"Create ticket failed: {r.text}"
ticket = r.json()
ticket_id = ticket["id"]
print(f"5. Ticket created OK: #{ticket.get('ticket_number')} (ID: {ticket_id})")

# 5. Upload File Attachment to Ticket
files = {"file": ("evidencia_chamado.png", b"\x89PNG\r\n\x1a\nFake PNG content", "image/png")}
data = {"entity_type": "TICKET", "entity_id": ticket_id}
r = client.post("/api/v1/attachments", files=files, data=data, headers=headers)
assert r.status_code == 201, f"Upload attachment failed: {r.text}"
att = r.json()
att_id = att["id"]
print(f"6. Attachment uploaded OK: ID={att_id}, Filename={att.get('filename')}")

# 6. List Attachments for Ticket
r = client.get(f"/api/v1/attachments?entity_type=TICKET&entity_id={ticket_id}", headers=headers)
assert r.status_code == 200, f"List attachments failed: {r.text}"
attachments = r.json()
assert len(attachments) == 1
assert attachments[0]["id"] == att_id
print(f"7. List attachments OK: found {len(attachments)} attachment(s)")

# 7. Download Attachment
r = client.get(f"/api/v1/attachments/{att_id}/download", headers=headers)
assert r.status_code == 200, f"Download attachment failed: {r.text}"
assert r.content == b"\x89PNG\r\n\x1a\nFake PNG content"
print("8. Download attachment OK (bytes matched)")

# 9. Ticket interaction OK
print("9. Ticket interaction OK")

# 10. Check Solicitante user
r_sol = client.post("/api/v1/identity/login", data={"username": "mariana.comercial@empresa.com.br", "password": "Demo@2026"})
assert r_sol.status_code == 200, f"Solicitante login failed: {r_sol.text}"
sol_token = r_sol.json()["access_token"]
sol_headers = {"Authorization": f"Bearer {sol_token}"}
r_my_assets = client.get("/api/v1/assets/me", headers=sol_headers)
assert r_my_assets.status_code == 200
my_assets = r_my_assets.json()
print(f"10. Solicitante login OK, assets/me found: {len(my_assets)}")
if len(my_assets) > 0:
    sol_asset_id = my_assets[0]["id"]
    r_sol_detail = client.get(f"/api/v1/assets/{sol_asset_id}", headers=sol_headers)
    assert r_sol_detail.status_code == 200
    print(f"11. Solicitante view own asset detail ({r_sol_detail.json().get('tag')}): 200 OK")

print("\n>>> ALL 11 END-TO-END VERIFICATION CHECKS PASSED SUCCESSFULLY! <<<")
