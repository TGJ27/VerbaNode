from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Token
from app.knowledge import KnowledgeEngineConflict, KnowledgeEngineNotFound
from app.schemas import (
    AgentKnowledgeLibrariesUpdate,
    KnowledgeLibraryCreate,
    KnowledgeLibraryUpdate,
)
from app.state import state

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KnowledgeEngineNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, KnowledgeEngineConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="Knowledge Engine operation failed")


@router.get("/status")
async def knowledge_status(token: Token) -> dict[str, Any]:
    return state.knowledge.status()


@router.get("/libraries")
async def list_libraries(token: Token) -> list[dict[str, Any]]:
    return state.knowledge.list_libraries()


@router.get("/libraries/{library_id}")
async def get_library(library_id: int, token: Token) -> dict[str, Any]:
    try:
        return state.knowledge.get_library(library_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc


@router.post("/libraries")
async def create_library(payload: KnowledgeLibraryCreate, token: Token) -> dict[str, Any]:
    try:
        item = state.knowledge.create_library(payload.model_dump())
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast("knowledge_changed", {"kind": "library_created", "library": item})
    return item


@router.put("/libraries/{library_id}")
async def update_library(
    library_id: int, payload: KnowledgeLibraryUpdate, token: Token
) -> dict[str, Any]:
    try:
        item = state.knowledge.update_library(library_id, payload.model_dump())
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast("knowledge_changed", {"kind": "library_updated", "library": item})
    return item


@router.delete("/libraries/{library_id}")
async def delete_library(library_id: int, token: Token) -> dict[str, bool]:
    try:
        state.knowledge.delete_library(library_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast("knowledge_changed", {"kind": "library_deleted", "library_id": library_id})
    return {"ok": True}


@router.get("/documents")
async def list_documents(
    token: Token, library_id: int | None = Query(default=None, ge=1)
) -> list[dict[str, Any]]:
    try:
        return state.knowledge.list_documents(library_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc


@router.get("/documents/{document_id}")
async def get_document(document_id: int, token: Token) -> dict[str, Any]:
    try:
        return state.knowledge.get_document(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc


@router.get("/jobs")
async def list_jobs(
    token: Token, document_id: int | None = Query(default=None, ge=1)
) -> list[dict[str, Any]]:
    try:
        return state.knowledge.list_jobs(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc


@router.get("/agents/{agent_id}/libraries")
async def get_agent_libraries(agent_id: int, token: Token) -> dict[str, Any]:
    try:
        ids = state.knowledge.agent_library_ids(agent_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc
    return {"agent_id": agent_id, "library_ids": ids}


@router.put("/agents/{agent_id}/libraries")
async def set_agent_libraries(
    agent_id: int, payload: AgentKnowledgeLibrariesUpdate, token: Token
) -> dict[str, Any]:
    try:
        ids = state.knowledge.set_agent_libraries(agent_id, payload.library_ids)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict) as exc:
        raise _translate_error(exc) from exc
    result = {"agent_id": agent_id, "library_ids": ids}
    await state.events.broadcast("knowledge_changed", {"kind": "agent_libraries_updated", **result})
    return result
