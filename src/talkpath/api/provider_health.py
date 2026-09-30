"""Safe provider readiness metadata for the health endpoint."""

from __future__ import annotations

from talkpath.adapters.provider_profiles import BackendKind, Capability
from talkpath.config import Settings


def provider_health_report(settings: Settings) -> dict[str, object]:
    providers: dict[str, dict[str, object]] = {}
    healthy = True

    for capability in Capability:
        try:
            profile = settings.provider_profile(capability)
        except ValueError:
            providers[capability.value] = {
                "backend": "invalid",
                "model": "unknown",
                "configured": False,
                "availability": "invalid_configuration",
            }
            healthy = False
            continue

        configured = (
            profile.backend is BackendKind.FAKE or profile.base_url is not None
        )
        providers[capability.value] = {
            "backend": profile.backend.value,
            "model": profile.model,
            "configured": configured,
            "availability": "not_checked" if configured else "not_configured",
        }
        healthy = healthy and configured

    return {
        "status": "ok" if healthy else "degraded",
        "agent": {"backend": settings.agent_backend},
        "providers": providers,
    }


__all__ = ["provider_health_report"]
