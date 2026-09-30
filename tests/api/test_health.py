from fastapi.testclient import TestClient

from talkpath.adapters.provider_registry import ProviderRegistry
from talkpath.agent.pi_rpc import PiRpcClient
from talkpath.api.app import create_app
from talkpath.application.session_service import SessionService
from talkpath.config import Settings


def test_health_returns_ok():
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_direct_app_does_not_construct_pi_and_health_returns_ok(monkeypatch, tmp_path):
    def fail_from_settings(cls, settings):
        raise AssertionError('direct mode must not construct Pi')

    monkeypatch.setattr(PiRpcClient, 'from_settings', classmethod(fail_from_settings))
    settings = Settings(
        _env_file=None,
        agent_backend='direct',
        lessonlens_root=tmp_path / 'lessonlens',
        sqlite_path=tmp_path / 'progress.sqlite',
        upload_root=tmp_path / 'uploads',
    )

    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.get('/health')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    assert app.state.session_service.agent_backend == 'direct'
    assert app.state.session_service.pi_client is None


def test_pi_app_constructs_pi_once_with_pi_settings(monkeypatch, tmp_path):
    calls = []

    class FakePi:
        async def close(self):
            pass

    fake_pi = FakePi()

    def fake_from_settings(cls, settings):
        calls.append(settings)
        return fake_pi

    monkeypatch.setattr(PiRpcClient, 'from_settings', classmethod(fake_from_settings))
    settings = Settings(
        _env_file=None,
        agent_backend='pi',
        lessonlens_root=tmp_path / 'lessonlens',
        sqlite_path=tmp_path / 'progress.sqlite',
        upload_root=tmp_path / 'uploads',
    )

    app = create_app(settings=settings)

    assert calls == [settings]
    assert calls[0].agent_backend == 'pi'
    assert app.state.session_service.agent_backend == 'pi'
    assert app.state.session_service.pi_client is fake_pi


def test_app_does_not_close_provider_registry_separately(monkeypatch):
    registry = ProviderRegistry.from_settings(Settings(_env_file=None))
    closed = False

    async def close_registry():
        nonlocal closed
        closed = True

    monkeypatch.setattr(registry, "aclose", close_registry)
    monkeypatch.setattr(
        ProviderRegistry,
        "from_settings",
        classmethod(lambda cls, settings: registry),
    )

    with TestClient(create_app(settings=Settings(_env_file=None))):
        pass

    assert closed is False


def test_app_closes_internally_created_service_once(monkeypatch, tmp_path):
    close_calls = []

    async def close_service(service):
        close_calls.append(service)

    monkeypatch.setattr(SessionService, 'aclose', close_service)
    settings = Settings(
        _env_file=None,
        agent_backend='direct',
        lessonlens_root=tmp_path / 'lessonlens',
        sqlite_path=tmp_path / 'progress.sqlite',
        upload_root=tmp_path / 'uploads',
    )
    app = create_app(settings=settings)

    with TestClient(app):
        pass

    assert close_calls == [app.state.session_service]


def test_app_does_not_close_externally_injected_service():
    class ExternalService:
        def __init__(self):
            self.close_calls = 0

        async def aclose(self):
            self.close_calls += 1

        def __bool__(self):
            return False

    service = ExternalService()
    app = create_app(services=service, testing=True)

    with TestClient(app):
        pass

    assert app.state.session_service is service
    assert service.close_calls == 0
