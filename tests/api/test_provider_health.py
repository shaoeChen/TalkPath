from pathlib import Path

from fastapi.testclient import TestClient

from talkpath.api.app import create_app
from talkpath.config import Settings


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        sqlite_path=tmp_path / "progress.sqlite",
        lessonlens_root=tmp_path / "lessonlens",
        upload_root=tmp_path / "uploads",
        **overrides,
    )


def test_provider_health_reports_agent_backend_without_pi_secrets(tmp_path):
    settings = _settings(
        tmp_path,
        agent_backend="direct",
        pi_command="pi --api-key top-secret --endpoint https://pi.example/run",
    )

    response = TestClient(
        create_app(settings=settings, services=object(), testing=True)
    ).get("/health/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == {"backend": "direct"}
    assert "top-secret" not in response.text
    assert "pi --api-key" not in response.text
    assert "pi.example" not in response.text


def test_provider_health_reports_safe_metadata_without_network_probe(tmp_path):
    settings = _settings(
        tmp_path,
        vision_backend="openai_compatible",
        vision_base_url="https://vision.example/v1?secret=query-secret",
        vision_api_key="vision-secret",
        vision_model="vision-model",
        stt_backend="local_http",
        stt_base_url="http://stt.local",
        stt_model="stt-model",
    )

    response = TestClient(
        create_app(settings=settings, services=object(), testing=True)
    ).get("/health/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["agent"] == {"backend": "direct"}
    assert set(body["providers"]) == {"vision", "text", "stt", "tts"}
    assert body["providers"]["vision"] == {
        "backend": "openai_compatible",
        "model": "vision-model",
        "configured": True,
        "availability": "not_checked",
    }
    assert body["providers"]["stt"]["backend"] == "local_http"
    assert body["providers"]["stt"]["configured"] is True
    assert "vision-secret" not in response.text
    assert "query-secret" not in response.text
    assert "vision.example" not in response.text
    assert "prompt" not in response.text
    assert "audio" not in response.text
    assert "image" not in response.text


def test_provider_health_reports_missing_url_as_degraded_without_failing_app(
    tmp_path,
):
    settings = _settings(
        tmp_path,
        text_backend="openai_compatible",
        text_api_key="text-secret",
        text_model="text-model",
    )

    response = TestClient(
        create_app(settings=settings, services=object(), testing=True)
    ).get("/health/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["providers"]["text"] == {
        "backend": "openai_compatible",
        "model": "text-model",
        "configured": False,
        "availability": "not_configured",
    }
    assert "text-secret" not in response.text


def test_provider_health_reports_invalid_backend_without_secret_or_url(
    tmp_path,
):
    settings = _settings(
        tmp_path,
        tts_backend="unknown-vendor",
        tts_base_url="https://tts.example?secret=tts-secret",
        tts_api_key="tts-secret",
    )

    response = TestClient(
        create_app(settings=settings, services=object(), testing=True)
    ).get("/health/providers")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["providers"]["tts"]["backend"] == "invalid"
    assert body["providers"]["tts"]["configured"] is False
    assert body["providers"]["tts"]["availability"] == "invalid_configuration"
    assert "tts-secret" not in response.text
    assert "tts.example" not in response.text
