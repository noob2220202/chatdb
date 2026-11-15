#!/usr/bin/env python3
"""ChatDB 실행 파일.

    pip install -r requirements.txt
    python run.py

설정은 이 폴더의 .env 파일이나 CHATDB_ 로 시작하는 환경 변수로 바꾼다(.env.example 참고).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    if sys.version_info < (3, 11):
        sys.exit(f"파이썬 3.11 이상이 필요해요. 지금 버전은 {sys.version.split()[0]} 이에요.")

    # .env 와 data 폴더를 어디서 실행하든 이 폴더 기준으로 찾는다.
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("CHATDB_DATA_DIR", str(ROOT / "data"))

    dist = ROOT / "frontend" / "dist"
    if "CHATDB_STATIC_DIR" not in os.environ:
        if (dist / "index.html").exists():
            os.environ["CHATDB_STATIC_DIR"] = str(dist)
        else:
            print(
                "화면 파일(frontend/dist)이 아직 없어요. API 만 뜹니다.\n"
                "화면까지 쓰려면 한 번만 빌드해 주세요:  cd frontend && npm install && npm run build\n"
            )

    try:
        import uvicorn

        from app.config import get_config
    except ImportError as exc:
        sys.exit(
            f"필요한 패키지가 없어요 ({exc.name}).\n먼저 설치해 주세요:  pip install -r requirements.txt"
        )

    config = get_config()
    shown_host = "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
    print(f"ChatDB 를 시작해요  →  http://{shown_host}:{config.port}\n")
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
