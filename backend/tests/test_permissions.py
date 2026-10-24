async def test_client_isolation_and_manager_rights(client, auth_headers, order_payload):
    client_a = await auth_headers(333)
    order = (await client.post("/api/orders", json=order_payload, headers=client_a)).json()
    client_b = await auth_headers(444)
    assert (await client.get(f"/api/orders/{order['id']}", headers=client_b)).status_code == 404
    assert (await client.get("/api/orders", headers=client_b)).json()["total"] == 0
    assert (await client.get("/api/admin/orders", headers=client_a)).status_code == 403
    assert (await client.get("/api/admin/dashboard", headers=client_a)).status_code == 403
    manager = await auth_headers(222)
    assert (await client.get("/api/admin/orders", headers=manager)).status_code == 200
    assert (await client.get("/api/admin/settings", headers=manager)).status_code == 403
    assert (await client.put("/api/admin/settings", headers=manager, json={"rate_cny_rub": "20", "commission_percent": "6.5", "commission_min_rub": "650"})).status_code == 403
    assert (await client.get("/api/admin/tariffs", headers=manager)).status_code == 403


async def test_role_recomputed_and_notes_private(client, app, auth_headers, order_payload):
    headers = await auth_headers(111)
    assert (await client.get("/api/admin/settings", headers=headers)).status_code == 200
    app.state.settings.owner_ids = ""
    assert (await client.get("/api/admin/settings", headers=headers)).status_code == 403
    client_headers = await auth_headers(333)
    order = (await client.post("/api/orders", json=order_payload, headers=client_headers)).json()
    manager = await auth_headers(222)
    response = await client.patch(f"/api/admin/orders/{order['id']}/note", json={"note": "Внутренняя информация"}, headers=manager)
    assert response.status_code == 200, response.text
    customer = (await client.get(f"/api/orders/{order['id']}", headers=client_headers)).json()
    assert "manager_note" not in customer
    assert all(x["type"] != "note" for x in customer["events"])
    assert "Внутренняя информация" not in str(customer)


async def test_idempotency_does_not_leak_other_client(client, auth_headers, order_payload):
    assert (await client.post("/api/orders", json=order_payload, headers=await auth_headers(333))).status_code == 200
    response = await client.post("/api/orders", json=order_payload, headers=await auth_headers(444))
    assert response.status_code == 409 and "public_no" not in response.json()
