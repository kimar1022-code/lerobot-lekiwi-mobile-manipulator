"""바퀴 방향 시험: 아주 느리게 1초씩 움직이며 배 카메라의 ArUco 마커 변화로 방향을 판정."""
import time
import cv2
import numpy as np
from robot_api import Cam, drive_for, stop, state

det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
front = Cam("front")


def marker(n=5):
    xs, ss = [], []
    t = time.time()
    for _ in range(n):
        f = front.get(newer_than=t); t = time.time()
        c, ids, _ = det.detectMarkers(f)
        if ids is not None:
            p = c[0][0]; xs.append(p[:, 0].mean())
            ss.append(np.mean([np.linalg.norm(p[k] - p[(k + 1) % 4]) for k in range(4)]))
    return (np.median(xs), np.median(ss)) if xs else (None, None)


assert state()["connected"], "로봇 연결 안 됨"
tests = [("앞으로 x=+0.05", dict(x=0.05)), ("뒤로 x=-0.05", dict(x=-0.05)),
         ("회전 theta=+15", dict(theta=15)), ("회전 theta=-15", dict(theta=-15)),
         ("옆 y=+0.05", dict(y=0.05)), ("옆 y=-0.05", dict(y=-0.05))]
# 2026-10-05 결과: x+ = 배 카메라 쪽 전진(마커 커짐) / theta+ = 왼쪽(반시계) 회전(마커가 화면 오른쪽으로)
#                  y+ = 왼쪽 이동(마커가 화면 오른쪽으로). 배 카메라 초점거리 ≈ 650px(640x480)
time.sleep(1.0)
for name, cmd in tests:
    x0, s0 = marker()
    drive_for(sec=1.0, **cmd)
    time.sleep(0.6)
    x1, s1 = marker()
    if x0 is None or x1 is None:
        print(f"{name}: 마커를 못 봄 (전 {x0}, 후 {x1})")
    else:
        print(f"{name}: 마커 x {x0:.0f}→{x1:.0f} ({x1-x0:+.0f}px), 크기 {s0:.1f}→{s1:.1f} ({s1-s0:+.1f}px)")
stop()
