import pytest

from talkpath.adapters.provider_profiles import (
    BackendKind,
    Capability,
    canonical_environment_names,
)


def test_backend_kind_is_string_compatible_for_configuration_serialization():
    assert BackendKind.OPENAI_COMPATIBLE == "openai_compatible"


def test_capability_environment_names_are_explicit_and_capability_specific():
    assert canonical_environment_names(Capability.VISION) == {
        "backend": "TALKPATH_VISION_BACKEND",
        "base_url": "TALKPATH_VISION_BASE_URL",
        "api_key": "TALKPATH_VISION_API_KEY",
        "model": "TALKPATH_VISION_MODEL",
    }


def test_canonical_environment_names_reject_unknown_capability():
    with pytest.raises(ValueError, match="unsupported capability"):
        canonical_environment_names("audio")
