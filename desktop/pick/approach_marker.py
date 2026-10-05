"""배 카메라로 보관함 ArUco 마커를 보며 다가가 정해진 거리에서 멈춘다.

거리 = 초점거리 * 마커실제크기 / 화면 속 마커 한 변(px)
방향: 마커가 화면 오른쪽이면 오른쪽(theta 음수)으로 돈다.
안전: 마커를 1초 넘게 놓치거나 제한시간을 넘으면 즉시 정지.
"""
import sys
import time
import cv2
import numpy as np
from robot_api import Cam, drive, stop

F_PX = 650.0          # 배 카메라 초점거리(2026-10-05 실측)
MARKER_M = 0.035      # 검은 사각형 한 변
DET = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))


def find_marker(img, mid=0):
    c, ids, _ = DET.detectMarkers(img)
    if ids is None:
        return None
    for cc, i in zip(c, ids.flatten()):
        if i == mid:
            p = cc[0]
            side = float(np.mean([np.linalg.norm(p[k] - p[(k + 1) % 4]) for k in range(4)]))
            return dict(cx=float(p[:, 0].mean()), cy=float(p[:, 1].mean()), side=side,
                        dist=F_PX * MARKER_M / side)
    return None


def approach(front, stop_dist=0.30, v=0.05, k_turn=0.08, max_turn=15, timeout=25):
    t0, last_seen, m = time.time(), time.time(), None
    t = time.time()
    while True:
        img = front.get(newer_than=t); t = time.time()
        m = find_marker(img)
        if m:
            last_seen = t
            err = m["cx"] - img.shape[1] / 2
            th = float(np.clip(-k_turn * err, -max_turn, max_turn))
            if m["dist"] <= stop_dist:
                stop(); return True, m
            # 방향이 많이 틀어졌으면 제자리에서 먼저 돌고, 맞으면 전진
            x = v if abs(err) < 60 else 0.0
            drive(x=x, theta=th)
        if t - last_seen > 1.0:
            stop(); return False, "마커를 1초 넘게 놓침"
        if t - t0 > timeout:
            stop(); return False, "제한시간 초과"


if __name__ == "__main__":
    d = float(sys.argv[1]) if len(sys.argv) > 1 else 0.30
    front = Cam("front")
    time.sleep(0.5)
    m0 = find_marker(front.get(timeout=3))
    print("출발 전:", m0 and {k: round(v, 3) for k, v in m0.items()})
    ok, info = approach(front, stop_dist=d)
    print("결과:", "도착" if ok else "중단", info if not ok else {k: round(v, 3) for k, v in info.items()})
