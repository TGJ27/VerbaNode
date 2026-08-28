from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile, status

from app.api.deps import Token
from app.knowledge import (
    KnowledgeEngineConflict,
    KnowledgeEngineNotFound,
    KnowledgeEngineValidation,
)
from app.schemas import (
    AgentKnowledgeLibrariesUpdate,
    KnowledgeIndexRebuildRequest,
    KnowledgeLibraryCreate,
    KnowledgeLibraryUpdate,
    KnowledgeSearchRequest,
)
from app.state import state

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KnowledgeEngineNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, KnowledgeEngineConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, KnowledgeEngineValidation):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Knowledge Engine operation failed")


async def _run_ingestion(document_id: int, job_id: int) -> None:
    try:
        document = state.knowledge.ingest_document(document_id, job_id)
    except Exception as exc:
        await state.events.broadcast(
            "knowledge_changed",
            {
                "kind": "document_ingestion_failed",
                "document_id": document_id,
                "job_id": job_id,
                "error": str(exc),
            },
        )
        return
    await state.events.broadcast(
        "knowledge_changed",
        {
            "kind": "document_ingested",
            "document": document,
            "job_id": job_id,
        },
    )


async def _run_index_rebuild(library_id: int | None) -> None:
    try:
        result = await asyncio.to_thread(state.knowledge.rebuild_index, library_id)
    except Exception as exc:
        await state.events.broadcast(
            "knowledge_changed",
            {
                "kind": "retrieval_index_failed",
                "library_id": library_id,
                "error": str(exc),
            },
        )
        return
    await state.events.broadcast(
        "knowledge_changed",
        {
            "kind": "retrieval_index_rebuilt",
            "library_id": library_id,
            "result": result,
        },
    )


@router.get("/status")
async def knowledge_status(token: Token) -> dict[str, Any]:
    return state.knowledge.status()


@router.get("/index/status")
async def knowledge_index_status(token: Token) -> dict[str, Any]:
    return state.knowledge.retrieval_status()


@router.post("/search")
async def knowledge_search(payload: KnowledgeSearchRequest, token: Token) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            state.knowledge.search,
            payload.query,
            library_ids=payload.library_ids or None,
            agent_id=payload.agent_id,
            mode=payload.mode,
            top_k=payload.top_k,
            candidate_k=payload.candidate_k,
            adaptive=payload.adaptive,
            build_context=payload.build_context,
            context_top_k=payload.context_top_k,
            context_token_budget=payload.context_token_budget,
            neighbor_window=payload.neighbor_window,
        )
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc


@router.post("/index/rebuild", status_code=status.HTTP_202_ACCEPTED)
async def rebuild_knowledge_index(
    payload: KnowledgeIndexRebuildRequest,
    background_tasks: BackgroundTasks,
    token: Token,
) -> dict[str, Any]:
    if payload.library_id is not None:
        try:
            state.knowledge.get_library(payload.library_id)
        except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
            raise _translate_error(exc) from exc
    background_tasks.add_task(_run_index_rebuild, payload.library_id)
    return {
        "accepted": True,
        "library_id": payload.library_id,
        "scope": "library" if payload.library_id is not None else "all",
    }


@router.get("/formats")
async def knowledge_formats(token: Token) -> dict[str, Any]:
    engine_status = state.knowledge.status()
    return {
        "formats": engine_status["supported_formats"],
        "ocr_available": bool(engine_status["capabilities"]["ocr"]),
        "vlm_enabled": False,
        "max_upload_bytes": engine_status["max_upload_bytes"],
    }


@router.get("/libraries")
async def list_libraries(token: Token) -> list[dict[str, Any]]:
    return state.knowledge.list_libraries()


