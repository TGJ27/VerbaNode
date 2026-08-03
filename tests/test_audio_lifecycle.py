import asyncio
import threading

from app.services.conversation import ConversationManager


def test_stop_conversation_pauses_capture_then_releases_persistent_input():
    manager = object.__new__(ConversationManager)
    manager._stop_event = threading.Event()
    manager._conversation_task = None
    manager._ptt_active = False
    manager._mode = "conversation"

    calls = []

    class Recorder:
        def cancel_capture(self, wait=True, timeout=2.0):
            calls.append(("cancel", wait, timeout))
            return True

        def cancel_ptt(self):
            calls.append(("ptt",))

        def unlock_input(self):
            calls.append(("unlock",))

    class Player:
        output_locked = True

    class Tts:
        player = Player()

    class Events:
        async def broadcast(self, *args, **kwargs):
            return None

    manager.recorder = Recorder()
    manager.tts = Tts()
    manager.events = Events()

    async def no_tts():
        calls.append(("tts",))

    manager.stop_current_tts = no_tts
    asyncio.run(manager.stop_conversation(stop_tts=True))

    assert calls == [
        ("tts",),
        ("cancel", True, 2.0),
        ("ptt",),
        ("unlock",),
    ]


def test_start_conversation_locks_output_before_input():
    manager = object.__new__(ConversationManager)
    manager._conversation_task = None
    manager._ptt_active = False
    manager._mode = "idle"
    manager._stop_event = threading.Event()
    manager.script_queue = None
    calls = []

    class DB:
        def get_runtime_settings(self):
            return {"input_device": 20, "output_device": 16}

    class Recorder:
        def cancel_capture(self, wait=True, timeout=2.0):
            calls.append(("cancel",))
            return True

        def lock_input(self, device):
            calls.append(("input", device))

    class Player:
        output_locked = False

        def set_output_device(self, device):
            calls.append(("select_output", device))

        def lock_output(self, device):
            calls.append(("output", device))
            self.output_locked = True

    class Tts:
        player = Player()

    class Events:
        async def broadcast(self, *args, **kwargs):
            return None

    async def idle_loop():
        return None

    manager.db = DB()
    manager.recorder = Recorder()
    manager.tts = Tts()
    manager.events = Events()
    manager._conversation_loop = idle_loop

    asyncio.run(manager.start_conversation())

    assert calls.index(("output", 16)) < calls.index(("input", 20))
