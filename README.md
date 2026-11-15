# ChatDB

내 텔레그램 계정 여러 개를 그룹에 넣어 두고, 그룹 대화에서 **키워드를 말한 사람**과 **활발하게 채팅하는 사람**의
@아이디를 받아 적는 1인용 콘솔입니다. 계정·그룹·수집 규칙·수집 결과를 웹에서 관리합니다.

듣고 받아 적기만 합니다. 누구에게도 메시지를 보내지 않습니다.

## 필요한 것

- Python 3.11 이상
- Node.js 20 이상 (화면을 한 번 빌드할 때, 그리고 pm2)
- 텔레그램 API 키 (`api_id`, `api_hash`) — https://my.telegram.org → API development tools

## 설치와 실행

```bash
pip install -r requirements.txt          # 가상환경 없이 설치
cd frontend && npm install && npm run build && cd ..
python run.py                            # http://127.0.0.1:8000
```

`pip install` 이 `pyaes` 빌드에서 멈추면 `pip install --use-pep517 -r requirements.txt` 로 설치하세요.

pm2 로 띄우기:

```bash
pm2 start ecosystem.config.js
pm2 logs chatdb
pm2 save && pm2 startup                  # 재부팅 뒤에도 자동으로 뜨게
```

> **프로세스는 반드시 하나만** 띄웁니다(`-i` 로 여러 개 띄우지 마세요). 같은 텔레그램 세션을 두 프로세스가
> 동시에 쓰면 텔레그램이 그 세션을 끊습니다.

## 처음 쓸 때

1. 브라우저로 접속해 관리자 비밀번호를 정합니다.
2. **설정**에서 텔레그램 API 키를 넣습니다.
3. **계정**에서 내 텔레그램 계정을 연결합니다(전화번호 로그인 또는 세션 문자열·`.session` 파일 불러오기).
4. **그룹**에서 링크를 붙여 넣습니다. 계정이 차례로 들어가고, 승인이 필요한 곳은 입장 요청을 보냅니다.
5. **수집 규칙**에서 키워드 규칙이나 활동량 규칙을 만듭니다.
6. **수집함**에 받아 적은 사람이 쌓입니다. @아이디 복사, CSV/TXT 내보내기를 할 수 있습니다.

텔레그램 없이 화면만 둘러보려면 `CHATDB_DEMO=true python run.py` 로 실행하세요(지어낸 데이터로 움직입니다).

## 설정

저장소 폴더의 `.env` 파일이나 `CHATDB_` 로 시작하는 환경 변수로 바꿉니다. `.env.example` 을 참고하세요.
데이터(SQLite DB, 암호화된 세션, 비밀 키)는 `data/` 폴더에 저장됩니다. 이 폴더를 백업하면 됩니다.

밖에서 접속하게 하려면 HTTPS 리버스 프록시 뒤에 두고 `CHATDB_COOKIE_SECURE=true` 로 설정하세요.

## 알아 둘 것

- 텔레그램은 자동화된 계정 사용과 데이터 수집을 약관으로 제한합니다. 계정이 제한되거나 정지될 수 있습니다.
- 동의 없이 모은 연락처를 영리 목적 광고에 쓰면 개인정보보호법·정보통신망법에 걸릴 수 있습니다.
- 텔레그램이 요청을 제한하면(FloodWait) 콘솔은 그 시간만큼 기다립니다. 이를 피해 가는 기능은 없습니다.

## 개발

```bash
pip install -r requirements-dev.txt
cd backend && python -m pytest -q        # 백엔드 테스트
cd frontend && npm run dev               # 화면 개발 서버 (백엔드는 8000 포트)
cd frontend && npm run typecheck && npm run lint && npm test
```

구조: `backend/app` (FastAPI + Telethon + SQLite), `frontend/src` (React + Vite), `run.py` (한 프로세스로 실행).
