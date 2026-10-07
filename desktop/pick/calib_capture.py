# 렌즈 보정용 사진 자동 수집 (판을 손에 들고 움직이는 방식)
#   python calib_capture.py front 30     # 앞카메라, 30장
#   python calib_capture.py wrist 30     # 손목카메라
# 웹서버 영상에서 체커보드(안쪽 꼭짓점 9x6)가 보이는 장면을 골라 calib_<카메라>_tilt/ 에 저장.
# 이미 찍은 것과 위치 · 크기 · 기울기가 비슷하면 건너뛰고, 빈 구역과 기울기 장수를 알려 준다.
import os, sys, time, urllib.request, cv2, numpy as np
from calib_boards import find_boards, near_fingers

CAM = sys.argv[1] if len(sys.argv) > 1 else "front"
NEED = int(sys.argv[2]) if len(sys.argv) > 2 else 30
URL = f"http://localhost:8080/stream/{CAM}"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"calib_{CAM}_tilt")
os.makedirs(OUT, exist_ok=True)


def frames():
    s = urllib.request.urlopen(URL, timeout=10); buf = b""
    while True:
        buf += s.read(8192)
        a = buf.find(b"\xff\xd8"); b = buf.find(b"\xff\xd9", a)
        if a >= 0 and b >= 0:
            j, buf = buf[a:b + 2], buf[b + 2:]
            img = cv2.imdecode(np.frombuffer(j, np.uint8), 1)
            if img is not None:
                yield img


PARTIAL = False   # 일부분만 찾기(SB LARGER)는 꼭짓점이 엉뚱하게 잡혀 fx 141~2016 으로 튐(2026-10-07) → 끔


def tilt(p, pat):
    """판 기울기 대략: 위 · 아래 변 길이 비(좌우로 기울임), 왼 · 오른 변 비(위아래로 기울임)"""
    p = p.reshape(pat[1], pat[0], 2)
    top, bot = np.linalg.norm(p[0, -1] - p[0, 0]), np.linalg.norm(p[-1, -1] - p[-1, 0])
    lef, rig = np.linalg.norm(p[-1, 0] - p[0, 0]), np.linalg.norm(p[-1, -1] - p[0, -1])
    return np.log(top / bot), np.log(lef / rig)


saved, cover, n_tilt = [], np.zeros((3, 3), int), 0
# 이어서 찍기: 이미 저장된 사진의 판도 '찍은 것'으로 등록
for f in sorted(os.listdir(OUT)):
    for b, pat in find_boards(cv2.imread(os.path.join(OUT, f), 0), most=2, with_pat=True, partial=PARTIAL):
        pts = b.reshape(-1, 2); tl = np.array(tilt(b, pat))
        saved.append((pts.mean(0), np.ptp(pts, 0).mean(), tl)); n_tilt += np.abs(tl).max() > 0.15
        for x, y in pts:
            cover[min(int(y * 3 / 480), 2), min(int(x * 3 / 640), 2)] += 1
t_last = 0
print(f"{CAM} 카메라 수집 시작 - 판을 천천히 움직여 줘", flush=True)
for img in frames():
    if time.time() - t_last < 0.5:
        continue
    t_last = time.time()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 흔들린 사진 거르기: 꼭짓점 주변이 흐리면 버림
    if cv2.Laplacian(g, cv2.CV_64F).var() < 30:
        continue
    # 벽에 붙은 판과 손에 든 판이 같이 보일 수 있다 → 둘 다 보고 '새로운' 판이 있을 때만 저장
    new = None
    for b, pat in find_boards(g, most=2, with_pat=True, partial=PARTIAL):
        if CAM == "wrist" and near_fingers(b):
            continue                                  # 손가락에 걸친 판은 꼭짓점이 틀어진다
        pts = b.reshape(-1, 2)
        ctr, size, tl = pts.mean(0), np.ptp(pts, 0).mean(), np.array(tilt(b, pat))
        if not any(np.linalg.norm(ctr - c0) < 50 and abs(size - z0) < 30 and np.linalg.norm(tl - t0) < 0.12
                   for c0, z0, t0 in saved):
            new = (b, pts, ctr, size, tl); break
    if new is None:
        continue
    b, pts, ctr, size, tl = new
    h, w = g.shape
    for x, y in pts:
        cover[min(int(y * 3 / h), 2), min(int(x * 3 / w), 2)] += 1
    tilted = np.abs(tl).max() > 0.15                 # 대략 20° 넘게 기울었으면
    n_tilt += tilted
    saved.append((ctr, size, tl))
    cv2.imwrite(os.path.join(OUT, f"{len(os.listdir(OUT)) + 1:02d}.png"), img)
    empty = [f"{'위가아'[r]}{'왼가오'[c]}" for r in range(3) for c in range(3) if cover[r, c] == 0]
    print(f"{len(os.listdir(OUT))}/{NEED} 저장{' (기울임)' if tilted else ''}  기울인 사진 {n_tilt}장"
          + (f"  빈 구역: {' '.join(empty)}" if empty else "  모든 구역 채움"), flush=True)
    if len(os.listdir(OUT)) >= NEED and not empty and n_tilt >= NEED // 3:
        print("완료", flush=True); break
