from __future__ import annotations

from typing import Any

from app.api.protocol import API_VERSION, MIN_API_VERSION, PROTOCOL_VERSION
from app.config import get_settings
from app.migrations import CURRENT_SCHEMA_VERSION
from app.services.backup import BACKUP_FORMAT_VERSION
from app.services.https_cert import certificate_fingerprint_sha256, certificate_spki_sha256
from app.version import APP_VERSION, BUILD_LABEL

CLIENT_INFO_VERSION = 1
SESSION_HEADER = "X-Session-Token"
CONTROLLER_POLICY = "single_active_controller"


def feature_manifest() -> dict[str, Any]:
    """Stable feature flags that web and future mobile clients can negotiate."""
    return {
        "api_version": API_VERSION,
        "websocket_protocol_version": PROTOCOL_VERSION,
        "client_info_version": CLIENT_INFO_VERSION,
        "diagnostics": True,
        "diagnostics_api_version": 1,
        "plugin_manager": True,
        "plugin_manager_api_version": 2,
        "external_plugins": True,
        "persistent_action_ledger": True,
        "action_ledger_schema_version": 3,
        "database_schema_version": CURRENT_SCHEMA_VERSION,
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "migration_history": True,
        "recovery_snapshots": True,
        "capability_provider_framework": True,
        "capability_provider_api_version": 1,
        "capability_action_expiry": True,
        "capability_cancellation": True,
        "client_metadata": True,
        "modular_web_client": True,
        "websocket_heartbeat": True,
        "same_origin_websocket_guard": True,
        "security_headers": True,
        "bounded_uploads": True,
        "mobile_pairing": True,
        "trusted_devices": True,
        "device_revocation": True,
        "lan_discovery": True,
        "mdns_service_type": "_verbanode._tcp.local.",
        "audio_library": True,
        "audio_library_formats": ["mp3", "mpeg", "mpg", "mpga", "mp2", "mpa", "wav", "flac", "ogg", "oga", "opus", "m4a", "aac", "wma", "aiff", "aif", "webm", "mka", "amr"],
        "configuration_options": True,
        "script_queue_loop": True,
        "script_queue_pause": True,
        "script_queue_drag_reorder": True,
        "stable_instance_identity": True,
        "type_to_talk_queue": True,
        "script_defaults": True,
        "broad_audio_formats": True,
        "knowledge_engine": True,
        "knowledge_engine_phase": "chat_voice_cutover",
        "knowledge_libraries": True,
        "knowledge_agent_permissions": True,
        "knowledge_ingestion": True,
        "knowledge_ingestion_api_version": 1,
        "knowledge_ocr": True,
        "knowledge_tables": True,
        "knowledge_vlm": False,
        "knowledge_retrieval": True,
        "knowledge_retrieval_api_version": 2,
        "knowledge_bm25": True,
        "knowledge_dense_embeddings": True,
        "knowledge_hnsw": True,
        "knowledge_rrf": True,
        "knowledge_structured_table_search": True,
        "knowledge_query_routing": True,
        "knowledge_reranking": True,
        "knowledge_confidence_fallback": True,
        "knowledge_context_builder": True,
        "knowledge_deduplication": True,
        "knowledge_chat_integration": True,
        "knowledge_voice_integration": True,
        "knowledge_legacy_information_injection": False,
        "knowledge_prompt_integration_api_version": 1,
    }


def client_info_payload(*, instance_id: str | None = None, instance_name: str | None = None) -> dict[str, Any]:
    """Public, non-secret contract used before a client authenticates."""
    settings = get_settings()
    return {
        "contract_version": CLIENT_INFO_VERSION,
        "product": "VerbaNode",
        "server": {
            "version": APP_VERSION,
            "build": BUILD_LABEL,
        },
        "instance": {
            "id": instance_id,
            "name": instance_name or "VerbaNode",
        },
        "api": {
            "version": API_VERSION,
            "minimum_supported_version": MIN_API_VERSION,
            "base_path": "/api",
            "request_id_header": "X-Request-ID",
        },
        "authentication": {
            "mode": "pin_or_trusted_device",
            "login_endpoint": "/api/auth/login",
            "device_login_endpoint": "/api/auth/device-login",
            "logout_endpoint": "/api/auth/logout",
            "session_header": SESSION_HEADER,
            "controller_policy": CONTROLLER_POLICY,
            "pairing_claim_endpoint": "/api/pairing/claim",
            "idle_timeout_seconds": int(settings.controller_timeout_seconds),
        },
        "tls": {
            "required": True,
            "certificate_fingerprint_sha256": certificate_fingerprint_sha256(),
            "certificate_spki_sha256": certificate_spki_sha256(),
            "local_ca_endpoint": "/verbanode-local-ca.crt",
        },
        "discovery": {
            "service_type": "_verbanode._tcp.local.",
            "enabled": bool(settings.lan_discovery_enabled),
        },
        "websocket": {
            "endpoint": "/ws",
            "protocol_version": PROTOCOL_VERSION,
            "ticket_endpoint": "/api/auth/ws-ticket",
            "ticket_required": True,
            "heartbeat_interval_seconds": float(settings.websocket_heartbeat_interval_seconds),
            "heartbeat_timeout_seconds": float(settings.websocket_heartbeat_timeout_seconds),
            "same_origin_browser_required": True,
            "originless_native_clients_allowed": True,
        },
        "endpoints": {
            "bootstrap": "/api/bootstrap",
            "status": "/api/status",
            "heartbeat": "/api/heartbeat",
            "session": "/api/session",
            "devices": "/api/devices",
            "knowledge_status": "/api/knowledge/status",
            "knowledge_libraries": "/api/knowledge/libraries",
            "knowledge_search": "/api/knowledge/search",
            "knowledge_index_status": "/api/knowledge/index/status",
            "pairing_start": "/api/devices/pairing/start",
            "pairing_claim": "/api/pairing/claim",
        },
        "features": feature_manifest(),
    }


__all__ = [
    "CLIENT_INFO_VERSION",
    "CONTROLLER_POLICY",
    "SESSION_HEADER",
    "client_info_payload",
    "feature_manifest",
]
