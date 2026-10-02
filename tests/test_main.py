import os

from talkpath import main


def test_run_uses_configured_host_and_port(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setenv("TALKPATH_APP_HOST", "0.0.0.0")
    monkeypatch.setenv("TALKPATH_APP_PORT", "9000")
    main.get_settings.cache_clear()
    monkeypatch.setattr(main.uvicorn, "run", fake_run)

    main.run()

    assert calls == [
        (
            ("talkpath.api.app:create_app",),
            {"factory": True, "host": "0.0.0.0", "port": 9000},
        )
    ]


def test_lan_run_uses_https_certificate_and_binds_network(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: type("Settings", (), {"app_host": "127.0.0.1", "app_port": 8000, "agent_backend": "direct"})(),
    )
    monkeypatch.setattr(main, "local_ipv4_addresses", lambda: ["192.168.1.50"])
    monkeypatch.setattr(main, "LAN_TLS_DIR", tmp_path)
    monkeypatch.setattr(main.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    main.run(lan=True)

    assert calls == [
        (
            ("talkpath.api.app:create_app",),
            {
                "factory": True,
                "host": "0.0.0.0",
                "port": 8000,
                "ssl_certfile": str(tmp_path / "talkpath-server.crt"),
                "ssl_keyfile": str(tmp_path / "talkpath-server.key"),
            },
        )
    ]


def test_lan_pi_mode_uses_local_https_and_preserves_existing_node_ca(monkeypatch, tmp_path):
    previous_ca = tmp_path / "existing-ca.crt"
    previous_ca.write_text("existing CA")
    monkeypatch.setenv("NODE_EXTRA_CA_CERTS", str(previous_ca))
    monkeypatch.setenv("TALKPATH_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: type("Settings", (), {"app_host": "127.0.0.1", "app_port": 9000, "agent_backend": "pi"})(),
    )
    monkeypatch.setattr(main, "local_ipv4_addresses", lambda: ["192.168.1.50"])
    monkeypatch.setattr(main, "LAN_TLS_DIR", tmp_path / "tls")
    seen = {}
    monkeypatch.setattr(
        main.uvicorn,
        "run",
        lambda *_args, **_kwargs: seen.update(
            url=os.environ["TALKPATH_API_BASE_URL"], ca=os.environ["NODE_EXTRA_CA_CERTS"]
        ),
    )

    main.run(lan=True)

    assert seen["url"] == "https://127.0.0.1:9000"
    bundle = (tmp_path / "tls" / "talkpath-node-ca-bundle.crt").read_bytes()
    assert seen["ca"] == str(tmp_path / "tls" / "talkpath-node-ca-bundle.crt")
    assert bundle.startswith(b"existing CA")
    assert (tmp_path / "tls" / "talkpath-ca.crt").read_bytes() in bundle


def test_lan_explicit_ip_works_when_auto_detection_finds_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: type("Settings", (), {"app_host": "127.0.0.1", "app_port": 8000, "agent_backend": "direct"})(),
    )
    monkeypatch.setattr(main, "local_ipv4_addresses", lambda: [])
    monkeypatch.setattr(main, "LAN_TLS_DIR", tmp_path)
    monkeypatch.setattr(main.uvicorn, "run", lambda *_args, **_kwargs: None)

    main.run(lan=True, lan_ips=["192.168.1.50"])

    assert (tmp_path / "talkpath-server.crt").exists()
