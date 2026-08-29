#!/usr/bin/env bash
# LeKiwi 조종 화면을 한 번에 띄운다.
#   1) 웹서버가 안 떠 있으면 실행
#   2) 브라우저로 화면 열기
# 로봇/리더팔 연결은 화면의 「▶ 전체 시작」 버튼이 알아서 한다.
#
# 사용법:  ~/lerobot/start_lekiwi.sh

cd "$(dirname "$0")" || exit 1
PORT=8080
URL="http://localhost:$PORT"

echo "=== LeKiwi 조종 시작 ==="

# 이미 떠 있나
if curl -s -m 2 "$URL/api/state" >/dev/null 2>&1; then
  echo "  웹서버 이미 실행 중"
else
  echo "  웹서버 시작..."
  setsid nohup ./.venv/bin/python lekiwi_web.py > /tmp/lekiwi_web.log 2>&1 < /dev/null &
  for i in $(seq 1 30); do
    sleep 1
    curl -s -m 2 "$URL/api/state" >/dev/null 2>&1 && break
  done
  if curl -s -m 2 "$URL/api/state" >/dev/null 2>&1; then
    echo "  웹서버 준비됨"
  else
    echo "  ! 웹서버가 안 떴어. 로그: tail /tmp/lekiwi_web.log"
    exit 1
  fi
fi

echo "  브라우저 여는 중: $URL"
(xdg-open "$URL" >/dev/null 2>&1 &) || echo "  브라우저를 직접 열어줘: $URL"

echo
echo "화면에서 「▶ 전체 시작」을 누르면"
echo "  Pi 데몬 확인/시작 -> 로봇 연결 -> 리더팔 연결 까지 자동으로 진행돼."
