#!/usr/bin/env python
"""LeKiwi 웹 조종 GUI

카메라 3대(로봇 배·손목, 데스크탑 웹캠) + 실제 STL 3D 모델 +
바퀴/팔 조종 + 리더팔 미러링을 브라우저 한 화면에서.

실행:
    cd ~/lerobot && ./.venv/bin/python lekiwi_web.py
    브라우저에서 http://localhost:8080

Pi 호스트 데몬이 먼저 떠 있어야 함:
    ssh lekiwi '~/lekiwi_tools/run_host.sh -b'
"""
import glob
import os
import subprocess
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request, send_from_directory

from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

# ─── 설정 ────────────────────────────────────────────────────────────
PI_IP     = os.environ.get("LEKIWI_IP", "192.168.75.20")
ROBOT_ID  = os.environ.get("LEKIWI_ID", "my_lekiwi")
LEADER_ID = os.environ.get("LEADER_ID", "my_leader")
WEB_PORT  = int(os.environ.get("WEB_PORT", "8080"))
DESK_CAM  = int(os.environ.get("DESK_CAM", "0"))
FPS       = 30

# 카메라가 돌아간 채로 달려 있어 화면에서 바로잡는다.
#   front : 거꾸로 달림      -> 180도
#   wrist : 옆으로 누워 달림 -> 왼쪽(반시계) 90도
FRONT_ROTATE = 180
WRIST_ROTATE = 90       # 0 / 90(반시계) / 180 / 270(시계)

ARM_JOINTS = [
    ("arm_shoulder_pan.pos",   "조인트 1", "shoulder_pan"),
    ("arm_shoulder_lift.pos",  "조인트 2", "shoulder_lift"),
    ("arm_elbow_flex.pos",     "조인트 3", "elbow_flex"),
    ("arm_wrist_flex.pos",     "조인트 4", "wrist_flex"),
    ("arm_wrist_roll.pos",     "조인트 5", "wrist_roll"),
    ("arm_gripper.pos",        "그리퍼",   "gripper"),
]
JOINT_KEYS = [k for k, _, _ in ARM_JOINTS]

# 명령이 이 시간 넘게 안 오면 바퀴를 세운다(브라우저가 닫혀도 안 달아나게)
DRIVE_TIMEOUT = 0.6

# 로봇 관측이 이 시간 넘게 안 오면 연결이 끊긴 것으로 보고 다시 붙는다.
# (Pi 데몬이 조용히 죽어도 화면은 '연결됨'으로 남아있던 문제)
OBS_TIMEOUT = 4.0
SSH_HOST = os.environ.get("LEKIWI_SSH", "lekiwi")


def find_leader_port():
    if p := os.environ.get("LEADER_PORT"):
        return p
    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    return ports[0] if ports else None


class Shared:
    """스레드 사이에서 주고받는 상태"""
    def __init__(self):
        self.lock = threading.Lock()

        self.frames = {"front": None, "wrist": None, "desk": None}

        self.drive = {"x": 0.0, "y": 0.0, "theta": 0.0}
        self.drive_stamp = 0.0

        self.arm_target = {}      # 슬라이더로 정한 목표
        self.arm_current = {}     # 로봇이 알려준 현재값
        self.leader_pose = {}     # 리더팔에서 읽은 값
        self.arm_mode = "off"     # off | manual | leader

        # 연결 요청 / 실제 상태
        self.want_robot = True
        self.want_leader = False
        self.robot_on = False
        self.leader_on = False

        self.error = ""
        self.leader_error = ""
        self.fps_actual = 0.0
        self.leader_reads = 0      # 리더팔을 실제로 읽은 횟수(진단용)
        self.obs_age = 0.0         # 마지막으로 관측이 온 뒤 흐른 시간(초)
        self.reconnects = 0        # 자동 재연결 횟수
        self.startup_msg = ""      # 원클릭 시작 진행 상황
        self.loop_count = 0        # 제어 루프가 돈 횟수
        self.stop = False


S = Shared()
app = Flask(__name__)
HERE = os.path.dirname(os.path.abspath(__file__))


