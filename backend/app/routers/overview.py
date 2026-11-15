"""/overview 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_admin

router = APIRouter(prefix="/overview", tags=["overview"], dependencies=[Depends(require_admin)])
