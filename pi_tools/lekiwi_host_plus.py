#!/usr/bin/env python3
"""LeKiwi 호스트 + 모터 배터리 전압 기록.

로봇 호스트가 도는 동안 다른 프로그램이 모터 포트를 열면 패킷이 섞여 호스트가 죽는다
(2026-10-05 "Port is in use" 3회). 그래서 상태줄 · 웹 화면은 호스트가 돌 때 모터 배터리를 못 읽었다.
→ 호스트 자신이 10초에 한 번, 자기 반복 안에서 전압을 읽어 ~/lekiwi_motor_v.txt 에 남긴다.
   (read_batt.py 는 호스트가 돌면 포트 대신 이 파일을 읽는다)

lerobot 라이브러리 파일은 고치지 않고, get_observation 만 감싸서 쓴다.
사용법은 원래와 같다:  python lekiwi_host_plus.py --robot.id=my_lekiwi --host.connection_time_s=...
"""
import os
import time

from lerobot.robots.lekiwi import lekiwi_host
from lerobot.robots.lekiwi.lekiwi import LeKiwi

OUT = os.path.expanduser("~/lekiwi_motor_v.txt")
EVERY = 10.0
_orig = LeKiwi.get_observation


def get_observation_with_battery(self):
    obs = _orig(self)
    now = time.time()
    if now - getattr(self, "_batt_t", 0.0) >= EVERY:
        self._batt_t = now
        for motor in ("arm_shoulder_pan", "arm_shoulder_lift", "arm_elbow_flex"):
            try:
                v = self.bus.read("Present_Voltage", motor, normalize=False)
                if 50 < v < 200:              # 0.1V 단위 → 5~20V 만 정상 값으로 본다
                    with open(OUT + ".tmp", "w") as f:
                        f.write(f"{v / 10:.1f} {now:.0f}")
                    os.replace(OUT + ".tmp", OUT)
                    break
            except Exception:
                continue
    return obs


LeKiwi.get_observation = get_observation_with_battery

if __name__ == "__main__":
    lekiwi_host.main()
