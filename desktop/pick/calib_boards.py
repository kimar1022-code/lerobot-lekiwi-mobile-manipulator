# 한 화면에 체커보드가 여러 장(벽 · 바닥) 있을 때 하나씩 찾는다: 찾은 판은 회색으로 덮고 다시 찾기
# 판 일부가 가려져도(클립보드 등) 안쪽 꼭짓점 7x6 이 보이면 쓴다. 칸 크기가 같아 보정엔 상관없다.
import cv2, numpy as np
PATS = [(9, 6), (7, 6)]
FLAGS = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE


# 판이 화면보다 클 때(손목캠 look 자세: 바닥이 가까움) 보이는 일부분만 찾는 크기
PARTS = [(6, 4), (5, 4), (6, 3)]


def find_boards(g, most=2, with_pat=False, partial=False):
    g, out = g.copy(), []
    for _ in range(most):
        for pat in PATS:
            ok, c = cv2.findChessboardCorners(g, pat, FLAGS)
            if ok:
                c = cv2.cornerSubPix(g, c, (5, 5), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3))
                break
        if not ok and partial:
            for pat in PARTS:
                ok, c = cv2.findChessboardCornersSB(g, pat, cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY | cv2.CALIB_CB_LARGER)
                if ok:
                    break
        if not ok:
            break
        out.append((c, pat) if with_pat else c)
        # 안쪽 꼭짓점 테두리를 한 칸쯤 넓혀서 덮는다(바깥 칸까지)
        hull = cv2.convexHull(c.reshape(-1, 2))
        ctr = hull.reshape(-1, 2).mean(0)
        big = ((hull.reshape(-1, 2) - ctr) * 1.35 + ctr).astype(np.int32)
        cv2.fillConvexPoly(g, big, 128)
    return out


# 손목캠 look 계열 자세에서 그리퍼 손가락 · 몸체가 가리는 곳(640x480 기준, 2026-10-07 화면에서 잼)
# 이 근처에 꼭짓점이 있으면 가려진 칸 때문에 위치가 틀어진다 → 그런 판은 버린다
WRIST_BLOCK = [(0, 165, 185, 480), (445, 160, 640, 480), (140, 420, 520, 480)]


def near_fingers(c, margin=15):
    for x, y in c.reshape(-1, 2):
        for x0, y0, x1, y1 in WRIST_BLOCK:
            if x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin:
                return True
    return False
