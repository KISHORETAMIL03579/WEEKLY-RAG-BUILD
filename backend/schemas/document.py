# backend/schemas/document.py — Pydantic Schemas for Document Ingestion & Storage Management
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict


class _LenientModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class UploadCancelPayload(_LenientModel):
    upload_id: Optional[str] = None


UploadCancelRequest = UploadCancelPayload


class UrlPayload(_LenientModel):
    url: Optional[str] = None
    chunk_mode: Optional[str] = None


LoadUrlRequest = UrlPayload


class RemovePayload(_LenientModel):
    doc_id: Optional[str] = None


RemoveRequest = RemovePayload


class OkResponse(BaseModel):
    ok: bool = True


class RemoveResponse(BaseModel):
    ok: bool = True
    removed_chunks: int = 0
    warning: Optional[str] = None

