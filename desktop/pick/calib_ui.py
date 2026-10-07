# 렌즈 보정 사진 수집 화면 (브라우저)
#   python calib_ui.py wrist      → http://localhost:8091
#   python calib_ui.py front
# 실시간 화면에 찾은 판 · 손가락 자리 · '다음 추천 자리'를 그려 주고,
# 찍은 장수 · 기울인 장수 · 구역 지도 · 찍은 사진 모음 · 지금 계산 버튼을 보여 준다.
# 저장 규칙은 calib_capture.py 와 같다(이미 찍은 것과 비슷하면 건너뜀, 손가락에 걸치면 버림).
import os, sys, time, json, threading, subprocess, urllib.request
import cv2, numpy as np
from flask import Flask, Response, jsonify, send_from_directory
from calib_boards import find_boards, near_fingers, WRIST_BLOCK

CAM = sys.argv[1] if len(sys.argv) > 1 else "wrist"
NEED = 25
PORT = 8091
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, f"calib_{CAM}_tilt")
os.makedirs(OUT, exist_ok=True)
W, H = 640, 480
FLAT, TILT = 0.08, 0.15            # 기울기 값(변 길이 비의 로그) 기준: 이보다 작으면 평평, 크면 '기울임'

# ─── 다음에 찍을 자리 계획: (구역, 기울이기) ───
# 구역은 판 중심이 들어간 3x3 칸. 기울이기: 평평 · 왼쪽 들기 · 오른쪽 들기 · 먼 쪽 들기 · 가까운 쪽 들기
ZN = {(0, 0): "왼쪽 위", (0, 1): "위 가운데", (0, 2): "오른쪽 위", (1, 0): "왼쪽 가운데", (1, 1): "한가운데",
      (1, 2): "오른쪽 가운데", (2, 0): "왼쪽 아래", (2, 1): "아래 가운데", (2, 2): "오른쪽 아래"}
# 판은 바닥에 평평히 두고 팔(카메라)을 기울인다 → 안내는 '화면에서 어느 쪽이 크게 보이게' 로 한다
TN = {"flat": "정면으로(판이 반듯한 직사각형)", "L": "판 왼쪽이 크게 보이게", "R": "판 오른쪽이 크게 보이게",
      "F": "판 위쪽이 크게 보이게", "B": "판 아래쪽이 크게 보이게"}
PLAN = [((1, 1), "flat"), ((0, 0), "flat"), ((0, 2), "flat"), ((0, 0), "R"), ((0, 2), "L"),
        ((1, 1), "L"), ((1, 1), "R"), ((1, 1), "F"), ((1, 1), "B"),
        ((0, 1), "flat"), ((0, 1), "F"), ((0, 1), "B"), ((0, 0), "B"), ((0, 2), "B"),
        ((1, 0), "flat"), ((1, 0), "R"), ((1, 2), "flat"), ((1, 2), "L"), ((2, 1), "flat"), ((2, 1), "F")]
if CAM == "front":
    PLAN += [((2, 0), "flat"), ((2, 2), "flat"), ((2, 0), "R"), ((2, 2), "L")]
else:
    # 손목캠: 손가락이 양옆 아래를 차지해 판(화면에서 약 200px)이 온전히 들어가는 곳은 가운데 세로줄뿐(2026-10-07).
    # 구석 자리를 추천하면 판이 화면 밖이나 손가락에 걸려 영영 안 찍힌다 → 들어가는 자리만, 기울기를 다양하게.
    # 좌우로 넓게 못 덮는 대신 calib_solve.py 가 렌즈 중심을 화면 정중앙으로 고정한다.
    PLAN = [(z, k) for z in [(1, 1), (0, 1)] for k in ["flat", "L", "R", "F", "B"]]


def tilt(c, pat):
    p = c.reshape(pat[1], pat[0], 2)
    if p[0, :, 1].mean() > p[-1, :, 1].mean():   # 모서리 순서가 뒤집혀 나와도 위 · 왼쪽이 맞게
        p = p[::-1]
    if p[:, 0, 0].mean() > p[:, -1, 0].mean():
        p = p[:, ::-1]
    top, bot = np.linalg.norm(p[0, -1] - p[0, 0]), np.linalg.norm(p[-1, -1] - p[-1, 0])
    lef, rig = np.linalg.norm(p[-1, 0] - p[0, 0]), np.linalg.norm(p[-1, -1] - p[0, -1])
    return float(np.log(top / bot)), float(np.log(lef / rig))


