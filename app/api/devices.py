from __future__ import annotations

import io
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.api.deps import Token
from app.schemas import DeviceRenameRequest, PairingClaimRequest, PairingStartRequest
from app.services.devices import PairingError, PairingRateLimited
from app.services.https_cert import certificate_fingerprint_sha256, certificate_spki_sha256, discover_ipv4_addresses
from app.state import state

router = APIRouter(tags=["devices", "pairing"])


def _default_server_url(request: Request) -> str:
    addresses = [value for _interface, value in discover_ipv4_addresses()]
    if addresses:
        return f"https://{addresses[0]}:{state.settings.port}"
    return str(request.base_url).rstrip("/")


def _validate_server_url(value: str | None, request: Request) -> str:
    candidate = (value or "").strip() or _default_server_url(request)
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Pairing server URL must be an HTTPS URL")
    return candidate.rstrip("/")


@router.get("/api/devices")
async def list_devices(token: Token) -> dict[str, Any]:
    active = state.controller.active_info() or {}
    active_device_id = active.get("device_id")
    devices = state.devices.list_devices()
    for device in devices:
        device["active_controller"] = device.get("device_id") == active_device_id
    return {"devices": devices, "controller_policy": "single_active_controller"}


@router.post("/api/devices/pairing/start")
async def start_pairing(payload: PairingStartRequest, request: Request, token: Token) -> dict[str, Any]:
    fingerprint = certificate_fingerprint_sha256()
    spki = certificate_spki_sha256()
    if not fingerprint or not spki:
        raise HTTPException(status_code=503, detail="Local HTTPS certificate is unavailable")
    result = state.devices.create_pairing(
        server_url=_validate_server_url(payload.preferred_server_url, request),
        certificate_fingerprint_sha256=fingerprint,
        certificate_spki_sha256=spki,
    )
    result["qr_endpoint"] = f"/api/devices/pairing/{result['pairing_id']}/qr"
    return result


@router.get("/api/devices/pairing/{pairing_id}")
async def pairing_status(pairing_id: str, token: Token) -> dict[str, Any]:
    status = state.devices.pairing_status(pairing_id)
    if not status:
        raise HTTPException(status_code=404, detail="Pairing request not found or expired")
    return status


@router.get("/api/devices/pairing/{pairing_id}/qr")
async def pairing_qr(pairing_id: str, token: Token) -> Response:
    pairing_uri = state.devices.pairing_uri(pairing_id)
    if not pairing_uri:
        raise HTTPException(status_code=404, detail="Pairing request not found, claimed, or expired")
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="QR support is not installed") from exc
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=3, box_size=8)
    qr.add_data(pairing_uri)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    return Response(stream.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.delete("/api/devices/pairing/{pairing_id}")
async def cancel_pairing(pairing_id: str, token: Token) -> dict[str, bool]:
    return {"cancelled": state.devices.cancel_pairing(pairing_id)}


@router.post("/api/pairing/claim")
async def claim_pairing(payload: PairingClaimRequest, request: Request) -> dict[str, Any]:
    client_key = request.client.host if request.client else "unknown"
    try:
        result = state.devices.claim_pairing(
            client_key=client_key,
            pairing_id=payload.pairing_id,
            secret=payload.secret,
            short_code=payload.short_code,
            device_name=payload.device_name,
            device_type=payload.device_type,
            device_version=payload.device_version,
            platform=payload.platform,
        )
    except PairingRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except PairingError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return result


@router.patch("/api/devices/{device_id}")
async def rename_device(device_id: str, payload: DeviceRenameRequest, token: Token) -> dict[str, Any]:
    device = state.devices.rename_device(device_id, payload.name)
    if not device:
        raise HTTPException(status_code=404, detail="Trusted device not found")
    return device


@router.post("/api/devices/{device_id}/revoke")
async def revoke_device(device_id: str, token: Token) -> dict[str, bool]:
    active = state.controller.active_info() or {}
    active_token = state.controller.active_token() if active.get("device_id") == device_id else None
    changed = state.devices.revoke_device(device_id)
    if changed and active_token:
        state.controller.logout(active_token)
        await state.events.send(active_token, "control_revoked", {"reason": "device_revoked"})
        await state.events.disconnect(active_token)
    return {"revoked": changed}


@router.delete("/api/devices/{device_id}")
async def delete_device(device_id: str, token: Token) -> dict[str, bool]:
    active = state.controller.active_info() or {}
    if active.get("device_id") == device_id:
        raise HTTPException(status_code=409, detail="Revoke the active device before deleting it")
    return {"deleted": state.devices.delete_device(device_id)}


@router.get("/api/discovery/status")
async def discovery_status(token: Token) -> dict[str, Any]:
    return state.discovery.status()
