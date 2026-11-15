"""/blocklist 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_admin

router = APIRouter(prefix="/blocklist", tags=["blocklist"], dependencies=[Depends(require_admin)])
