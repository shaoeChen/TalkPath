import os

import pytest

from talkpath.adapters.provider_profiles import BackendKind, Capability
from talkpath.config import Settings


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    if os.getenv("TALKPATH_LIVE_TESTS") != "1":
        pytest.skip("TALKPATH_LIVE_TESTS is not 1")
    return Settings()


def require_live_profile(settings: Settings, capability: Capability):
    profile = settings.provider_profile(capability)
    if profile.backend is BackendKind.FAKE:
        pytest.fail(
            f"{capability.value} live profile must not use fake backend"
        )
    if profile.base_url is None:
        pytest.fail(
            f"{capability.value} live profile requires base_url "
            f"for backend {profile.backend.value}"
        )
    if not profile.model.strip():
        pytest.fail(f"{capability.value} live profile requires model")
    if (
        profile.backend is BackendKind.OPENAI_COMPATIBLE
        and profile.api_key is None
    ):
        pytest.fail(
            f"{capability.value} openai_compatible live profile requires api_key"
        )
    return profile