@router.get("/libraries/{library_id}")
async def get_library(library_id: int, token: Token) -> dict[str, Any]:
    try:
        return state.knowledge.get_library(library_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc


@router.post("/libraries")
async def create_library(payload: KnowledgeLibraryCreate, token: Token) -> dict[str, Any]:
    try:
        item = state.knowledge.create_library(payload.model_dump())
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast("knowledge_changed", {"kind": "library_created", "library": item})
    return item


@router.put("/libraries/{library_id}")
async def update_library(
    library_id: int, payload: KnowledgeLibraryUpdate, token: Token
) -> dict[str, Any]:
    try:
        item = state.knowledge.update_library(library_id, payload.model_dump())
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast("knowledge_changed", {"kind": "library_updated", "library": item})
    return item


@router.delete("/libraries/{library_id}")
async def delete_library(library_id: int, token: Token) -> dict[str, bool]:
    try:
        state.knowledge.delete_library(library_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast("knowledge_changed", {"kind": "library_deleted", "library_id": library_id})
    return {"ok": True}


@router.get("/documents")
async def list_documents(
    token: Token, library_id: int | None = Query(default=None, ge=1)
) -> list[dict[str, Any]]:
    try:
        return state.knowledge.list_documents(library_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/libraries/{library_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    library_id: int,
    background_tasks: BackgroundTasks,
    token: Token,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> dict[str, Any]:
    filename = file.filename or "document"
    try:
        staged = state.knowledge.new_upload_path(filename)
    except KnowledgeEngineValidation as exc:
        raise _translate_error(exc) from exc
    written = 0
    try:
        with staged.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > state.knowledge.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Knowledge document exceeds the {state.knowledge.max_upload_bytes} byte upload limit",
                    )
                handle.write(chunk)
        document, job = state.knowledge.register_staged_upload(
            library_id=library_id,
            staged_path=staged,
            source_name=filename,
            mime_type=file.content_type,
            title=title,
        )
    except HTTPException:
        staged.unlink(missing_ok=True)
        raise
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        staged.unlink(missing_ok=True)
        raise _translate_error(exc) from exc
    finally:
        await file.close()

    background_tasks.add_task(_run_ingestion, int(document["id"]), int(job["id"]))
    await state.events.broadcast(
        "knowledge_changed",
        {"kind": "document_queued", "document": document, "job": job},
    )
    return {"document": document, "job": job}


@router.get("/documents/{document_id}")
async def get_document(document_id: int, token: Token) -> dict[str, Any]:
    try:
        return state.knowledge.get_document(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc


@router.get("/documents/{document_id}/content")
async def get_document_content(
    document_id: int,
    token: Token,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    try:
        content = state.knowledge.document_content(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    for key in ("parent_blocks", "chunks", "assets"):
        values = content[key]
        content[f"{key}_total"] = len(values)
        content[key] = values[:limit]
    return content


@router.post(
    "/documents/{document_id}/reingest",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reingest_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    token: Token,
) -> dict[str, Any]:
    try:
        job = state.knowledge.reingest_document(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    background_tasks.add_task(_run_ingestion, document_id, int(job["id"]))
    await state.events.broadcast(
        "knowledge_changed",
        {"kind": "document_reingest_queued", "document_id": document_id, "job": job},
    )
    return {"document_id": document_id, "job": job}


@router.post("/documents/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
async def reindex_document_retrieval(
    document_id: int,
    background_tasks: BackgroundTasks,
    token: Token,
) -> dict[str, Any]:
    try:
        document = state.knowledge.get_document(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc

    async def run_document_index() -> None:
        try:
            result = await asyncio.to_thread(state.knowledge.retrieval.index_document, document_id)
            await state.events.broadcast(
                "knowledge_changed",
                {"kind": "document_reindexed", "document_id": document_id, "result": result},
            )
        except Exception as exc:
            await state.events.broadcast(
                "knowledge_changed",
                {
                    "kind": "document_reindex_failed",
                    "document_id": document_id,
                    "error": str(exc),
                },
            )

    background_tasks.add_task(run_document_index)
    return {"accepted": True, "document_id": document_id, "library_id": document["library_id"]}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int, token: Token) -> dict[str, bool]:
    try:
        state.knowledge.delete_document(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    await state.events.broadcast(
        "knowledge_changed", {"kind": "document_deleted", "document_id": document_id}
    )
    return {"ok": True}


@router.get("/jobs")
async def list_jobs(
    token: Token, document_id: int | None = Query(default=None, ge=1)
) -> list[dict[str, Any]]:
    try:
        return state.knowledge.list_jobs(document_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc


@router.get("/agents/{agent_id}/libraries")
async def get_agent_libraries(agent_id: int, token: Token) -> dict[str, Any]:
    try:
        ids = state.knowledge.agent_library_ids(agent_id)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    return {"agent_id": agent_id, "library_ids": ids}


@router.put("/agents/{agent_id}/libraries")
async def set_agent_libraries(
    agent_id: int, payload: AgentKnowledgeLibrariesUpdate, token: Token
) -> dict[str, Any]:
    try:
        ids = state.knowledge.set_agent_libraries(agent_id, payload.library_ids)
    except (KnowledgeEngineNotFound, KnowledgeEngineConflict, KnowledgeEngineValidation) as exc:
        raise _translate_error(exc) from exc
    result = {"agent_id": agent_id, "library_ids": ids}
    await state.events.broadcast("knowledge_changed", {"kind": "agent_libraries_updated", **result})
    return result
