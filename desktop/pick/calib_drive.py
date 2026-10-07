# 벽에 붙인 체커보드 앞에서 로봇이 스스로 물러나고 돌면서 렌즈 보정 사진을 모은다.
# 판이 화면 여러 위치(왼쪽 · 가운데 · 오른쪽, 가까이 · 멀리)에 오도록 거리마다 좌우로 돈다.
# 멈춘 뒤 찍어서 흔들림을 없앤다. 끝나면 calib_front/ 에 사진, 이어서 calib_solve.py 로 계산.
import os, time, urllib.request, cv2, numpy as np
from robot_api import drive_for, stop
from calib_boards import find_boards

URL = "http://localhost:8080/stream/front"
PAT = (9, 6)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib_front")
os.makedirs(OUT, exist_ok=True)
BACK_V, TURN_V = -0.06, 12.0          # m/s, 도/s (천천히: 강아지 주의)


def snap():
    s = urllib.request.urlopen(URL, timeout=5); buf = b""; got = 0
    while True:
        buf += s.read(8192)
        a = buf.find(b"\xff\xd8"); b = buf.find(b"\xff\xd9", a)
        if a >= 0 and b >= 0:
            j, buf = buf[a:b + 2], buf[b + 2:]
            got += 1
            if got >= 3:                  # 앞쪽 몇 장은 멈추기 전 장면일 수 있어 버림
                return cv2.imdecode(np.frombuffer(j, np.uint8), 1)


n = len(os.listdir(OUT))
def shoot(tag):
    global n
    time.sleep(0.6)
    img = snap()
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    boards = find_boards(g)
    if boards:
        n += 1
        cv2.imwrite(os.path.join(OUT, f"{n:02d}.png"), img)
        desc = ", ".join(f"y {p[:,1].min():.0f}~{p[:,1].max():.0f}" for p in (b.reshape(-1, 2) for b in boards))
        print(f"  {tag}: 저장 {n:02d} (판 {len(boards)}장: {desc})", flush=True)
    else:
        print(f"  {tag}: 판 안 보임", flush=True)


try:
    # 30cm(제자리) → 40 · 55 · 75cm, 각 거리에서 정면 · 왼쪽 2단 · 오른쪽 2단
    for back in (0.0, 0.10, 0.15, 0.20):
        if back: drive_for(x=BACK_V, sec=back / -BACK_V)
        print(f"물러남 +{back*100:.0f}cm", flush=True)
        shoot("정면")
        for deg in (8, 16):                  # 왼쪽으로 돌면 판은 화면 오른쪽으로
            drive_for(theta=TURN_V, sec=8 / TURN_V); shoot(f"왼쪽 {deg}°")
        drive_for(theta=-TURN_V, sec=16 / TURN_V)     # 다시 정면
        for deg in (8, 16):
            drive_for(theta=-TURN_V, sec=8 / TURN_V); shoot(f"오른쪽 {deg}°")
        drive_for(theta=TURN_V, sec=16 / TURN_V)      # 정면으로 복귀
finally:
    stop()
print(f"끝: 사진 {n}장", flush=True)
