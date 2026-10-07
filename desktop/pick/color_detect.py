"""색깔 블록 찾기 (HSV 색 범위 + 모양 검사).

detect(bgr) → [{color, cx, cy, w, h, area}, ...] (면적 큰 순)
단독 실행: python color_detect.py 사진.jpg  → 사진_det.jpg 로 결과 그림 저장
"""
import sys
import cv2
import numpy as np

# 색 이름: (H 범위 목록, S 최소, V 최소, 표시색 BGR)   ※ OpenCV H 는 0~179
#  S/V 최소값은 색마다 따로 둔다. 2026-10-05 실측(배 카메라) 기준:
#   진짜 노랑 S247 V253 / 빨강 S206 V164 / 초록 S213 V120 / 파랑 S232 V111 / 보라 S159 V74
#   주의: 갈색 나무(가구 다리) H23 S127 V95 가 노랑으로 오검출됐음 → 노랑은 S·V 를 높게 요구
COLORS = {
    "red":    ([(0, 8), (170, 179)], 150,  90, (0, 0, 255)),
    "yellow": ([(18, 35)],           180, 150, (0, 220, 255)),
    "green":  ([(40, 85)],           150,  70, (0, 200, 0)),
    "blue":   ([(95, 115)],          150,  60, (255, 120, 0)),
    "purple": ([(116, 160)],         110,  40, (200, 0, 160)),
}
# 카메라마다 색감이 달라 S/V 최소값을 덮어쓴다. {카메라: {색: (S최소, V최소)}}
#  손목캠은 같은 빨강도 S120~165 로 연하게 찍힘(배캠은 S206). 그리퍼 끝 연두 스티커는 H32~34 S87~116.
CAM_SV = {
    "wrist": {"red": (45, 100), "yellow": (80, 140)},
    # 2026-10-06 저녁: 조명이 바뀌어 손목캠 빨강이 S76(연한 곳 52)까지 내려가 블록을 놓침 → 낮춤.
    #  저녁 바닥은 노르스름해도 S 60 이하, 그리퍼 스티커는 H37 이라 노랑(H18~31 · S≥80)에 안 걸린다.
}
# 카메라마다 색상(H) 범위도 덮어쓴다.
#  손목캠 노랑 블록 H25 S178 V239 / 그리퍼 끝 연두 스티커 H37~38 S87~108 (2026-10-06 실측)
#  → 손목캠 노랑은 H 18~31 로 좁혀 스티커와 겹치지 않게.
CAM_H = {
    "wrist": {"yellow": [(18, 31)]},
}
# 손목캠 빨강은 S(진하기) 대신 Lab 의 a*(붉은 정도)로 본다. 방 불빛이 위에서 비추면 블록 윗면이
#  허옇게 떠서 S 가 30~50 까지 떨어지는데(2026-10-06 20시), a* 는 블록 140 이상 · 바닥 135 이하로 갈린다.
CAM_A = {"wrist": {"red": 140}}
AREA_MIN = 40                # 너무 작은 점은 잡음
ASPECT_MAX = 2.5             # 블록은 대략 정사각형
FILL_MIN = 0.55              # 상자 안을 색이 얼마나 채우는지(블록이면 꽉 참)

# 카메라별 관심 영역(화면 비율 0~1, 다각형). 바닥 밖·로봇 몸체를 지운다.
#  배: 수평선(벽과 바닥 경계) 아래만 / 손목: 화면 아래쪽의 LED·로봇 몸체 제외
ROI = {
    "front": [(0, 0.47), (1, 0.47), (1, 1), (0, 1)],
    "wrist": [(0, 0), (1, 0), (1, 0.80), (0, 0.80)],
}


# 배캠에서 블록 크기 검사: 블록은 같은 크기 정육면체라, 화면 아래쪽(가까움)일수록 크게 보인다.
#  폭(px) ≈ SIZE_K × (아래끝 y − SIZE_YH). 2026-10-06 실측(30 · 50 · 70cm 에 블록 3개):
#   아래끝 342 → 42px, 284 → 27px, 260 → 18px (예측 42 · 25 · 18). 640x480 기준.
#  노란 비닐봉지 · 장난감을 노란 블록으로 착각해 다가간 일(2026-10-06 19:16) 막으려고.
SIZE_K, SIZE_YH = 0.293, 198.6
SIZE_RANGE = (0.55, 1.7)     # 예측 크기의 이 배수 사이면 블록으로 인정


