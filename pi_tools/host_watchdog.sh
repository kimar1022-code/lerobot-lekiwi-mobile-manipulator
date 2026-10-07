#!/bin/bash
# LeKiwi 호스트 감시 루프 - run_host.sh -b 가 띄운다. 직접 실행할 일은 없음.
# 호스트가 어떤 이유로든 끝나면(모터 통신 오류로 죽음, 연결시간 만료) 다시 켠다.
#  - 로그는 이어 쓴다 → 죽기 직전 오류를 나중에 볼 수 있게
#  - 10초 안에 또 죽으면(포트 점유 등) 10초 쉬어서 헛돌지 않게
#  - 재시작 기록은 ~/lekiwi_restarts.log
cd ~/lerobot
LOG=~/lekiwi_host.log
RLOG=~/lekiwi_restarts.log
while true; do
  start=$(date +%s)
  "$@" >> "$LOG" 2>&1 < /dev/null
  code=$?
  why=$(grep -E "Error" "$LOG" | tail -1 | cut -c1-160)
  echo "$(date "+%F %T") 호스트 종료(코드 $code) → 재시작 | $why" >> "$RLOG"
  if [ $(( $(date +%s) - start )) -lt 10 ]; then sleep 10; else sleep 2; fi
  # 로그가 20MB 넘으면 뒤쪽만 남김
  if [ "$(stat -c %s "$LOG")" -gt 20000000 ]; then tail -2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi
done