# ─── 로봇 제어 스레드 ────────────────────────────────────────────────
def robot_loop():
    robot = None
    leader = None
    last_t = time.perf_counter()
    last_obs_ok = time.time()
    smooth = 0.0

    while not S.stop:
        with S.lock:
            want_r, want_l = S.want_robot, S.want_leader

        # ── 로봇 연결 / 해제 ──
        if want_r and robot is None:
            try:
                robot = LeKiwiClient(LeKiwiClientConfig(remote_ip=PI_IP, id=ROBOT_ID))
                robot.connect()
                with S.lock:
                    S.robot_on, S.error = True, ""
            except Exception as e:
                robot = None
                with S.lock:
                    S.robot_on, S.error = False, f"로봇 연결 실패: {e}"
                # 로봇이 없어도 리더팔은 읽어야 하므로 continue 하지 않는다.
                # (예전엔 여기서 빠져나가 리더팔이 통째로 멈췄다)
                read_leader(leader)
                time.sleep(1.0)
        elif not want_r and robot is not None:
            try:
                robot.send_action(stop_action())
                time.sleep(0.1)
                robot.disconnect()
            except Exception:
                pass
            robot = None
            with S.lock:
                S.robot_on = False
            continue

        # ── 리더팔 연결 / 해제 ──
        if want_l and leader is None:
            port = find_leader_port()
            try:
                if not port:
                    raise RuntimeError("리더팔 포트를 못 찾음 (/dev/ttyACM*)")
                leader = SO101Leader(SO101LeaderConfig(port=port, id=LEADER_ID))
                leader.connect()
                with S.lock:
                    S.leader_on, S.leader_error = True, ""
            except Exception as e:
                leader = None
                with S.lock:
                    S.leader_on = False
                    S.leader_error = f"리더팔 연결 실패: {e}"
                    S.want_leader = False
                    if S.arm_mode == "leader":
                        S.arm_mode = "off"
        elif not want_l and leader is not None:
            try:
                leader.disconnect()
            except Exception:
                pass
            leader = None
            with S.lock:
                S.leader_on = False

        t0 = time.perf_counter()

        # ── 리더팔 읽기 (로봇 상태와 무관하게 항상 먼저) ──
        read_leader(leader)

        with S.lock:
            S.loop_count += 1

        if robot is None:
            time.sleep(0.2)
            continue

        # ── 관측 ──
        obs = None
        try:
            obs = robot.get_observation()
            if obs:
                last_obs_ok = time.time()
        except Exception as e:
            with S.lock:
                S.error = f"관측 실패: {e}"

        # ── 워치독: 관측이 한참 안 오면 끊긴 것으로 보고 다시 붙는다 ──
        age = time.time() - last_obs_ok
        with S.lock:
            S.obs_age = age
        if age > OBS_TIMEOUT:
            with S.lock:
                S.error = f"로봇 응답 없음({age:.0f}초) — 다시 연결하는 중"
                S.robot_on = False
                S.reconnects += 1
            try:
                robot.disconnect()
            except Exception:
                pass
            robot = None
            last_obs_ok = time.time()
            time.sleep(1.0)
            continue

        if not obs:
            time.sleep(0.05)
            continue

        if obs:
            cur = {k: v for k, v in obs.items() if k.startswith("arm_")}
            front = to_jpeg(obs.get("front"), rotate=FRONT_ROTATE)
            wrist = to_jpeg(obs.get("wrist"), rotate=WRIST_ROTATE)
            with S.lock:
                if cur:
                    S.arm_current = cur
                    if not S.arm_target:
                        S.arm_target = dict(cur)
                if front is not None:
                    S.frames["front"] = front
                if wrist is not None:
                    S.frames["wrist"] = wrist

        # ── 명령 만들기 ──
        now = time.perf_counter()
        with S.lock:
            fresh = (now - S.drive_stamp) < DRIVE_TIMEOUT
            d = dict(S.drive) if fresh else {"x": 0.0, "y": 0.0, "theta": 0.0}
            mode = S.arm_mode
            target = dict(S.arm_target)
            current = dict(S.arm_current)
            lead = dict(S.leader_pose)

        action = {"x.vel": d["x"], "y.vel": d["y"], "theta.vel": d["theta"]}

        # 로봇의 send_action 은 팔 목표값이 반드시 있어야 한다(없으면 sync_write 가 터짐).
        # 팔을 조종하지 않는 동안에는 '지금 자세'를 그대로 보내 제자리를 유지시킨다.
        if mode == "leader" and lead:
            arm_cmd = lead
        elif mode == "manual" and target:
            arm_cmd = target
        else:
            arm_cmd = current

        if arm_cmd:
            action.update({k: v for k, v in arm_cmd.items() if k.endswith(".pos")})

        if not any(k.endswith(".pos") for k in action):
            time.sleep(0.02)
            continue

        try:
            robot.send_action(action)
        except Exception as e:
            with S.lock:
                S.error = f"명령 전송 실패: {e}"

        dt = time.perf_counter() - last_t
        last_t = time.perf_counter()
        if dt > 0:
            smooth = smooth * 0.9 + (1.0 / dt) * 0.1
        with S.lock:
            S.fps_actual = smooth

        time.sleep(max(1.0 / FPS - (time.perf_counter() - t0), 0.0))

    # 종료 정리
    for dev in (robot, leader):
        try:
            if dev is robot and robot is not None:
                robot.send_action(stop_action())
                time.sleep(0.1)
            if dev is not None:
                dev.disconnect()
        except Exception:
            pass