def block_size_ok(d, shape):
    s = 480.0 / shape[0]
    bottom, size = (d["y"] + d["h"]) * s, max(d["w"], d["h"]) * s
    exp = max(6.0, SIZE_K * (bottom - SIZE_YH))
    if bottom >= 475:            # 화면 아래에 걸려 잘린 블록은 작게만 안 보이면 통과
        return size >= SIZE_RANGE[0] * exp * 0.5
    return SIZE_RANGE[0] * exp <= size <= SIZE_RANGE[1] * exp


def roi_px(cam, shape):
    h, w = shape[:2]
    return [(x * w, y * h) for x, y in ROI[cam]]


def color_mask(bgr, name, cam=None):
    """한 색의 화면 전체 마스크(관심 영역 자르기 전)."""
    hsv = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2HSV)
    ranges, s_min, v_min, _ = COLORS[name]
    s_min, v_min = CAM_SV.get(cam, {}).get(name, (s_min, v_min))
    ranges = CAM_H.get(cam, {}).get(name, ranges)
    mask = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in ranges:
        mask |= cv2.inRange(hsv[:, :, 0], lo, hi)
    a_min = CAM_A.get(cam, {}).get(name)
    if a_min is not None:
        lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2LAB)
        return mask & cv2.inRange(lab[:, :, 1], a_min, 255) & cv2.inRange(hsv[:, :, 2], v_min, 255)
    return mask & cv2.inRange(hsv, (0, s_min, v_min), (179, 255, 255))


def rises_above(bgr, d, top_y, cam=None):
    """이 블록 후보가 화면 전체에서 보면 바닥선(top_y) 위로 이어진 큰 덩어리의 일부인가.
    바닥에 놓인 블록은 바닥선 아래에만 있다. 벽에 기댄 노란 봉지는 아래끝만 바닥 영역에 걸쳐
    작은 블록처럼 보였다(2026-10-06 20:28, 크기 검사도 통과) → 위로 이어지면 블록이 아니다."""
    m = color_mask(bgr, d["color"], cam)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    x0, y0, w, h = d["x"], d["y"], d["w"], d["h"]
    ids = set(np.unique(lab[y0:y0 + h, x0:x0 + w])) - {0}
    return any(stats[i][1] < top_y - 3 for i in ids)


def detect(bgr, colors=None, roi=None, cam=None):
    hsv = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2HSV)
    base = np.full(hsv.shape[:2], 255, np.uint8)
    if roi is not None:                       # 관심 영역(다각형) 밖은 무시
        m = np.zeros(base.shape, np.uint8); cv2.fillPoly(m, [np.int32(roi)], 255)
        base &= m
    out = []
    for name, (ranges, s_min, v_min, _) in COLORS.items():
        s_min, v_min = CAM_SV.get(cam, {}).get(name, (s_min, v_min))
        ranges = CAM_H.get(cam, {}).get(name, ranges)
        if colors and name not in colors:
            continue
        mask = np.zeros(base.shape, np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(hsv[:, :, 0], lo, hi)
        a_min = CAM_A.get(cam, {}).get(name)
        if a_min is not None:                 # 붉은 정도(a*)로: 밝기 · 조명에 덜 흔들림
            lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2LAB)
            mask &= cv2.inRange(lab[:, :, 1], a_min, 255) & cv2.inRange(hsv[:, :, 2], v_min, 255) & base
        else:
            mask &= cv2.inRange(hsv, (0, s_min, v_min), (179, 255, 255)) & base
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if (a < AREA_MIN or max(w, h) / max(1, min(w, h)) > ASPECT_MAX
                    or a / float(w * h) < FILL_MIN):
                continue
            out.append(dict(color=name, cx=float(cents[i][0]), cy=float(cents[i][1]),
                            x=int(x), y=int(y), w=int(w), h=int(h), area=int(a)))
    return sorted(out, key=lambda d: -d["area"])


def draw(bgr, dets):
    img = bgr.copy()
    for d in dets:
        c = COLORS[d["color"]][-1]
        cv2.rectangle(img, (d["x"], d["y"]), (d["x"] + d["w"], d["y"] + d["h"]), c, 2)
        cv2.putText(img, d["color"], (d["x"], d["y"] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1)
    return img


if __name__ == "__main__":
    p = sys.argv[1]
    cam = sys.argv[2] if len(sys.argv) > 2 else None
    img = cv2.imread(p)
    dets = detect(img, roi=roi_px(cam, img.shape) if cam else None, cam=cam)
    for d in dets:
        print(f'{d["color"]:7s} 중심({d["cx"]:.0f},{d["cy"]:.0f}) 크기 {d["w"]}x{d["h"]} 면적 {d["area"]}')
    cv2.imwrite(p.rsplit(".", 1)[0] + "_det.jpg", draw(img, dets))
