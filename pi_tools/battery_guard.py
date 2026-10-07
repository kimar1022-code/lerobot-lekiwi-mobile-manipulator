#!/usr/bin/env python3
"""Pi 배터리(X1200 UPS) 저전압 자동 종료.

2026-10-06 배터리가 바닥나 Pi 가 종료 과정 없이 꺼졌다(SD 카드 손상 위험).
충전기가 빠져 있고 전압이 LOW_V 아래로 3번 연속 내려가면, 로봇 호스트를 먼저 멈추고 Pi 를 안전하게 끈다.
상태는 ~/lekiwi_power.json 에 남긴다(데스크탑 상태줄·웹 화면이 읽음).
부팅할 때 crontab @reboot 로 자동 실행된다.
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.expanduser("~/lekiwi_tools"))
LOW_V, WARN_V, CHECK_S, NEED = 3.40, 3.55, 30, 3
STATE = os.path.expanduser("~/lekiwi_power.json")


def log(msg):
    print(time.strftime("%F %T"), msg, flush=True)


def read():
    out = subprocess.run([sys.executable, os.path.expanduser("~/lekiwi_tools/read_ups.py")],
                         capture_output=True, text=True, timeout=10).stdout.split()
    return float(out[0]), float(out[1]), out[2] if len(out) > 2 else "?"


low = 0
log("저전압 감시 시작")
while True:
    try:
        pct, volt, ac = read()
        json.dump(dict(pct=pct, volt=volt, ac=ac, ts=time.time()), open(STATE + ".tmp", "w"))
        os.replace(STATE + ".tmp", STATE)
        if ac == "BAT" and volt < LOW_V:
            low += 1
            log(f"저전압 {volt:.2f}V ({low}/{NEED})")
            if low >= NEED:
                log("배터리 바닥 - 로봇 호스트를 멈추고 Pi 를 끕니다")
                subprocess.run([os.path.expanduser("~/lekiwi_tools/run_host.sh"), "-k"], timeout=20)
                subprocess.run(["sync"])
                subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "poweroff"])
                break
        else:
            if low:
                log(f"전압 회복 {volt:.2f}V ({ac})")
            low = 0
            if ac == "BAT" and volt < WARN_V:
                log(f"경고: 배터리 낮음 {volt:.2f}V - 곧 꺼질 수 있음")
    except Exception as e:
        log(f"읽기 실패: {e}")
    time.sleep(CHECK_S)
