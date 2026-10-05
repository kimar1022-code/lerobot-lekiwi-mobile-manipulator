"""웹 서버(lekiwi_web.py, 포트 8080)를 거쳐 LeKiwi 를 움직이는 얇은 도구.

웹 서버가 로봇 연결을 쥐고 있으므로 자동 동작도 HTTP 로 명령한다.
→ 자동 동작 중에도 브라우저 화면으로 카메라를 계속 볼 수 있다.
"""
import threading
import time

import cv2
import numpy as np
import requests

BASE = "http://localhost:8080"


class Cam:
    """MJPEG 스트림을 뒤에서 계속 읽어 '가장 최근 프레임'만 들고 있는다.
    (버퍼에 쌓인 옛 프레임을 최신으로 착각하는 문제 방지)"""

    def __init__(self, name):
        self.name, self.frame, self.stamp = name, None, 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                r = requests.get(f"{BASE}/stream/{self.name}", stream=True, timeout=5)
                buf = b""
                for chunk in r.iter_content(4096):
                    buf += chunk
                    e = buf.rfind(b"\xff\xd9")
                    if e < 0:
                        continue
                    s = buf.rfind(b"\xff\xd8", 0, e)
                    if s >= 0:
                        img = cv2.imdecode(np.frombuffer(buf[s:e + 2], np.uint8), 1)
                        if img is not None:
                            self.frame, self.stamp = img, time.time()
                    buf = buf[e + 2:]
            except Exception:
                time.sleep(0.5)

    def get(self, newer_than=None, timeout=2.0):
        """newer_than(시각) 이후에 들어온 프레임을 기다려 돌려준다."""
        t0 = time.time()
        newer_than = time.time() if newer_than is None else newer_than
        while time.time() - t0 < timeout:
            if self.frame is not None and self.stamp > newer_than:
                return self.frame.copy()
            time.sleep(0.01)
        raise TimeoutError(f"{self.name} 카메라 새 프레임 없음")


def drive(x=0.0, y=0.0, theta=0.0):
    """한 번 보내면 0.6초 동안만 유효(웹 서버 안전장치). 계속 움직이려면 반복 호출."""
    requests.post(f"{BASE}/api/drive", json={"x": x, "y": y, "theta": theta}, timeout=1)


def drive_for(x=0.0, y=0.0, theta=0.0, sec=1.0, hz=10):
    end = time.time() + sec
    while time.time() < end:
        drive(x, y, theta)
        time.sleep(1.0 / hz)
    stop()


def stop():
    for _ in range(3):
        drive(0, 0, 0)
        time.sleep(0.03)


def state():
    return requests.get(f"{BASE}/api/state", timeout=2).json()


def arm_mode(mode):
    return requests.post(f"{BASE}/api/arm", json={"mode": mode}, timeout=2).json()


def arm_target(joints):
    """joints: {"arm_shoulder_pan.pos": 값, ...} — manual 모드에서만 반영."""
    return requests.post(f"{BASE}/api/arm", json={"joints": joints}, timeout=2).json()


def arm_now():
    return {k: v for k, v in state()["arm_current"].items() if k.endswith(".pos")}


def move_to(pose, sec=2.5, hz=30, keys=None):
    """현재 자세에서 pose 까지 sec 초 동안 부드럽게(코사인 보간) 옮긴다.
    manual 모드로 바꾼 뒤 호출. keys 를 주면 그 관절만 움직인다."""
    import math
    start = arm_now()
    keys = keys or [k for k in pose if k in start]
    n = max(1, int(sec * hz))
    for i in range(1, n + 1):
        a = 0.5 - 0.5 * math.cos(math.pi * i / n)
        arm_target({k: start[k] + (pose[k] - start[k]) * a for k in keys})
        time.sleep(1.0 / hz)
