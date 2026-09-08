from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeEngine
from app.services.conversation import ConversationManager
from app.services.events import EventHub
from app.services.pipeline import PipelineMonitor
from app.services.prompts import PromptComposer
from app.services.tools import ToolService
from app.version import APP_VERSION


class _KnowledgeStub:
    def __init__(self, *, safe: bool = True, fail: bool = False) -> None:
        self.safe = safe
        self.fail = fail
        self.search_calls = 0

    def agent_library_ids(self, agent_id: int) -> list[int]:
        assert agent_id > 0
        return [7]

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self.search_calls += 1
        if self.fail:
            raise RuntimeError("simulated retrieval outage")
        evidence = [
            {
                "evidence_id": "K1",
                "chunk_id": 11,
                "document_id": 12,
                "library_id": 7,
                "document_title": "XR4 Service Manual",
                "source_name": "xr4-service.pdf",
                "heading_path": "Power > Drive Controller",
                "page_start": 42,
                "page_end": 42,
                "content_type": "text",
                "text": "The XR4 shoulder drive resets below 20 volts under sustained load.",
            }
        ]
        return {
            "library_ids": [7],
            "routing": {"intent": "semantic"},
            "confidence": {"label": "high", "score": 0.91, "fallback_used": False},
            "warnings": [],
            "elapsed_ms": 3.5,
            "context": {
                "safe_to_inject": self.safe,
                "estimated_tokens": 23,
                "evidence": evidence,
            },
        }


class _CapturingLlm:
    def __init__(self, settings: Settings) -> None:
        self.tools = ToolService(settings)
        self.prompts = PromptComposer(settings)
        self.messages: list[dict[str, Any]] = []

    def build_system_prompt(
        self,
        agent: dict[str, Any],
        information: list[dict[str, Any]],
        summary: str | None,
        *,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> str:
        schemas = (
            self.tools.schemas(agent.get("tools_enabled") or [])
            if tool_schemas is None
            else tool_schemas
        )
        return self.prompts.compose(
            agent=agent,
            information=information,
            summary=summary,
            tool_schemas=schemas,
        )

    async def chat_stream(self, **kwargs: Any) -> tuple[str, bool]:
        self.messages = list(kwargs["messages"])
        await kwargs["on_token"]("Integrated RAG answer")
        return "Integrated RAG answer", False


class _NoopTts:
    player = None


def _manager(tmp_path: Path, knowledge: Any) -> tuple[Database, ConversationManager, _CapturingLlm]:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    llm = _CapturingLlm(settings)
    manager = ConversationManager(
        settings=settings,
        db=db,
        events=EventHub(),
        recorder=object(),
        stt=object(),
        llm=llm,
        tts=_NoopTts(),
        monitor=PipelineMonitor(),
        knowledge=knowledge,
    )
    return db, manager, llm


def test_phase5_status_and_client_contract_cut_over_to_rag(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "status.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    engine = KnowledgeEngine(db, settings.knowledge_dir)

    assert APP_VERSION == "0.12.4"
    status = engine.status()
    assert status["phase"] == "legacy_information_migrated"
    assert status["retrieval_chat_enabled"] is True
    assert status["legacy_information_injection_active"] is False
    assert status["capabilities"]["chat_integration"] is True

    features = feature_manifest()
    assert features["knowledge_engine_phase"] == "legacy_information_migrated"
    assert features["knowledge_chat_integration"] is True
    assert features["knowledge_voice_integration"] is True
    assert features["knowledge_legacy_information_injection"] is False


@pytest.mark.asyncio
async def test_chat_injects_only_safe_retrieved_evidence(
    tmp_path: Path,
) -> None:
    knowledge = _KnowledgeStub(safe=True)
    _db, manager, llm = _manager(tmp_path, knowledge)

    result = await manager.process_user_text(
        text="Why does the XR4 shoulder drive reset under load?",
        conversation_id=None,
        source="text",
        speak=False,
        allow_barge_in=False,
    )

    system_prompt = llm.messages[0]["content"]
    assert "The XR4 shoulder drive resets below 20 volts" in system_prompt
    assert "[K1]" in system_prompt
    assert result["knowledge"]["used"] is True
    assert result["knowledge"]["safe_to_inject"] is True
    assert result["knowledge"]["sources"][0]["source_name"] == "xr4-service.pdf"
    assert knowledge.search_calls == 1


@pytest.mark.asyncio
async def test_low_confidence_rag_is_not_injected(tmp_path: Path) -> None:
    knowledge = _KnowledgeStub(safe=False)
    _db, manager, llm = _manager(tmp_path, knowledge)

    result = await manager.process_user_text(
        text="Unrelated question with weak evidence",
        conversation_id=None,
        source="text",
        speak=False,
        allow_barge_in=False,
    )

    assert "XR4 shoulder drive resets" not in llm.messages[0]["content"]
    assert result["knowledge"]["used"] is False
    assert result["knowledge"]["safe_to_inject"] is False
    assert result["knowledge"]["sources"] == []


@pytest.mark.asyncio
async def test_retrieval_failure_does_not_break_chat(tmp_path: Path) -> None:
    knowledge = _KnowledgeStub(fail=True)
    _db, manager, llm = _manager(tmp_path, knowledge)

    result = await manager.process_user_text(
        text="Answer even if retrieval is temporarily unavailable",
        conversation_id=None,
        source="text",
        speak=False,
        allow_barge_in=False,
    )

    assert result["message"]["content"] == "Integrated RAG answer"
    assert result["knowledge"]["reason"] == "retrieval_failed"
    assert result["knowledge"]["used"] is False
    assert "RETRIEVED KNOWLEDGE POLICY" not in llm.messages[0]["content"]


@pytest.mark.asyncio
async def test_deterministic_core_tool_request_skips_rag(tmp_path: Path) -> None:
    knowledge = _KnowledgeStub(safe=True)
    db, manager, _llm = _manager(tmp_path, knowledge)
    agent = db.list_agents()[0]
    payload = dict(agent)
    payload["tools_enabled"] = ["get_current_time"]
    # update_agent expects only editable fields plus info/tools; preserve the
    # current profile while enabling the deterministic time tool.
    db.update_agent(int(agent["id"]), payload)

    result = await manager.process_user_text(
        text="What time is it?",
        conversation_id=None,
        source="text",
        speak=False,
        allow_barge_in=False,
    )

    assert knowledge.search_calls == 0
    assert result["knowledge"]["reason"] == "direct_tool"
    assert result["message"]["source"] == "tool"
