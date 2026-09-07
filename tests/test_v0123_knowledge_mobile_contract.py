from __future__ import annotations

from app.api.client_contract import mobile_contract_manifest
from app.schemas import AgentKnowledgeLibrariesUpdate


def test_mobile_contract_exposes_knowledge_phase2_operations() -> None:
    manifest = mobile_contract_manifest()
    endpoints = manifest["endpoints"]
    assert endpoints["knowledge_document_reingest"] == {
        "method": "POST",
        "path": "/api/knowledge/documents/{document_id}/reingest",
    }
    assert endpoints["knowledge_jobs"] == {
        "method": "GET",
        "path": "/api/knowledge/jobs",
    }
    assert endpoints["knowledge_agent_libraries_get"] == {
        "method": "GET",
        "path": "/api/knowledge/agents/{agent_id}/libraries",
    }
    assert endpoints["knowledge_agent_libraries_set"] == {
        "method": "PUT",
        "path": "/api/knowledge/agents/{agent_id}/libraries",
    }


def test_mobile_contract_declares_agent_library_assignment_fields() -> None:
    fields = mobile_contract_manifest()["request_fields"]
    assert fields["knowledge_agent_libraries_set"] == list(AgentKnowledgeLibrariesUpdate.model_fields)
