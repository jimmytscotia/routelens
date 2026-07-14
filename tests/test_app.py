from routelens.app import create_app


def test_health_endpoint_returns_ok(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})
    client = app.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_database_path_can_come_from_environment(tmp_path, monkeypatch):
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("ROUTELENS_DATABASE", str(db_path))

    app = create_app({"TESTING": True})

    assert app.config["DATABASE"] == str(db_path)
    assert db_path.exists()


def test_resource_detail_renders_latest_telemetry(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})
    store = app.config["ROUTELENS_STORE"]
    resource = next(item for item in store.list_resources() if item["name"] == "web.nexthop.engineer")
    store.record_check(
        resource_id=resource["id"],
        check_type="dns",
        status="healthy",
        summary="private DNS is present and public DNS is absent",
        details={"public_answers": [], "private_answers": ["100.94.135.62"]},
    )
    client = app.test_client()

    response = client.get(f"/resources/{resource['id']}")

    assert response.status_code == 200
    assert b"web.nexthop.engineer" in response.data
    assert b"private DNS is present" in response.data
    assert b"100.94.135.62" in response.data


def test_prefix_detail_renders_bgp_path_visualisation(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})
    store = app.config["ROUTELENS_STORE"]
    resource = next(item for item in store.list_resources() if item["name"] == "8.8.8.0/24")
    store.record_check(
        resource_id=resource["id"],
        check_type="bgp",
        status="healthy",
        summary="visible at 3 collectors with a single origin AS15169",
        details={
            "resource": "8.8.8.0/24",
            "collector_count": 3,
            "unique_path_count": 2,
            "origins": [15169],
            "sample_paths": [
                [64500, 3356, 15169],
                [64501, 1299, 15169],
            ],
        },
    )
    client = app.test_client()

    response = client.get(f"/resources/{resource['id']}")
    body = response.data.decode()

    assert response.status_code == 200
    # A dedicated AS-path visualisation section is present.
    assert "bgp-paths" in body
    assert "AS path" in body
    # Each hop of a stored sample path is rendered.
    assert "AS64500" in body
    assert "AS3356" in body
    assert "AS15169" in body
    assert "AS1299" in body
    # The origin AS is marked as such.
    assert "origin" in body.lower()


def test_non_prefix_detail_omits_bgp_path_visualisation(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})
    store = app.config["ROUTELENS_STORE"]
    resource = next(item for item in store.list_resources() if item["name"] == "web.nexthop.engineer")
    store.record_check(
        resource_id=resource["id"],
        check_type="dns",
        status="healthy",
        summary="private DNS is present and public DNS is absent",
        details={"private_answers": ["100.94.135.62"]},
    )
    client = app.test_client()

    response = client.get(f"/resources/{resource['id']}")
    body = response.data.decode()

    assert response.status_code == 200
    assert "bgp-paths" not in body
