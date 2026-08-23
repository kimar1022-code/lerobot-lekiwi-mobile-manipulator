#!/bin/bash
# LeKiwi 호스트 데몬 실행 - 데스크탑에서 조종하기 전에 Pi에서 이걸 먼저 켭니다.
# 기본 실행시간 30초라, 오래 쓰려면 --host.connection_time_s 크게. SSH 끊겨도 유지하려면 setsid nohup 권장.
set -e
cd ~/lerobot
source .venv/bin/activate
ROBOT_ID="${ROBOT_ID:-my_lekiwi}"
echo "=============================================="
echo " LeKiwi 호스트 시작 (로봇: $ROBOT_ID)"
echo "  Pi 주소 : $(hostname -I | awk '{print $1}')  포트: 5555/5556"
echo "=============================================="
exec python -m lerobot.robots.lekiwi.lekiwi_host --robot.id="$ROBOT_ID" --host.connection_time_s="${CONN_TIME:-3600}"
