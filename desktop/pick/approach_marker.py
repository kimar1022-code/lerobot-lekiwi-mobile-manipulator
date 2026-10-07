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
from calib_cam import load

# 배 카메라 렌즈 보정값(front_calib.json, 2026-10-07). 줄자 56cm ↔ 계산 57cm 로 확인.
# 예전 650 은 24% 컸다 → 거리 숫자들이 실제보다 1.24배로 나왔음. auto_pick 의 멈춤 거리는 같은 자리에 서도록 x0.807 로 바꿈.
K_FRONT, DIST_FRONT = load("front")
F_PX = float((K_FRONT[0, 0] + K_FRONT[1, 1]) / 2)
MARKER_M = 0.035      # 검은 사각형 한 변
_P = cv2.aruco.DetectorParameters()
# 멀리 있는 작은 마커(10px 안팎)도 읽도록: 작은 둘레 허용 + 작은 창 크기 + 모서리 보정
_P.minMarkerPerimeterRate = 0.01
_P.adaptiveThreshWinSizeMin = 3
_P.adaptiveThreshWinSizeStep = 4
_P.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
DET = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), _P)


BOX_IDS = {"A": (0, 1, 2, 3), "B": (4, 5, 6, 7)}   # 보관함마다 네 면에 붙인 마커 번호


def find_marker(img, ids=BOX_IDS["A"], upscale=True):
    """ids 중 아무 마커나 찾는다(보관함 네 면 어디든). 여러 개면 가장 크게 보이는 것."""
    ms = find_markers(img, ids, upscale)
    return max(ms, key=lambda m: m["side"]) if ms else None


def find_markers(img, ids=BOX_IDS["A"], upscale=True):
    """보이는 마커를 면마다 하나씩 전부 돌려준다(정면 맞추다 막히면 다른 면으로 바꾸려고)."""
    c, found, _ = DET.detectMarkers(img)
    if (found is None or not set(found.flatten()) & set(ids)) and upscale:
        # 2026-10-06: 2.3m 거리에서 마커가 약 10px 이라 못 읽었음 → 2배로 키워 다시 찾기
        big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        c, found, _ = DET.detectMarkers(big)
        if found is not None:
            c = [cc / 2.0 for cc in c]
    if (found is None or not set(found.flatten()) & set(ids)) and upscale:
        # 2026-10-06 저녁: 3m 에서 마커가 12px + 어두워 흐릿 → 3배로 키우고 선명하게 하면 읽힘
        big = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        big = cv2.addWeighted(big, 1.8, cv2.GaussianBlur(big, (0, 0), 3), -0.8, 0)
        c, found, _ = DET.detectMarkers(big)
        if found is not None:
            c = [cc / 3.0 for cc in c]
    if found is None:
        return []
    out = {}
    for cc, i in zip(c, found.flatten()):
        if i in ids:
            p = cc[0]
            side = float(np.mean([np.linalg.norm(p[k] - p[(k + 1) % 4]) for k in range(4)]))
            if int(i) not in out or side > out[int(i)]["side"]:
                out[int(i)] = dict(id=int(i), cx=float(p[:, 0].mean()), cy=float(p[:, 1].mean()), side=side,
                                   dist=F_PX * MARKER_M / side, yaw=marker_yaw(p, img.shape))
                out[int(i)]["t"], out[int(i)]["n"] = marker_pose(p, img.shape)
    return list(out.values())


def marker_pose(corners, shape):
    """마커 위치 t(카메라 기준 m: x 오른쪽 · y 아래 · z 앞)와 마커 면이 바라보는 방향 n(로봇 쪽을 향하게)."""
    s = MARKER_M / 2
    obj = np.array([[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]], float)
    ok, rv, tv = cv2.solvePnP(obj, corners.astype(float), K_FRONT, DIST_FRONT, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None, None
    n = cv2.Rodrigues(rv)[0][:, 2]
    if n[2] > 0:
        n = -n
    return tv.flatten(), n


def front_spot(m, dist):
    """마커 정면 dist(m) 지점이 로봇 기준 앞으로 몇 m · 왼쪽으로 몇 m 인지."""
    t, n = m.get("t"), m.get("n")
    if t is None:
        return None
    p = t + dist * n
    return float(p[2]), float(-p[0])


def marker_yaw(corners, shape):
    """마커가 얼마나 비스듬히 보이는지(도). 0 이면 정면.
    음수면 로봇이 마커 정면선보다 오른쪽에 있다 → 왼쪽(y+)으로 가면 줄어든다(2026-10-06 실측)."""
    s = MARKER_M / 2
    obj = np.array([[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]], float)
    ok, rv, tv = cv2.solvePnP(obj, corners.astype(float), K_FRONT, DIST_FRONT, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None
    n = cv2.Rodrigues(rv)[0][:, 2]
    return float(np.degrees(np.arctan2(n[0], -n[2])))


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
    d = float(sys.argv[1]) if len(sys.argv) > 1 else 0.24
    front = Cam("front")
    time.sleep(0.5)
    m0 = find_marker(front.get(timeout=3))
    print("출발 전:", m0 and {k: round(v, 3) for k, v in m0.items()})
    ok, info = approach(front, stop_dist=d)
    print("결과:", "도착" if ok else "중단", info if not ok else {k: round(v, 3) for k, v in info.items()})
