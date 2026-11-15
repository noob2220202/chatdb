"""/settings 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_admin

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])
