from src.analytics.validators.__main__ import main


def test_validator_entrypoint_succeeds() -> None:
    assert main() == 0