def kind(tl):
    """기울기 값 → 평평 / L / R / F / B (변이 길어 보이는 쪽 = 카메라에 가까운 쪽 = 들린 쪽)"""
    fb, lr = tl
    if max(abs(fb), abs(lr)) < FLAT:
        return "flat"
    if abs(lr) >= abs(fb):
        return "L" if lr > 0 else "R"
    return "F" if fb > 0 else "B"


def zone(pts):
    cx, cy = pts.mean(0)
    return (min(int(cy * 3 / H), 2), min(int(cx * 3 / W), 2))


S = {"frame": None, "boards": [], "saved": [], "files": [], "msg": "", "solve": "", "lock": threading.Lock()}


def register(c, pat, fname):
    pts = c.reshape(-1, 2); tl = tilt(c, pat)
    S["saved"].append({"ctr": pts.mean(0), "size": float(np.ptp(pts, 0).mean()), "tl": np.array(tl),
                       "zone": zone(pts), "kind": kind(tl), "file": fname})


# 이어서 찍기: 이미 있는 사진을 먼저 등록
for f in sorted(os.listdir(OUT)):
    for c, pat in find_boards(cv2.imread(os.path.join(OUT, f), 0), 2, True):
        if not (CAM == "wrist" and near_fingers(c)):
            register(c, pat, f)
    S["files"].append(f)


def is_new(pts, tl):
    ctr, size = pts.mean(0), np.ptp(pts, 0).mean()
    return not any(np.linalg.norm(ctr - s["ctr"]) < 50 and abs(size - s["size"]) < 30
                   and np.linalg.norm(np.array(tl) - s["tl"]) < 0.12 for s in S["saved"])


def next_target():
    done = {(s["zone"], s["kind"]) for s in S["saved"]}
    for z, k in PLAN:
        if (z, k) not in done:
            return z, k
    return None


def frames():
    while True:
        try:
            s = urllib.request.urlopen(f"http://localhost:8080/stream/{CAM}", timeout=10); buf = b""
            while True:
                buf += s.read(8192)
                a = buf.find(b"\xff\xd8"); b = buf.find(b"\xff\xd9", a)
                if a >= 0 and b >= 0:
                    j, buf = buf[a:b + 2], buf[b + 2:]
                    img = cv2.imdecode(np.frombuffer(j, np.uint8), 1)
                    if img is not None:
                        yield img
        except Exception as e:
            S["msg"] = f"카메라 영상 끊김, 다시 연결 중 ({e})"; time.sleep(1)


def worker():
    t_det = 0
    for img in frames():
        with S["lock"]:
            S["frame"] = img
        if time.time() - t_det < 0.4:
            continue
        t_det = time.time()
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(g, cv2.CV_64F).var()
        boards, saved_now = [], False
        found = find_boards(g, 2, True)
        prev, S["prev_ctr"] = S.get("prev_ctr", []), [c.reshape(-1, 2).mean(0) for c, _ in found]
        for c, pat in found:
            pts = c.reshape(-1, 2); tl = tilt(c, pat)
            still = any(np.linalg.norm(pts.mean(0) - p) < 4 for p in prev)
            if CAM == "wrist" and near_fingers(c):
                boards.append((pts, "finger")); continue
            if sharp < 180 or not still:
                boards.append((pts, "blur")); continue
            if is_new(pts, tl):
                if not saved_now:
                    fname = f"{len(S['files']) + 1:02d}.png"
                    cv2.imwrite(os.path.join(OUT, fname), img)
                    S["files"].append(fname); saved_now = True
                register(c, pat, S["files"][-1])
                boards.append((pts, "new"))
            else:
                boards.append((pts, "dup"))
        with S["lock"]:
            S["boards"] = boards; S["t_boards"] = time.time()
            S["msg"] = {True: "새 사진 저장!", False: ""}[saved_now] or (
                "판이 손가락에 걸쳐 있어요" if any(k == "finger" for _, k in boards) else
                "이미 비슷한 사진이 있어요 - 위치나 기울기를 바꿔 주세요" if any(k == "dup" for _, k in boards) else
                "흔들려요 - 팔을 멈추고 1초 기다려 주세요" if any(k == "blur" for _, k in boards) else
                "판이 안 보여요" if not boards else "")


