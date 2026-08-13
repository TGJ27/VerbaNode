from __future__ import annotations

from fastapi import HTTPException, UploadFile


async def read_upload_limited(
    file: UploadFile,
    *,
    max_bytes: int,
    too_large_message: str,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    """Read an upload incrementally and stop before an oversized body fills RAM."""
    limit = max(1, int(max_bytes))
    chunk_size = max(4096, min(int(chunk_size), limit))
    payload = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        if len(payload) + len(chunk) > limit:
            raise HTTPException(status_code=413, detail=too_large_message)
        payload.extend(chunk)
    return bytes(payload)


__all__ = ["read_upload_limited"]
