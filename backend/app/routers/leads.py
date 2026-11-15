"""/leads 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_admin

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(require_admin)])
