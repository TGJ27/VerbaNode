from app.config import Settings
from app.services.controller import ControllerManager


def test_takeover_flow(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", pin="2468", open_browser=False)
    manager = ControllerManager(settings)

    first = manager.login("2468", "Desktop")
    assert first["status"] == "granted"

    second = manager.login("2468", "Phone")
    assert second["status"] == "takeover_required"
    assert second["active_client"] == "Desktop"

    transferred = manager.login("2468", "Phone", force_takeover=True)
    assert transferred["status"] == "granted"
    assert transferred["takeover"] is True
    assert transferred["previous_client"] == "Desktop"
    assert manager.validate(transferred["token"])
    assert not manager.validate(first["token"])
