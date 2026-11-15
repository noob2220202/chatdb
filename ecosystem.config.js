// pm2 설정.
//   pm2 start ecosystem.config.js     시작
//   pm2 logs chatdb                   로그 보기
//   pm2 restart chatdb                다시 시작
//   pm2 save && pm2 startup           서버가 재부팅돼도 자동으로 뜨게 하기
//
// 파이썬 실행 파일이 python3 가 아니면 CHATDB_PYTHON 환경 변수로 바꾼다.
const python = process.env.CHATDB_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')

module.exports = {
  apps: [
    {
      name: 'chatdb',
      script: 'run.py',
      interpreter: python,
      cwd: __dirname,

      // 반드시 프로세스 하나로만 돌린다. 같은 텔레그램 세션을 두 프로세스가 동시에 쓰면
      // 텔레그램이 그 세션을 끊어 버린다(다시 로그인해야 한다).
      instances: 1,
      exec_mode: 'fork',
      watch: false,

      autorestart: true,
      restart_delay: 5000,
      max_restarts: 20,
      min_uptime: '30s',

      // 종료할 때 수집 버퍼를 저장하고 텔레그램 연결을 정리할 시간을 준다.
      kill_timeout: 20000,

      env: {
        PYTHONUNBUFFERED: '1',
      },
    },
  ],
}