def read_leader(leader):
    """리더팔 관절값을 읽어 공유 상태에 넣는다. 로봇 상태와 무관하게 호출한다."""
    if leader is None:
        return
    try:
        lp = {f"arm_{k}": v for k, v in leader.get_action().items()}
        with S.lock:
            S.leader_pose = lp
            S.leader_reads += 1
            S.leader_error = ""
    except Exception as e:
        with S.lock:
            S.leader_error = f"리더팔 읽기 실패: {e}"


def stop_action():
    with S.lock:
        cur = dict(S.arm_current)
    a = {"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0}
    a.update({k: v for k, v in cur.items() if k.endswith(".pos")})
    return a


ROT_MAP = {
    90:  cv2.ROTATE_90_COUNTERCLOCKWISE,   # 왼쪽으로 90도
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_CLOCKWISE,          # 오른쪽으로 90도
}


def to_jpeg(frame, rotate: int = 0):
    """관측 프레임을 JPEG 바이트로. LeKiwiClient 는 numpy 배열(RGB)로 준다."""
    if frame is None:
        return None
    try:
        if isinstance(frame, (bytes, bytearray)):
            if not rotate:
                return bytes(frame)
            img = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return bytes(frame)
        else:
            img = np.asarray(frame)
            if img.size == 0:
                return None
            if img.ndim == 3 and img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        if rotate in ROT_MAP:
            img = cv2.rotate(img, ROT_MAP[rotate])
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None
    except Exception:
        return None


# ─── 데스크탑 웹캠 ───────────────────────────────────────────────────
def desk_cam_loop():
    cap = cv2.VideoCapture(DESK_CAM)
    if not cap.isOpened():
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    try:
        while not S.stop:
            ok, img = cap.read()
            if not ok:
                time.sleep(0.1)
                continue
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with S.lock:
                    S.frames["desk"] = buf.tobytes()
            time.sleep(1.0 / 20)
    finally:
        cap.release()


# ─── 웹 ──────────────────────────────────────────────────────────────
def blank_frame(text="NO SIGNAL"):
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:] = (4, 12, 4)
    cv2.putText(img, text, (185, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 130, 40), 2)
    ok, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def mjpeg(name):
    boundary = b"--frame\r\n"
    while True:
        with S.lock:
            f = S.frames.get(name)
        if f is None:
            f = blank_frame()
            time.sleep(0.2)
        yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + f + b"\r\n"
        time.sleep(1.0 / 25)


