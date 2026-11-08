"""Opt-in isolated voice profile. Normal mode does not import these guards."""

from core.isolation.profile import (
    IsolatedProfileError,
    apply_isolated_profile,
    isolation_active,
    isolation_requested,
    isolation_required,
    persistence_disabled,
    prepare_runtime_config,
)

__all__ = [
    "IsolatedProfileError",
    "apply_isolated_profile",
    "isolation_active",
    "isolation_requested",
    "isolation_required",
    "persistence_disabled",
    "prepare_runtime_config",
]