COL = {"new": (0, 200, 0), "dup": (0, 200, 255), "finger": (0, 0, 255), "blur": (200, 0, 200)}


def overlay():
    with S["lock"]:
        img = None if S["frame"] is None else S["frame"].copy()
        boards = S["boards"] if time.time() - S.get("t_boards", 0) < 1.0 else []
    if img is None:
        img = np.zeros((H, W, 3), np.uint8)
    if CAM == "wrist":                       # 손가락 자리: 어둡게
        sh = img.copy()
        for x0, y0, x1, y1 in WRIST_BLOCK:
            cv2.rectangle(sh, (x0, y0), (x1, y1), (0, 0, 120), -1)
        img = cv2.addWeighted(sh, 0.35, img, 0.65, 0)
    nt = next_target()
    if nt:                                   # 다음 추천 자리: 파란 점선 네모
        (r, c), k = nt
        x0, y0 = c * W // 3 + 12, r * H // 3 + 12
        x1, y1 = (c + 1) * W // 3 - 12, (r + 1) * H // 3 - 12
        for i in range(x0, x1, 16):
            cv2.line(img, (i, y0), (min(i + 8, x1), y0), (255, 140, 0), 3); cv2.line(img, (i, y1), (min(i + 8, x1), y1), (255, 140, 0), 3)
        for i in range(y0, y1, 16):
            cv2.line(img, (x0, i), (x0, min(i + 8, y1)), (255, 140, 0), 3); cv2.line(img, (x1, i), (x1, min(i + 8, y1)), (255, 140, 0), 3)
        mid = ((x0 + x1) // 2, (y0 + y1) // 2)
        arrow = {"L": ((x1 - 20, mid[1]), (x0 + 20, mid[1])), "R": ((x0 + 20, mid[1]), (x1 - 20, mid[1])),
                 "F": ((mid[0], y1 - 15), (mid[0], y0 + 15)), "B": ((mid[0], y0 + 15), (mid[0], y1 - 15))}.get(k)
        if arrow:                            # 화살표 끝 = 크게 보여야 할 쪽
            cv2.arrowedLine(img, arrow[0], arrow[1], (255, 140, 0), 4, tipLength=0.25)
    for pts, k in boards:
        hull = cv2.convexHull(pts.astype(np.int32))
        cv2.polylines(img, [hull], True, COL[k], 3)
        for x, y in pts[::3]:
            cv2.circle(img, (int(x), int(y)), 3, COL[k], -1)
    return img


app = Flask(__name__)


@app.route("/")
def index():
    return PAGE.replace("__CAM__", "손목 카메라" if CAM == "wrist" else "앞카메라")


@app.route("/frame.jpg")
def frame():
    """한 장씩: 화면이 0.1초마다 받아 간다. 영상(stream)과 달리 끊겨도 다음 장에서 저절로 이어진다."""
    ok, j = cv2.imencode(".jpg", overlay(), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(j.tobytes(), mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.route("/stream")
def stream():
    def gen():
        while True:
            ok, j = cv2.imencode(".jpg", overlay(), [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield b"--f\r\nContent-Type: image/jpeg\r\n\r\n" + j.tobytes() + b"\r\n"
            time.sleep(0.08)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=f")


@app.route("/api/status")
def status():
    grid = [[0] * 3 for _ in range(3)]
    for s in S["saved"]:
        grid[s["zone"][0]][s["zone"][1]] += 1
    nt = next_target()
    done = {(s["zone"], s["kind"]) for s in S["saved"]}
    n_tilt = sum(s["kind"] != "flat" for s in S["saved"])
    return jsonify(cam=CAM, photos=len(S["files"]), boards=len(S["saved"]), tilted=n_tilt, need=NEED,
                   need_tilt=NEED // 3, grid=grid, msg=S["msg"], solve=S["solve"],
                   blocked=[[1, 0], [1, 2], [2, 0], [2, 2]] if CAM == "wrist" else [],
                   target=None if not nt else {"zone": ZN[nt[0]], "how": TN[nt[1]], "rc": list(nt[0])},
                   plan_done=sum(p in done for p in PLAN), plan_total=len(PLAN),
                   files=[{"f": f, "kinds": [TN[s["kind"]] for s in S["saved"] if s["file"] == f]}
                          for f in reversed(S["files"])])


@app.route("/img/<f>")
def img(f):
    return send_from_directory(OUT, f)


@app.route("/api/undo", methods=["POST"])
def undo():
    if S["files"]:
        f = S["files"].pop()
        S["saved"] = [s for s in S["saved"] if s["file"] != f]
        os.rename(os.path.join(OUT, f), os.path.join(OUT, "..", f"_deleted_{CAM}_{int(time.time())}_{f}"))
    return jsonify(ok=True)


@app.route("/api/solve", methods=["POST"])
def solve():
    S["solve"] = "계산 중..."
    r = subprocess.run([sys.executable, "calib_solve.py", CAM], cwd=HERE, capture_output=True, text=True, timeout=300)
    S["solve"] = "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "Warning" not in l)
    return jsonify(ok=True, out=S["solve"])


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>렌즈 보정</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#111418;--card:#1c2128;--fg:#e8ecf1;--dim:#8b95a3;--ok:#3ccf6e;--warn:#f5b041;--bad:#ef5350;--acc:#4ea1ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,"Noto Sans KR",sans-serif}
header{padding:12px 16px;font-size:20px;font-weight:700}header span{color:var(--dim);font-weight:400;font-size:14px;margin-left:8px}
main{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:12px;padding:0 16px 16px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:12px;padding:14px}
#live{width:100%;border-radius:10px;display:block;background:#000}
.msg{margin-top:8px;font-size:18px;min-height:26px;font-weight:600}
.big{display:flex;gap:10px}.big div{flex:1;background:#262c35;border-radius:10px;padding:10px;text-align:center}
.big b{display:block;font-size:34px}.big small{color:var(--dim)}
.bar{height:10px;background:#333a44;border-radius:5px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--ok)}
.target{margin-top:12px;border:2px dashed var(--acc);border-radius:10px;padding:10px;font-size:17px}
.target b{color:var(--acc)}
.rules{margin-top:12px;background:#262c35;border-radius:10px;padding:10px;font-size:14px;line-height:1.5}
.rules label{display:block;margin-top:4px;cursor:pointer}.rules u{text-decoration-color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-top:10px}
.grid div{aspect-ratio:4/3;border-radius:6px;display:flex;align-items:center;justify-content:center;font-weight:700}
.legend{color:var(--dim);font-size:13px;margin-top:8px;line-height:1.6}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:middle;margin-right:4px}
button{background:#2d3540;color:var(--fg);border:0;border-radius:8px;padding:10px 12px;font-size:15px;cursor:pointer;flex:1}
button:hover{background:#3a4452}.btns{display:flex;gap:8px;margin-top:12px}
pre{white-space:pre-wrap;font-size:13px;color:var(--dim);margin:8px 0 0}
.thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px;margin-top:12px}
.thumbs figure{margin:0}.thumbs img{width:100%;border-radius:6px;display:block}
.thumbs figcaption{font-size:12px;color:var(--dim);margin-top:2px}
</style></head><body>
<header>렌즈 보정 - __CAM__<span>판은 바닥에 두고 팔을 움직여 파란 네모 자리에 맞춘 뒤 1초 멈추면 자동으로 찍혀요</span></header>
<main>
 <section class="card"><img id="live"><div class="msg" id="msg"></div>
  <div class="legend"><i style="background:#00c800"></i>새로 찍힘 <i style="background:#ffc800"></i>이미 비슷한 사진 있음
   <i style="background:#ff0000"></i>손가락에 걸침 <i style="background:#c800c8"></i>흔들림 <i style="background:#0078ff"></i>다음 추천 자리(화살표 끝 = 크게 보여야 할 쪽)</div>
  <div class="thumbs" id="thumbs"></div></section>
 <aside class="card">
  <div class="big"><div><b id="n">0</b><small>찍은 사진 / <span id="need"></span></small></div>
   <div><b id="t">0</b><small>기울인 판 / <span id="needt"></span></small></div></div>
  <div class="bar"><i id="pbar" style="width:0"></i></div>
  <div class="target" id="target"></div>
  <div class="rules"><b>찍기 전 확인</b>
   <label><input type="checkbox"> 체커 종이를 판지 · 책 표지에 붙여 <u>완전히 평평</u>하게</label>
   <label><input type="checkbox"> 판은 바닥에 <u>가만히</u> 두고, 움직이는 건 팔(카메라)만</label>
   <label><input type="checkbox"> 손으로 종이 끝을 들지 않기 (휘면 그 사진은 못 씀)</label>
   <label><input type="checkbox"> 판 전체(9x6)가 손가락에 안 걸리고 다 보이게</label>
   <label><input type="checkbox"> <u>왼쪽 위 · 오른쪽 위</u> 귀퉁이를 꼭 채우기 - 손목캠은 가장자리 정보가 여기서만 나와요</label>
  </div>
  <div style="margin-top:12px;color:var(--dim)">구역 지도 (숫자 = 그 구역에 찍힌 판 수)</div>
  <div class="grid" id="grid"></div>
  <div class="btns"><button onclick="undo()">마지막 사진 지우기</button><button onclick="solve()">지금 계산해 보기</button></div>
  <pre id="solve"></pre>
 </aside>
</main>
<script>
let lastN=-1;
async function tick(){
 const s=await (await fetch('/api/status')).json();
 n.textContent=s.photos; need.textContent=s.need; t.textContent=s.tilted; needt.textContent=s.need_tilt;
 pbar.style.width=Math.min(100,100*s.plan_done/s.plan_total)+'%';
 msg.textContent=s.msg; msg.style.color=s.msg.includes('저장')?'var(--ok)':s.msg?'var(--warn)':'';
 target.innerHTML=s.target?`다음 추천 (${s.plan_done}/${s.plan_total})<br>자리: <b>${s.target.zone}</b><br>기울이기: <b>${s.target.how}</b>`
   :'<b>추천 자리를 다 채웠어요!</b> 「지금 계산해 보기」를 눌러 주세요';
 grid.innerHTML='';
 for(let r=0;r<3;r++)for(let c=0;c<3;c++){const d=document.createElement('div');const v=s.grid[r][c];
  const blk=s.blocked.some(b=>b[0]==r&&b[1]==c);const tg=s.target&&s.target.rc[0]==r&&s.target.rc[1]==c;
  d.textContent=blk&&!v?'손가락':v; d.style.background=v>=3?'#1f6f3f':v?'#6b5a1e':blk?'#2a2f36':'#3a2228';
  if(tg)d.style.outline='3px dashed #4ea1ff'; grid.appendChild(d);}
 solveEl.textContent=s.solve;
 if(s.photos!=lastN){lastN=s.photos;thumbs.innerHTML=s.files.map(x=>`<figure><img src="/img/${x.f}?${x.f}"><figcaption>${x.f} · ${x.kinds.join(', ')||'판 없음'}</figcaption></figure>`).join('');}
}
const solveEl=document.getElementById('solve');
async function undo(){await fetch('/api/undo',{method:'POST'});tick();}
async function solve(){solveEl.textContent='계산 중...';await fetch('/api/solve',{method:'POST'});tick();}
// 영상: 한 장 다 받으면 다음 장 요청, 실패하면 0.5초 뒤 다시(끊겨도 저절로 이어짐)
const live=document.getElementById('live');
function nextFrame(d){setTimeout(()=>{live.src='/frame.jpg?'+Date.now();},d);}
live.onload=()=>nextFrame(80); live.onerror=()=>nextFrame(500);
setInterval(()=>{if(!live.complete)return; if(Date.now()-(live._t||0)>3000)nextFrame(0);},3000);
live.addEventListener('load',()=>{live._t=Date.now();});
nextFrame(0);
setInterval(()=>tick().catch(()=>{}),700);tick();
</script></body></html>"""

if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