@app.route("/stream/<name>")
def stream(name):
    if name not in ("front", "wrist", "desk"):
        return "없는 카메라", 404
    return Response(mjpeg(name), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/drive", methods=["POST"])
def api_drive():
    d = request.get_json(force=True, silent=True) or {}
    with S.lock:
        S.drive["x"] = float(d.get("x", 0.0))
        S.drive["y"] = float(d.get("y", 0.0))
        S.drive["theta"] = float(d.get("theta", 0.0))
        S.drive_stamp = time.perf_counter()
    return jsonify(ok=True)


@app.route("/api/connect", methods=["POST"])
def api_connect():
    d = request.get_json(force=True, silent=True) or {}
    tgt, on = d.get("target"), bool(d.get("on"))
    with S.lock:
        if tgt == "robot":
            S.want_robot = on
            if not on:
                S.arm_mode = "off"
        elif tgt == "leader":
            S.want_leader = on
            if on:
                S.leader_error = ""
            elif S.arm_mode == "leader":
                S.arm_mode = "off"
    return jsonify(ok=True)


@app.route("/api/arm", methods=["POST"])
def api_arm():
    d = request.get_json(force=True, silent=True) or {}
    with S.lock:
        if "mode" in d:
            m = d["mode"]
            if m in ("off", "manual", "leader"):
                if m == "leader" and not S.leader_on:
                    return jsonify(ok=False, msg="리더팔이 연결되지 않았어")
                S.arm_mode = m
                if m == "manual" and S.arm_current:
                    S.arm_target = dict(S.arm_current)   # 켤 때 현재 자세에서 시작
        for k, v in (d.get("joints") or {}).items():
            if k in JOINT_KEYS:
                S.arm_target[k] = float(v)
    return jsonify(ok=True)


@app.route("/api/pose")
def api_pose():
    """3D 트윈용. 관절값만 담아 가볍게 — 빠른 주기로 폴링해도 부담이 적다."""
    with S.lock:
        return jsonify(
            c={k: round(v, 2) for k, v in S.arm_current.items()},
            l={k: round(v, 2) for k, v in S.leader_pose.items()} if S.leader_on else {},
        )


def _pi_daemon_up():
    """Pi 의 호스트 데몬이 떠 있는지 확인한다."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", SSH_HOST,
             "pgrep -f lekiwi_host >/dev/null && echo UP || echo DOWN"],
            capture_output=True, text=True, timeout=15)
        return "UP" in r.stdout
    except Exception:
        return False


def _start_pi_daemon():
    """Pi 호스트 데몬을 백그라운드로 띄운다."""
    try:
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", SSH_HOST,
             "~/lekiwi_tools/run_host.sh -b"],
            capture_output=True, text=True, timeout=40)
        return True
    except Exception:
        return False


def _startup_worker():
    """버튼 하나로 로봇을 쓸 수 있는 상태까지 만든다."""
    def msg(t):
        with S.lock:
            S.startup_msg = t

    msg("Pi 데몬 확인 중...")
    if not _pi_daemon_up():
        msg("Pi 데몬 시작 중...")
        _start_pi_daemon()
        time.sleep(4)

    msg("로봇 연결 중...")
    with S.lock:
        S.want_robot = True
    for _ in range(30):
        time.sleep(0.5)
        with S.lock:
            if S.robot_on:
                break

    msg("리더팔 연결 중...")
    with S.lock:
        S.want_leader = True
    for _ in range(20):
        time.sleep(0.5)
        with S.lock:
            if S.leader_on:
                break

    with S.lock:
        ok_r, ok_l = S.robot_on, S.leader_on
    msg("준비 완료" if (ok_r and ok_l)
        else f"일부 실패 (로봇 {'O' if ok_r else 'X'} / 리더팔 {'O' if ok_l else 'X'})")
    time.sleep(4)
    msg("")


@app.route("/api/startup", methods=["POST"])
def api_startup():
    threading.Thread(target=_startup_worker, daemon=True).start()
    return jsonify(ok=True)


@app.route("/api/state")
def api_state():
    with S.lock:
        return jsonify(
            connected=S.robot_on,
            leader_connected=S.leader_on,
            want_robot=S.want_robot,
            want_leader=S.want_leader,
            arm_mode=S.arm_mode,
            error=S.error,
            leader_error=S.leader_error,
            fps=round(S.fps_actual, 1),
            leader_reads=S.leader_reads,
            obs_age=round(S.obs_age, 1),
            reconnects=S.reconnects,
            startup_msg=S.startup_msg,
            loop_count=S.loop_count,
            arm_current={k: round(v, 2) for k, v in S.arm_current.items()},
            arm_target={k: round(v, 2) for k, v in S.arm_target.items()},
            leader_pose={k: round(v, 2) for k, v in S.leader_pose.items()},
            joints=[{"key": k, "label": lab, "urdf": u} for k, lab, u in ARM_JOINTS],
        )


@app.route("/")
def index():
    return send_from_directory(HERE, "lekiwi_web.html")


@app.route("/static/<path:fname>")
def static_file(fname):
    """three.js·STL 등을 로컬에서 제공(인터넷 없어도 되게).

    STL 은 한 번 받으면 바뀌지 않으므로 브라우저에 오래 캐시시킨다.
    (캐시가 없으면 새로고침마다 38개를 다시 파싱하느라 몇십 초가 걸린다)
    """
    static_dir = os.path.join(HERE, "static")
    if fname.lower().endswith((".stl", ".js")):
        return send_from_directory(static_dir, fname, max_age=86400)
    return send_from_directory(static_dir, fname)


@app.after_request
def _cache_static(resp):
    """STL·JS 는 내용이 바뀌지 않으니 브라우저에 하루 캐시시킨다.
    (캐시가 없으면 새로고침마다 메시 38개를 다시 파싱해 수십 초가 걸린다)"""
    if request.path.startswith("/static/") and request.path.endswith((".stl", ".js")):
        resp.headers["Cache-Control"] = "public, max-age=86400"
        resp.headers.pop("Expires", None)
    return resp


def main():
    threading.Thread(target=robot_loop, daemon=True).start()
    threading.Thread(target=desk_cam_loop, daemon=True).start()
    print(f"웹 GUI: http://localhost:{WEB_PORT}   (로봇 {PI_IP})")
    try:
        app.run(host="0.0.0.0", port=WEB_PORT, threaded=True, debug=False)
    finally:
        S.stop = True
        time.sleep(0.5)


if __name__ == "__main__":
    main()
