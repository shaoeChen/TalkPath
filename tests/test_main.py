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
