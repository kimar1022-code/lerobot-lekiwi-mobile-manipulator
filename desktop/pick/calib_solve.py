# 렌즈 보정값 계산 → front_calib.json (또는 wrist_calib.json)
#   python calib_solve.py front     # calib_front/ + calib_front_tilt/ 사진 사용
# 손에 든 종이가 휘면 그 장면만 오차가 커진다 → 오차 큰 판을 몇 번 걸러 낸다.
import glob, json, os, sys, cv2, numpy as np
from calib_boards import find_boards, near_fingers
CAM = sys.argv[1] if len(sys.argv) > 1 else "front"
# 칸 크기(실측): 앞캠은 큰 판 24mm(10칸 240mm), 손목캠은 작은 판 12mm(100mm 자 확인, 2026-10-07)
SQ = float(sys.argv[2]) / 1000 if len(sys.argv) > 2 else (0.012 if CAM == "wrist" else 0.024)
D = os.path.dirname(os.path.abspath(__file__))


def objp(pat):
    o = np.zeros((pat[0] * pat[1], 3), np.float32)
    o[:, :2] = np.mgrid[0:pat[0], 0:pat[1]].T.reshape(-1, 2) * SQ
    return o


O, I = [], []
for f in sorted(glob.glob(os.path.join(D, f"calib_{CAM}*", "*.png"))):
    g = cv2.imread(f, 0)
    for c, pat in find_boards(g, 2, True, partial=False):
        if CAM == "wrist" and near_fingers(c):
            continue
        O.append(objp(pat)); I.append(c)
h, w = g.shape
n0 = len(O)
# 왜곡은 k1 · k2 만(접선 · k3 고정): 판이 적은 구역에서 엉뚱하게 휘지 않게
flags = cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST
K_init = None
if CAM == "wrist":
    # 손목캠은 손가락 때문에 판이 화면 가운데 세로줄에만 들어간다 → 렌즈 중심을 못 구한다(cx -144 같은 값이 나옴).
    # 값싼 USB 카메라는 렌즈 중심이 거의 정중앙이라, 중심을 정중앙에 고정하고 배율 · 휨만 구한다.
    flags |= cv2.CALIB_FIX_PRINCIPAL_POINT | cv2.CALIB_USE_INTRINSIC_GUESS
    K_init = np.array([[600.0, 0, 320], [0, 600.0, 240], [0, 0, 1]])
for _ in range(5):
    rms, K, dist, rv, tv = cv2.calibrateCamera(O, I, (w, h), None if K_init is None else K_init.copy(), None, flags=flags)
    err = [np.sqrt(np.mean(np.sum((cv2.projectPoints(o, r, t, K, dist)[0] - i) ** 2, -1)))
           for o, i, r, t in zip(O, I, rv, tv)]
    keep = [k for k, e in enumerate(err) if e < max(0.6, np.median(err) * 2.5)]
    if len(keep) == len(O):
        break
    O, I = [O[k] for k in keep], [I[k] for k in keep]
print(f"판 {n0}개 중 {len(O)}개 사용, 재투영 오차 {rms:.3f}px")
print("K", np.round(K, 1).tolist()); print("dist", np.round(dist.ravel(), 4).tolist())
out = os.path.join(D, f"{CAM}_calib.json")
old = json.load(open(out)) if os.path.exists(out) else {}
old.update({"K": K.tolist(), "dist": dist.ravel().tolist(), "size": [w, h], "rms": rms, "n": len(O)})
json.dump(old, open(out, "w"), indent=1, ensure_ascii=False)
