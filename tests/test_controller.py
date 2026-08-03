from app.config import Settings
from app.services.controller import ControllerManager


def test_valid_pin_transfers_control_immediately(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", pin="2468", open_browser=False)
    manager = ControllerManager(settings)

    first = manager.login("2468", "Desktop")
    assert first["status"] == "granted"

    transferred = manager.login("2468", "Phone")
    assert transferred["status"] == "granted"
    assert transferred["takeover"] is True
    assert transferred["previous_client"] == "Desktop"
    assert manager.validate(transferred["token"])
    assert not manager.validate(first["token"])
