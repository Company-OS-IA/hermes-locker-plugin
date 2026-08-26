import pytest


@pytest.fixture(autouse=True)
def clear_locker_environment(monkeypatch):
    for name in (
        "LOCKER_ACCESS_KEY_ID",
        "LOCKER_ACCESS_KEY_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
