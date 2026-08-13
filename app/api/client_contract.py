from __future__ import annotations

from typing import Any

from app.api.protocol import API_VERSION, MIN_API_VERSION, PROTOCOL_VERSION
from app.migrations import CURRENT_SCHEMA_VERSION
from app.services.backup import BACKUP_FORMAT_VERSION
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
        # Explicitly deferred until the dedicated mobile phase.
        "mobile_pairing": False,
        "lan_discovery": False,
    }


def client_info_payload() -> dict[str, Any]:
    """Public, non-secret contract used before a client authenticates."""
    return {
        "contract_version": CLIENT_INFO_VERSION,
        "product": "VerbaNode",
        "server": {
            "version": APP_VERSION,
            "build": BUILD_LABEL,
        },
        "api": {
            "version": API_VERSION,
            "minimum_supported_version": MIN_API_VERSION,
            "base_path": "/api",
            "request_id_header": "X-Request-ID",
        },
        "authentication": {
            "mode": "pin_session",
            "login_endpoint": "/api/auth/login",
            "logout_endpoint": "/api/auth/logout",
            "session_header": SESSION_HEADER,
            "controller_policy": CONTROLLER_POLICY,
        },
        "websocket": {
            "endpoint": "/ws",
            "protocol_version": PROTOCOL_VERSION,
            "ticket_endpoint": "/api/auth/ws-ticket",
            "ticket_required": True,
        },
        "endpoints": {
            "bootstrap": "/api/bootstrap",
            "status": "/api/status",
            "heartbeat": "/api/heartbeat",
            "session": "/api/session",
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
