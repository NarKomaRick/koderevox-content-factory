from app.core.capabilities import CapabilityRegistry
from app.core.config import Settings


def test_capability_registry_reports_flags_without_exposing_secrets() -> None:
    settings = Settings(
        operations_enabled=True,
        producer_enabled=True,
        director_enabled=False,
        credential_encryption_key="secret-value",
    )
    snapshot = CapabilityRegistry(settings).snapshot().as_dict()
    assert snapshot["operations"] is True
    assert snapshot["producer"] is True
    assert snapshot["director"] is False
    assert snapshot["publishing"] is True
    assert "secret-value" not in str(snapshot)
