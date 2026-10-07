# 렌즈 보정값(front_calib.json · wrist_calib.json) 읽기 + 배캠 화면 점 → 바닥 위 거리
#   from calib_cam import load, floor_cm
#   floor_cm(x, y) → (앞으로 cm, 왼쪽 cm)  범퍼 기준
import json, os
import cv2
import numpy as np

D = os.path.dirname(os.path.abspath(__file__))

# 배캠 자세: 블록 30·50·70cm 실측표(2026-10-06, y 342·284·260)에 보정값을 넣고 맞춘 값(2026-10-07, 세 점 모두 0.1cm 안)
FRONT_H = 0.0765        # 렌즈 높이(m)
FRONT_PITCH = 4.86      # 아래로 숙인 각도(도)
LENS_AHEAD = 0.018      # 렌즈가 범퍼보다 앞에 있는 거리(m)


def load(cam):
    """cam = 'front' 또는 'wrist' → (K 3x3, 왜곡계수)"""
    c = json.load(open(os.path.join(D, f"{cam}_calib.json")))
    return np.array(c["K"], float), np.array(c["dist"], float)


_K, _DIST = load("front")


def floor_cm(x, y):
    """배캠 화면 (x, y) 가 바닥에 닿은 점이라 보고 범퍼 기준 (앞 cm, 왼쪽 cm). 수평선 위쪽이면 None."""
    xn, yn = cv2.undistortPoints(np.array([[[x, y]]], float), _K, _DIST).ravel()
    p = np.radians(FRONT_PITCH)
    down = yn * np.cos(p) + np.sin(p)            # 광선이 아래로 내려가는 정도
    if down <= 1e-6:
        return None
    fwd = np.cos(p) - yn * np.sin(p)
    t = FRONT_H / down
    return float(100 * (t * fwd + LENS_AHEAD)), float(-100 * t * xn)
