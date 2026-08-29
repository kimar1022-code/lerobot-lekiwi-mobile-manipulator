#!/bin/bash
# LeKiwi 호스트 데몬 실행 - 데스크탑에서 조종하기 전에 Pi에서 이걸 먼저 켭니다.
#
# 사용법:
#   ~/lekiwi_tools/run_host.sh          앞에서 실행 (화면에 로그가 보임)
#   ~/lekiwi_tools/run_host.sh -b       뒤에서 실행 (SSH 끊어도 유지)
#   ~/lekiwi_tools/run_host.sh -s       상태 확인
#   ~/lekiwi_tools/run_host.sh -k       중지
#
# 환경변수: ROBOT_ID(기본 my_lekiwi), CONN_TIME(기본 3600초)
set -e
cd ~/lerobot

ROBOT_ID="${ROBOT_ID:-my_lekiwi}"
CONN_TIME="${CONN_TIME:-28800}"   # 기본값 30초면 금방 끊겨서 길게 잡음
LOG=~/lekiwi_host.log

case "${1:-}" in
  -s|--status)
    if pgrep -f lekiwi_host > /dev/null; then
      echo "돌고 있음 (PID $(pgrep -f lekiwi_host | tr '\n' ' '))"
      echo "--- 로그 마지막 10줄 ---"; tail -10 "$LOG" 2>/dev/null
    else
      echo "안 돌고 있음"
    fi
    exit 0 ;;
  -k|--kill)
    pkill -f lekiwi_host && echo "중지함" || echo "돌고 있지 않았음"
    exit 0 ;;
esac

pkill -f lekiwi_host 2>/dev/null || true
sleep 1

CMD=(./.venv/bin/python -m lerobot.robots.lekiwi.lekiwi_host
     --robot.id="$ROBOT_ID" --host.connection_time_s="$CONN_TIME")

if [ "${1:-}" = "-b" ] || [ "${1:-}" = "--background" ]; then
  setsid nohup "${CMD[@]}" > "$LOG" 2>&1 < /dev/null &
  sleep 6
  if pgrep -f lekiwi_host > /dev/null; then
    echo "백그라운드로 시작됨 (연결시간 ${CONN_TIME}초)"
    echo "로그: tail -f $LOG"
    tail -8 "$LOG" 2>/dev/null
  else
    echo "! 시작 실패. 로그:"; tail -20 "$LOG" 2>/dev/null
    exit 1
  fi
  exit 0
fi

echo "=============================================="
echo " LeKiwi 호스트 시작"
echo "  로봇 이름 : $ROBOT_ID"
echo "  Pi 주소   : $(hostname -I | awk '{print \$1}')"
echo "  포트      : 5555(명령) / 5556(영상)"
echo "  연결시간  : ${CONN_TIME}초"
echo "=============================================="
echo ""
echo "데스크탑에서:  cd ~/lerobot && python my_lekiwi_teleop.py"
echo ""
exec "${CMD[@]}"
