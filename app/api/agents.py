from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.api.deps import Token
from app.schemas import AgentCreate, AgentUpdate, RoleGenerateRequest
from app.services.llm import OllamaUnavailable
from app.state import state

router = APIRouter(tags=["agents"])


@router.get("/api/agents")
async def list_agents(token: Token) -> list[dict[str, Any]]:
    return state.db.list_agents()


@router.post("/api/agents")
async def create_agent(payload: AgentCreate, token: Token) -> dict[str, Any]:
    agent = state.db.create_agent(payload.model_dump())
    await state.events.broadcast("agents_changed", state.db.list_agents())
    return agent


@router.put("/api/agents/{agent_id}")
async def update_agent(agent_id: int, payload: AgentUpdate, token: Token) -> dict[str, Any]:
    agent = state.db.update_agent(agent_id, payload.model_dump())
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await state.events.broadcast("agents_changed", state.db.list_agents())
    return agent


@router.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: int, token: Token) -> dict[str, bool]:
    try:
        deleted = state.db.delete_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    await state.events.broadcast("agents_changed", state.db.list_agents())
    return {"ok": True}


@router.post("/api/agents/{agent_id}/activate")
async def activate_agent(agent_id: int, token: Token) -> dict[str, Any]:
    return await state.conversation.switch_agent(agent_id)


@router.post("/api/agents/generate-role")
async def generate_role(payload: RoleGenerateRequest, token: Token) -> dict[str, str]:
    try:
        return await state.llm.generate_role(payload.description, payload.model)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/api/agents/{agent_id}/memory")
async def clear_agent_memory(agent_id: int, token: Token) -> dict[str, bool]:
    if not state.db.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    state.db.clear_agent_memory(agent_id)
    await state.events.broadcast("memory_updated", {"agent_id": agent_id, "cleared": True})
    return {"ok": True}


@router.get("/api/agents/{agent_id}/backup")
async def backup_agent(agent_id: int, token: Token) -> JSONResponse:
    agent = state.db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    conversations = state.db.list_conversations(agent_id)
    data = {
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "information": [
            item for item in state.db.list_information() if item["id"] in agent["info_ids"]
        ],
        "conversations": [
            {
                **conversation,
                "messages": state.db.list_messages(int(conversation["id"]), limit=100000),
            }
            for conversation in conversations
        ],
    }
    filename = f"agent-{agent_id}-backup.json"
    return JSONResponse(
        data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
