from pathlib import Path

from app.config import Settings
from app.db import Database


def test_seed_and_agent_isolation(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        open_browser=False,
        default_model="test-model:3b",
    )
    db = Database(settings)
    db.initialize()
    agents = db.list_agents()
    assert len(agents) == 2
    english = next(agent for agent in agents if agent["language"] == "en")
    indonesian = next(agent for agent in agents if agent["language"] == "id")
    assert english["name"] == "Ropi"
    assert english["llm_model"] == "qwen3.5:0.8b"
    assert english["temperature"] == 0.2
    assert english["top_p"] == 0.8
    assert english["max_tokens"] == 224
    assert "You are Ropi" in english["system_prompt"]
    assert "get_current_time" not in english["system_prompt"]
    assert "Mandatory live-data" not in english["system_prompt"]
    assert indonesian["stt_model"] == "Whisper-base"
    assert indonesian["edge_voice"] == "id-ID-GadisNeural"

    info = db.create_information({"title": "Company", "content": "We build robots.", "enabled": True})
    payload = dict(english)
    for key in ("id", "created_at", "updated_at"):
        payload.pop(key, None)
    payload["name"] = "Receptionist"
    payload["info_ids"] = [info["id"]]
    created = db.create_agent(payload)
    assert created["info_ids"] == [info["id"]]
    assert any(item["id"] == info["id"] for item in db.enabled_information_for_agent(created["id"]))
    default_english_info = db.enabled_information_for_agent(english["id"])
    assert any(item["title"] == "Sari Teknologi Company Profile" for item in default_english_info)


def test_script_queue_order(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    first = db.list_scripts()[0]
    second = db.create_script({"title": "Second", "text": "Second text", "enabled": True})
    q1 = db.queue_script(first["id"])
    q2 = db.queue_script(second["id"])
    assert [item["id"] for item in db.list_queue()] == [q1["id"], q2["id"]]
    db.reorder_queue([q2["id"], q1["id"]])
    assert [item["id"] for item in db.list_queue()] == [q2["id"], q1["id"]]


def test_audio_safety_migrates_interruption_to_half_duplex(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    assert db.get_runtime_settings()["interruption_enabled"] is False

    # Simulate an older database where interruption was enabled by default and
    # the safety migration marker did not yet exist.
    with db.connect() as conn:
        conn.execute("UPDATE settings SET value='true' WHERE key='interruption_enabled'")
        conn.execute("DELETE FROM settings WHERE key='audio_safety_version'")
    db.initialize()
    assert db.get_runtime_settings()["interruption_enabled"] is False
    assert db.get_setting("audio_safety_version") == "1"


def test_audio_device_ids_persist_in_runtime_settings(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    db.set_setting("input_device", "20")
    db.set_setting("output_device", "16")
    runtime = db.get_runtime_settings()
    assert runtime["input_device"] == 20
    assert runtime["output_device"] == 16


def test_existing_ropi_receives_requested_defaults_once(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    ropi = db.list_agents()[0]
    with db.connect() as conn:
        conn.execute(
            "UPDATE agents SET role='Old role',system_prompt='Old prompt',temperature=0.9,top_p=0.95,max_tokens=900,tools_enabled='[]' WHERE id=?",
            (ropi["id"],),
        )
        conn.execute("UPDATE settings SET value='0.82' WHERE key='stt_confidence_threshold'")
        conn.execute("UPDATE settings SET value='0' WHERE key='ropi_defaults_version'")
    db.initialize()
    migrated = db.get_agent(ropi["id"])
    assert migrated is not None
    assert migrated["role"] == "Humanoid robot receptionist for Sari Technology Global"
    assert "You are Ropi" in migrated["system_prompt"]
    assert "get_current_time" not in migrated["system_prompt"]
    assert migrated["temperature"] == 0.2
    assert migrated["top_p"] == 0.8
    assert migrated["max_tokens"] == 224
    assert set(migrated["tools_enabled"]) >= {
        "get_current_time",
        "get_location",
        "get_weather",
        "handle_exit_intent",
    }
    assert db.get_setting("stt_confidence_threshold") == "0.82"
    assert db.get_setting("ropi_defaults_version") == "4"


def test_v031_operational_prompt_is_migrated_but_custom_role_is_preserved(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    ropi = db.list_agents()[0]
    with db.connect() as conn:
        conn.execute(
            "UPDATE agents SET role=?, system_prompt=? WHERE id=?",
            (
                "Friendly humanoid robot receptionist",
                "Primary behavior:\nMandatory live-data and tool rules:\nTools are the only source of truth",
                ropi["id"],
            ),
        )
        conn.execute("UPDATE settings SET value='3' WHERE key='ropi_defaults_version'")
    db.initialize()
    migrated = db.get_agent(ropi["id"])
    assert migrated is not None
    assert migrated["role"] == "Humanoid robot receptionist for Sari Technology Global"
    assert "You are Ropi" in migrated["system_prompt"]
    assert "Mandatory live-data" not in migrated["system_prompt"]
    assert db.get_setting("ropi_defaults_version") == "4"

    with db.connect() as conn:
        conn.execute(
            "UPDATE agents SET role='My custom role', system_prompt='My custom character' WHERE id=?",
            (ropi["id"],),
        )
        conn.execute("UPDATE settings SET value='3' WHERE key='ropi_defaults_version'")
    db.initialize()
    custom = db.get_agent(ropi["id"])
    assert custom is not None
    assert custom["role"] == "My custom role"
    assert custom["system_prompt"] == "My custom character"
    assert db.get_setting("ropi_defaults_version") == "4"
