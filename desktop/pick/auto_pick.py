"""LeKiwi 자율 색깔 블록 집기 → 보관함 넣기.

  찾기(제자리 회전) → 다가가기(배캠) → 손목캠에 보이면 넘겨받기 → 바퀴로 기준점 맞추기
  → 집기(가르친 자세) → 집었는지 확인 → 마커 찾기(회전) → 보관함 앞 접근 → 넣기 → 반복

팔은 poses.json 에 저장한 자세(look / pick / drop)만 쓰고, 위치 맞추기는 옴니휠로 한다.
웹 서버(lekiwi_web.py)를 거쳐 명령하므로 동작 중에도 브라우저로 화면을 볼 수 있다.

사용법:  python auto_pick.py red yellow        (색을 안 주면 red yellow)
         python auto_pick.py red --once        (한 개만 집고 끝)
         python auto_pick.py red yellow --sort (빨강 → 보관함 A, 노랑 → 보관함 B)
"""
import json
import os
import sys
import time

import cv2
import numpy as np

from approach_marker import find_marker, find_markers, front_spot, BOX_IDS, F_PX
from color_detect import block_size_ok, detect, rises_above, roi_px
from robot_api import Cam, arm_mode, arm_now, arm_target, drive, drive_for, move_to, stop

HERE = os.path.dirname(os.path.abspath(__file__))
ALL_IDS = tuple(i for ids in BOX_IDS.values() for i in ids)
POSES = os.path.join(HERE, "poses.json")
LOGDIR = os.path.join(HERE, "logs", time.strftime("%Y%m%d_%H%M%S"))
G = "arm_gripper.pos"

# 주행 속도 (느리게 시작. 2026-10-05 방향 실측: x+ 전진 / y+ 왼쪽 / theta+ 반시계)
V_FWD = 0.06
CARRY_SCALE = 1.0       # 블록을 들고 있을 때 바퀴 속도 배율 (사용자: 바퀴는 그대로, 팔만 천천히)
TURN_SEARCH = 20.0      # 찾을 때 회전 속도(도/초). theta 명령 1초 = 실측 약 15.2°/15 → 거의 정확
K_TURN = 0.08           # 배캠 x 오차(px) → 회전속도
ALIGN_TOL = 10          # 손목캠 기준점 허용 오차(px)
ALIGN_V = 0.04          # 미세 이동 속도


TRIALS = os.path.join(HERE, "trials.csv")   # 성공률 기록 (한 블록 = 한 줄)
_events = []


def log(*a):
    msg = " ".join(str(x) for x in a)
    _events.append(msg)
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def record_trial(color, result, sec):
    """한 블록 처리 결과를 trials.csv 에 덧붙인다. 'confirmed' 칸은 사람이 눈으로 확인한 결과(나중에 채움)."""
    import csv
    ev = " | ".join(_events)
    stage = lambda key: "Y" if key in ev else ""
    new = not os.path.exists(TRIALS)
    with open(TRIALS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "time", "color", "result", "sec", "found", "grasp_ok", "grasp_retry",
                        "box_found", "squared", "dropped", "confirmed", "note", "logdir"])
        w.writerow([time.strftime("%Y-%m-%d"), time.strftime("%H:%M:%S"), color, result, round(sec),
                    stage("발견"), stage("집기 성공"), ev.count("다시 시도"), stage("보관함 마커 발견") or stage("보관함 마커 바로"),
                    stage("정면 맞춤 완료"), stage("넣기 완료"), "", "", os.path.basename(LOGDIR)])
    _events.clear()


def save(name, img):
    os.makedirs(LOGDIR, exist_ok=True)
    cv2.imwrite(os.path.join(LOGDIR, f"{time.strftime('%H%M%S')}_{name}.jpg"), img)


class Picker:
    def __init__(self, colors):
        self.colors = colors
        self.P = json.load(open(POSES))
        self.front, self.wrist = Cam("front"), Cam("wrist")
        self.glimpse = None
        self.box = "A"
        self.sort = {}                      # 색 → 보관함 (예: {"red": "A", "yellow": "B"}). 비면 모두 A
        self.carry(False)
        time.sleep(1.0)

    def fm(self, img, upscale=True):
        """지금 목표 보관함(self.box)의 네 면 마커 중 하나를 찾는다."""
        return find_marker(img, ids=BOX_IDS[self.box], upscale=upscale)

    def carry(self, on):
        """블록을 들고 있는 동안은 바퀴를 60% 속도로(사용자 요청 2026-10-06: '확확 움직인다')."""
        self.f = CARRY_SCALE if on else 1.0
        self.ts, self.v = TURN_SEARCH * self.f, V_FWD * self.f

    # ── 공통 ──────────────────────────────────────────────
    def snap(self, cam, settle=0.0):
        t = time.time() + settle
        if settle:
            time.sleep(settle)
        return cam.get(newer_than=t, timeout=3)

    def save_poses(self):
        json.dump(self.P, open(POSES, "w"), indent=1, ensure_ascii=False)

    def pose(self, name, grip=None, sec=2.5):
        """저장한 자세(fold/look/home/drop...)로 옮긴다. grip 을 주면 그리퍼는 그 값으로 유지."""
        p = dict(self.P[name])
        p[G] = arm_now()[G] if grip is None else grip
        move_to(p, sec=sec)

    def look(self, grip=None, sec=2.5):
        pose = dict(self.P["look"])
        pose[G] = arm_now()[G] if grip is None else grip
        move_to(pose, sec=sec)

    def front_blocks(self, img):
        """배캠에서 목표 색 블록. 보관함(A · B 모두) 안에 든 것은 뺀다."""
        dets = detect(img, colors=self.colors, roi=roi_px("front", img.shape), cam="front")
        dets = [d for d in dets if block_size_ok(d, img.shape)]     # 봉지 · 장난감처럼 크기가 안 맞는 것 제외
        top_y = min(y for _, y in roi_px("front", img.shape))
        dets = [d for d in dets if not rises_above(img, d, top_y, cam="front")]   # 벽에 기댄 봉지 아래끝 제외
        for box_ids in BOX_IDS.values():
            m = find_marker(img, ids=box_ids, upscale=False)   # 가까운 보관함만 문제라 확대 검출은 생략
            if m:   # 투명 보관함 안 블록 제외: 마커 좌우 2.6칸, 위아래로 상자 높이 안
                s = m["side"]
                dets = [d for d in dets if not (abs(d["cx"] - m["cx"]) < 2.6 * s
                                                and m["cy"] - 1.5 * s < d["cy"] < m["cy"] + 1.8 * s)]
        return dets

    def wrist_block(self, img):
        dets = detect(img, colors=self.colors, roi=roi_px("wrist", img.shape), cam="wrist")
        dets = [d for d in dets if d["area"] > 300]
        return dets[0] if dets else None

    # ── 그리퍼 빈손 기준 (처음 한 번만) ─────────────────────
    def calib_empty_grip(self):
        if "grip_empty" in self.P:
            return
        log("그리퍼 빈손으로 끝까지 닫히는 값 측정")
        g0 = arm_now()[G]
        last = g0
        for tgt in np.arange(g0 + 4, 101, 4):
            arm_target({G: float(tgt)}); time.sleep(0.25)
            last = arm_now()[G]
            if tgt - last > 6:
                break
        self.P["grip_empty"] = round(last, 1)
        log(f"  빈손 끝 = {last:.1f} (블록 물림 ≈ {self.P['grip_closed_on_block']})")
        move_to({G: g0}, sec=1.0, keys=[G])
        self.save_poses()

    # ── ① 찾기: 가까운 쪽부터 좌우로 훑고, 없으면 한 바퀴 ─────────
    #  오른쪽 45° → 왼쪽으로 90°(왼쪽 45°까지) → 계속 왼쪽으로 270°(한 바퀴 채움)
    #  예전엔 왼쪽으로만 돌아서, 오른쪽 살짝 옆 블록도 300° 돌아 찾았음(2026-10-05)
    SWEEP = [(-1, 45), (+1, 90), (+1, 270)]     # (방향: -1 오른쪽 / +1 왼쪽, 각도)

    def search(self, finder, what):
        img = self.snap(self.front, settle=0.3)
        if found := finder(img):
            log(f"{what} 바로 보임")
            return found
        self.glimpse = None
        for sign, deg in self.SWEEP:
            # 시간이 아니라 '실제로 돈 각도'로 센다. 예전엔 잠깐 보인 것 쪽으로 되돌아가 보는 동안에도
            # 시간이 흘러, 보관함 안 블록(돌 땐 마커가 흐려 못 걸러냄)에 계속 낚여 양쪽으로 왔다 갔다만 하고
            # 한 바퀴를 못 돌았다(2026-10-06 19:12, 뒤 180°에 있던 빨간 블록을 못 찾음).
            turned, ignore_until, t_prev = 0.0, -1.0, time.time()
            t = time.time()
            while turned < deg:
                drive(theta=sign * self.ts)
                img = self.front.get(newer_than=t); t = time.time()
                turned += self.ts * min(t - t_prev, 0.3); t_prev = t
                g = finder(img)
                if g and turned > ignore_until:
                    stop()
                    # 도는 중 본 화면은 살짝 늦으므로 멈춘 뒤 다시 보고 확정
                    if found := finder(self.snap(self.front, settle=0.4)):
                        log(f"{what} 발견 (돌다가 멈춰서 확인)")
                        return found
                    # 사용자 제안(2026-10-06): 잠깐 보였던 자리를 기억해 두고 그쪽으로 되돌아가 본다.
                    self.glimpse = (sign, g["cx"])
                    if found := self.toward_glimpse(finder, what):
                        return found
                    # 없으면 되돌아간 만큼 다시 돌려 놓고, 그 근처 30° 는 또 낚이지 않게 무시
                    if abs(self.glimpse_back) > 1:
                        drive_for(theta=-np.sign(self.glimpse_back) * self.ts, sec=abs(self.glimpse_back) / self.ts)
                    ignore_until = turned + 30
                    t_prev = t = time.time()
            stop()
        log(f"{what} 못 찾음 (좌우 훑고 한 바퀴 돌았음)")
        return None

    def toward_glimpse(self, finder, what, deg_per_px=180 / np.pi / F_PX):
        """잠깐 보였던 마커 쪽으로 되돌아 돌고, 좌우로 조금씩 살핀다.
        화면 중심에서 벗어난 만큼 + 멈추는 사이 더 돈 만큼(약 6°) 되돌린다."""
        sign, cx = self.glimpse
        back = (320 - cx) * deg_per_px - sign * 6.0          # +면 왼쪽으로 돌기
        self.glimpse_back = back                              # 못 찾으면 search 가 이만큼 되돌린다
        steps = [back, 8, -16, 8]                             # 기억한 곳 → 왼쪽 8 → 오른쪽 8 → 제자리
        for d in steps:
            if abs(d) > 1:
                drive_for(theta=np.sign(d) * self.ts, sec=abs(d) / self.ts)
            if found := finder(self.snap(self.front, settle=0.45)):
                log(f"{what} 발견 (잠깐 보였던 쪽으로 되돌아가서)")
                return found
        return None

    def creep_toward(self, finder, what, steps=3):
        """마커가 너무 작아 안 읽히면, 마지막으로 보였던 쪽을 향해 20cm 씩 다가가며 본다."""
        for k in range(steps):
            drive_for(x=self.v, sec=0.20 / self.v)
            if found := finder(self.snap(self.front, settle=0.45)):
                log(f"{what} 발견 ({20 * (k + 1)}cm 다가가서)")
                return found
            if found := self.toward_glimpse(finder, what):
                return found
        return None

    # ── ② 블록으로 다가가기 → 손목캠에 보이면 정지 ───────────
    def approach_block(self, first, timeout=40):
        """팔을 접은 채 배캠으로 다가가다가, 블록이 화면 아래 정지선(stop_y)까지 오면 멈춘다.
        그다음 팔을 보기 자세로 펴서 손목캠이 넘겨받는다. 손목캠에 안 보이면 천천히 앞으로."""
        stop_y = self.P.get("stop_y", 400)
        tx, ty = first["cx"], first["cy"]
        t0 = last_seen = time.time()
        while time.time() - t0 < timeout:
            img = self.snap(self.front)
            dets = self.front_blocks(img)
            if dets:   # 직전 위치에서 가장 가까운 블록을 계속 쫓는다(다른 블록으로 갈아타기 방지)
                d = min(dets, key=lambda d: (d["cx"] - tx) ** 2 + (d["cy"] - ty) ** 2)
                # 크게 도는 중에는 블록이 화면에서 많이 움직이므로 허용 거리를 넓힌다
                near = 200 if abs(tx - img.shape[1] / 2) > 120 else 120
                if (d["cx"] - tx) ** 2 + (d["cy"] - ty) ** 2 < near ** 2:
                    tx, ty, last_seen = d["cx"], d["cy"], time.time()
            err = tx - img.shape[1] / 2
            seen = time.time() - last_seen < 0.5
            if seen and ty >= stop_y and abs(err) < 70:
                stop(); log(f"정지선 도착 (배캠 y {ty:.0f} ≥ {stop_y}) → 팔 펴기")
                break
            if seen:
                th = float(np.clip(-K_TURN * err, -15 * self.f, 15 * self.f))
                drive(x=V_FWD if abs(err) < 70 else 0.0, theta=th)
            elif ty > 300 and time.time() - last_seen < 3.0:
                stop(); log("블록이 배캠 아래로 사라짐(가까움) → 팔 펴기")
                break
            elif time.time() - last_seen >= 3.0:
                stop(); log("블록을 놓침"); return False
        else:
            stop(); log("다가가기 시간 초과"); return False
        self.look(grip=self.P["look"][G], sec=2.5)
        t1 = time.time()
        while time.time() - t1 < 4.0:
            w = self.wrist_block(self.snap(self.wrist, settle=0.1))
            if w:
                stop(); log(f"손목캠이 블록을 봄 → 넘겨받기 ({w['cx']:.0f},{w['cy']:.0f})")
                return True
            drive(x=0.03)
        stop(); log("팔을 폈는데 손목캠에 블록이 안 보임"); return False

    # ── ③ 손목캠 기준점 맞추기 (바퀴로) ──────────────────────
    def calib_wrist_jacobian(self):
        """x·y 로 살짝 움직여 손목캠에서 블록이 몇 px 움직이는지 잰다(처음 한 번)."""
        if "wrist_jac" in self.P:
            return True
        log("손목캠 이동량 측정(처음 한 번): 앞뒤·좌우로 3cm씩")
        J = []
        for cmd in ({"x": ALIGN_V}, {"y": ALIGN_V}):
            a = self.wrist_block(self.snap(self.wrist, settle=0.4))
            drive_for(sec=0.75, **cmd)
            b = self.wrist_block(self.snap(self.wrist, settle=0.5))
            drive_for(sec=0.75, **{k: -v for k, v in cmd.items()})
            if not (a and b):
                log("  측정 중 블록을 놓침"); return False
            J.append([(b["cx"] - a["cx"]) / 0.03, (b["cy"] - a["cy"]) / 0.03])   # px / m
            log(f"  {list(cmd)[0]} +3cm → 화면 ({b['cx']-a['cx']:+.0f}, {b['cy']-a['cy']:+.0f})px")
        self.P["wrist_jac"] = np.array(J).T.round(1).tolist()   # [[dcx/dx, dcx/dy],[dcy/dx, dcy/dy]]
        self.save_poses()
        return True

    def refind_wrist(self, back=True):
        """손목캠에서 블록을 놓쳤을 때: 세 번 다시 보고, 없으면 3cm 물러났다가 다시 본다.
        물러나기는 한 블록에 한 번만(2026-10-06 20:17 놓쳤다 찾았다 하며 3cm 씩 열 번 넘게 물러남)."""
        for _ in range(3):
            if w := self.wrist_block(self.snap(self.wrist, settle=0.3)):
                return w
        if not back:
            return None
        drive_for(x=-ALIGN_V, sec=0.75)
        for _ in range(3):
            if w := self.wrist_block(self.snap(self.wrist, settle=0.3)):
                log("  물러나서 블록 다시 찾음"); return w
        return None

    def align(self, max_iter=14):
        tgt = np.array(self.P["target_px"])
        Jinv = np.linalg.pinv(np.array(self.P["wrist_jac"]))
        backed = False
        for i in range(max_iter):
            w = self.wrist_block(self.snap(self.wrist, settle=0.4))
            if not w:
                # 한 장면 놓쳤다고 바로 포기하지 않는다(2026-10-06 넘겨받은 직후 한 번 안 보여 실패)
                w = self.refind_wrist(back=not backed); backed = True
                if not w:
                    log("정렬 중 블록이 손목캠에서 사라짐 (다시 보고 물러나도 없음)"); return False
            e = np.array([w["cx"], w["cy"]]) - tgt
            if np.abs(e).max() < ALIGN_TOL:
                log(f"정렬 완료 ({i}번, 오차 {e.round(0)}px)")
                return True
            dx, dy = (-Jinv @ e) * 0.7          # 0.7배만 움직여 넘치지 않게
            dist = float(np.hypot(dx, dy))
            dur = float(np.clip(dist / ALIGN_V, 0.12, 1.5))
            drive_for(x=dx / dist * ALIGN_V, y=dy / dist * ALIGN_V, sec=dur)
        log("정렬 실패(반복 초과)"); return False

    # ── ④ 집기 + 확인 ─────────────────────────────────────
    def grasp(self):
        open_g = self.P["look"][G]
        pick = dict(self.P["pick"]); pick[G] = open_g
        move_to(pick, sec=2.5); time.sleep(0.4)
        g = arm_now()[G]
        for tgt in np.arange(g + 3, 101, 3):
            arm_target({G: float(tgt)}); time.sleep(0.22)
            real = arm_now()[G]
            if tgt - real > 6:
                break
        held = arm_now()[G]
        self.carry(True)
        self.look(grip=held + 4, sec=4.5)          # 블록 들고 들어 올리기: 천천히
        time.sleep(0.4)
        img = self.snap(self.wrist, settle=0.3)
        save("grasp", img)
        w = self.wrist_block(img)
        empty = self.P.get("grip_empty", 100)
        ok = held < empty - 8 and w is not None and w["area"] > 6000
        log(f"집기 {'성공' if ok else '실패'}: 그리퍼 {held:.1f} (빈손 {empty}), "
            f"손목캠 블록 면적 {w['area'] if w else 0}")
        if not ok:
            self.carry(False)
            move_to({G: open_g}, sec=0.8, keys=[G])
        return ok, held

    # ── ⑤ 보관함 ──────────────────────────────────────────
    def search_still(self, finder, what, step_deg=15):
        """멈춰서 보기 방식: step_deg 씩 돌고 멈춘 뒤 또렷한 화면으로 찾는다(작은 마커용).
        오른쪽 45° → 왼쪽 45° → 계속 왼쪽으로 한 바퀴, search() 와 같은 순서."""
        plan = [-1] * 3 + [+1] * 6 + [+1] * 18      # 15°씩: 오른쪽 45 · 왼쪽 90 · 왼쪽 270
        turned = 0
        for k in range(len(plan) + 1):
            img = self.snap(self.front, settle=0.45)
            if found := finder(img):
                log(f"{what} 발견 (약 {turned:+d}°, 멈춰서 보기)")
                return found
            if k == len(plan):
                break
            drive_for(theta=plan[k] * self.ts, sec=step_deg / self.ts)
            turned += plan[k] * step_deg
        log(f"{what} 못 찾음 (멈춰서 보기로 한 바퀴)")
        return None

    def go_to_box(self, timeout=60):
        m = self.search(self.fm, "보관함 마커")
        if not m and self.glimpse:                 # 잠깐 보였던 쪽이 있으면 그리로 다가가며 찾기
            m = self.creep_toward(self.fm, "보관함 마커")
        if not m:
            m = self.search_still(self.fm, "보관함 마커")
        if not m:
            return False
        want = self.P["drop_marker"]
        # ① 멀리서 1.13m 까지  ② 거기서 정면 0.40m 지점으로 곧장(보관함 앞 장애물을 돌아가도록 일찍 꺾음)
        # (거리 숫자는 2026-10-07 렌즈 보정 후 실제 m. 예전 1.4 · 0.5 와 같은 자리)
        # ③ 정면에서 넣는 거리까지
        if not self._approach_marker(1.13, timeout):
            return False
        if not self.square_up():
            return False
        return self._approach_marker(want["dist"], 30, final=True)

    def _approach_marker(self, stop_dist, timeout, final=False):
        want = self.P["drop_marker"]
        t0, last_seen, last_dist, last_cmd = time.time(), time.time(), 0.0, (0.0, 0.0)
        while time.time() - t0 < timeout:
            img = self.snap(self.front)
            m = self.fm(img)
            if m:
                last_seen, last_dist, self.last_face = time.time(), m["dist"], m["id"]
                err = m["cx"] - (want["cx"] if final else img.shape[1] / 2)
                if m["dist"] <= stop_dist and abs(err) < 12:
                    stop()
                    log(f"{'보관함 앞 도착' if final else f'{stop_dist}m 지점 도착'} (거리 {m['dist']:.3f}m, 좌우 {err:+.0f}px, 각도 {m['yaw']:+.1f}°)")
                    return True
                th = float(np.clip(-K_TURN * err, -15 * self.f, 15 * self.f))
                # 멀어서 마커가 작으면(25px 미만) 천천히: 흔들리면 작은 마커를 놓친다(2026-10-06)
                v = self.v if m["side"] >= 25 else 0.035 * self.f
                x = v if (m["dist"] > stop_dist and abs(err) < 60) else 0.0
                # 마지막 구간에서도 비스듬해지면 조금씩 옆으로 바로잡는다
                y = float(np.clip(-0.002 * m["yaw"], -0.02, 0.02)) if final and m["yaw"] is not None else 0.0
                drive(x=x, y=y, theta=th)
                last_cmd = (x, y)
            elif last_dist > 1.2 and time.time() - last_seen < 2.0:
                # 멀면 작은 마커가 세 장에 한 장꼴로만 읽힌다(2026-10-06 저녁 3m) → 2초까지는 하던 대로 직진
                drive(x=last_cmd[0], y=0.0, theta=0.0)
            elif time.time() - last_seen > 0.6:
                stop()
                m = self.relook()
                if not m and last_dist > 1.2:
                    # 3m 쯤에선 3.5cm 마커가 12px 라 보였다 말았다 한다(2026-10-06) → 그쪽으로 조금씩 다가가 본다
                    m = self.creep_toward(self.fm, "보관함 마커")
                if not m:
                    log("마커를 놓침 (멈춰서 다시 보고 좌우로 찾아도 없음)"); return False
                last_seen = time.time()
        stop(); log("보관함 접근 시간 초과"); return False

    def square_up(self, dist=0.40, tol=6.0, timeout=40):
        """보관함 면 정면 dist(m) 지점으로 곧장 간다(몸은 마커를 바라본 채 앞 · 옆 동시에).

        예전엔 0.5m 까지 똑바로 간 뒤 옆걸음으로 크게 돌아 정면을 맞췄는데, 보관함 옆이 울타리면
        거기에 박았다(2026-10-06 저녁). 사용자 제안: 발견했을 때 마커 yaw 로 정면 지점을 계산해 그리로.
        매 장면마다 다시 계산하니 가까워질수록 정확해진다.
        그래도 그 지점이 벽 너머면 못 가므로, 3초 동안 2cm 도 못 가까워지면 보였던 다른 면으로 바꾼다."""
        t0, good = time.time(), 0
        face, tried, seen = None, set(), set()
        best, t_best, spots = 9.9, time.time(), []
        yaw, t_seen = 0.0, time.time()
        while time.time() - t0 < timeout:
            img = self.snap(self.front)
            ms = [m for m in find_markers(img, ids=BOX_IDS[self.box]) if m.get("t") is not None]
            seen |= {m["id"] for m in ms}
            if face is None and ms:
                # 멀리서부터 따라온 면이 보이면 그 면(방향이 안 뒤집힘), 아니면 덜 돌아가도 되는 면
                ids = [m["id"] for m in ms]
                face = (self.last_face if getattr(self, "last_face", None) in ids
                        else min(ms, key=lambda m: np.hypot(*front_spot(m, dist)))["id"])
                log(f"  {face}번 면 정면으로 가기 시작")
            m = next((m for m in ms if m["id"] == face), None)
            if not m and time.time() - t_seen < 1.0:
                continue                                    # 한두 장 안 읽힌 건 하던 대로 계속
            if not m:
                stop()
                # 다른 면이 보여도 소용없다: 지금 맞추는 면만 다시 찾는다
                one = lambda im: next((x for x in find_markers(im, ids=BOX_IDS[self.box]) if x["id"] == face), None)
                if not self.relook(one):
                    log(f"정면 찾아가다 {face}번 면을 놓침"); return False
                t_seen = time.time()
                continue
            t_seen = time.time()
            spots = (spots + [front_spot(m, dist)])[-5:]   # 멀면 각도가 가끔 뒤집혀 나와 5장 중간값
            fwd, left = np.median(spots, axis=0)          # 한 장면 튀는 값 무시
            yaw, err, gap = m["yaw"], m["cx"] - img.shape[1] / 2, float(np.hypot(fwd, left))
            now = time.time()
            if gap < best - 0.02:
                best, t_best = gap, now
            if gap < 0.032 and abs(yaw) < tol and abs(err) < 25:
                good += 1
                if good >= 3:
                    stop(); log(f"정면 맞춤 완료 ({face}번 면, 각도 {yaw:+.1f}°, 거리 {m['dist']:.2f}m)")
                    return True
            else:
                good = 0
            if now - t_best > 3.0:
                stop()
                tried.add(face)
                others = seen - tried
                if not others:
                    log(f"정면 맞추기 포기: {face}번 면 앞으로 못 감 (남은 거리 {gap * 100:.0f}cm)"); return False
                face = others.pop()
                log(f"  3초째 안 가까워짐 → 막힌 것 같아 {face}번 면으로 바꿈")
                spots, good, best, t_best = [], 0, 9.9, time.time()
                continue
            v = min(0.05 * self.f, 0.5 * gap)               # 가까워질수록 천천히
            x, y = (fwd / gap * v, left / gap * v) if gap > 1e-3 else (0.0, 0.0)
            if m["side"] < 25:
                # 1m 넘게 멀면 각도가 부정확해(뒤집혀 나오기도) 정면 지점이 엉뚱하게 뒤로 잡힌다
                # (2026-10-06 18:37 뒤로 0.8m 물러남) → 그땐 옆으로만 살짝, 앞으로는 다가가기만
                x, y = max(x, 0.02), float(np.clip(y, -0.02, 0.02))
            x = max(x, -0.02)                               # 뒤엔 카메라가 없으니 크게 물러나지 않기
            th = float(np.clip(-K_TURN * err, -15 * self.f, 15 * self.f))   # 몸은 계속 마커를 향하게
            drive(x=float(x), y=float(y), theta=th)
        stop(); log(f"정면 맞추기 시간 초과 (마지막 각도 {yaw:+.1f}°)"); return False

    def relook(self, finder=None):
        """마커를 잠깐 놓쳤을 때: 멈춰서 다시 보고, 없으면 좌우로 10°씩 살짝 돌며 찾는다."""
        finder = finder or self.fm
        for turn in (0, -10, +20, -10):            # 제자리 → 오른쪽 10 → 왼쪽 10 → 원위치
            if turn:
                drive_for(theta=np.sign(turn) * self.ts, sec=abs(turn) / self.ts)
            m = finder(self.snap(self.front, settle=0.45))
            if m:
                log(f"  마커 다시 찾음 (거리 {m['dist']:.2f}m)")
                return m
        return None

    def drop(self, held):
        pose = dict(self.P["drop"]); pose[G] = held + 4
        move_to(pose, sec=5.0); time.sleep(0.6)        # 블록 든 채 넣기 자세로: 천천히
        move_to({G: self.P["look"][G]}, sec=0.8, keys=[G]); time.sleep(0.8)
        save("drop", self.snap(self.wrist))
        self.carry(False)
        self.pose("fold", grip=self.P["look"][G], sec=3.0)
        log("넣기 완료")

    # ── 블록 들고 있는지 ──────────────────────────────────
    def holding(self):
        """그리퍼 값: 벌림 약 8.5 · 블록 쥠 약 45 · 빈손으로 끝까지 닫힘 94.5 → 그 사이면 블록을 쥔 것."""
        g = arm_now()[G]
        return self.P["look"][G] + 20 < g < self.P.get("grip_empty", 94.5) - 8

    def free_grip(self):
        """팔을 옮길 때 쓸 그리퍼 값: 빈손이면 벌린 값, 블록을 들고 있으면 지금 값 그대로.
        2026-10-06: 실패 뒤 홈 자세로 가며 그리퍼를 벌려 들고 있던 블록을 떨어뜨림 → 여는 곳은 전부 이걸 거친다."""
        return arm_now()[G] if self.holding() else self.P["look"][G]

    # ── 전체 ──────────────────────────────────────────────
    def run_one(self):
        if self.holding():
            # 지난 판이 블록을 든 채 끝났으면 블록 찾기 말고 보관함부터
            held = arm_now()[G] - 4
            self.last_color = getattr(self, "last_color", "red")
            log(f"블록을 들고 있음 (그리퍼 {held + 4:.1f}) → 보관함부터")
            self.pose("fold", grip=held + 4, sec=3.0)
            return self.deliver(held)
        self.pose("fold", grip=self.P["look"][G], sec=2.5)   # 찾고 다가가는 동안 팔은 접는다
        first = self.search(lambda img: (self.front_blocks(img) or [None])[0], "블록")
        if not first:
            return "없음"
        log(f"  목표: {first['color']} ({first['cx']:.0f},{first['cy']:.0f})")
        self.last_color = first["color"]
        if not self.approach_block(first):
            return "실패"
        if not self.calib_wrist_jacobian():
            return "실패"
        # 손목캠에 보관함 마커가 같이 보이면 보관함에 붙은 블록 → 집지 않는다.
        # (2026-10-06 보관함 바로 옆 블록을 집으려다 그리퍼가 보관함 모서리를 물었음)
        if find_marker(self.snap(self.wrist, settle=0.2), ids=ALL_IDS, upscale=False):
            log("블록이 보관함에 붙어 있어 건너뜀 (그리퍼가 보관함에 걸릴 수 있음)")
            self.pose("fold", grip=self.P["look"][G], sec=2.0)
            drive_for(x=-V_FWD, sec=2.0)
            return "건너뜀"
        for attempt in range(3):
            if not self.align():
                return "실패"
            ok, held = self.grasp()
            if ok:
                break
            log(f"다시 시도 ({attempt + 1}/2)")
        else:
            return "실패"
        self.pose("fold", grip=held + 4, sec=4.5)        # 블록 문 채로 접고 이동 (천천히)
        self.box = self.sort.get(self.last_color, "A")     # 색깔별 분류: 이 색이 갈 보관함
        log(f"  {self.last_color} → 보관함 {self.box}")
        if arm_now()[G] > self.P["grip_empty"] - 8:
            log("접는 중에 블록을 놓침"); return "실패"
        return self.deliver(held)

    def deliver(self, held):
        """블록을 든 채 보관함을 찾아 넣고, 물러나 돌아선다."""
        for k in range(3):                       # 블록을 든 채 포기하지 않는다: 보관함 찾기 3번까지
            if self.go_to_box():
                break
            if k < 2:
                log(f"보관함 다시 찾기 ({k + 2}/3): 조금 물러나서 다시")
                drive_for(x=-V_FWD, sec=2.0)
        else:
            return "실패"
        self.drop(held)
        # 보관함은 보통 벽 앞이라 넣은 자리에서 돌면 시야가 막힌다(2026-10-06 쿠션에 가려 못 찾음).
        # 충분히 물러난 뒤(약 18cm) 몸을 180° 돌려 트인 쪽을 보고 다음 블록을 찾는다.
        drive_for(x=-V_FWD, sec=3.0)
        drive_for(theta=self.ts, sec=180 / self.ts)
        return "성공"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    colors = args or ["red", "yellow"]
    once = "--once" in sys.argv
    pk = Picker(colors)
    if "--sort" in sys.argv:                 # 색깔별 분류: 빨강 → 보관함 A, 노랑 → 보관함 B
        pk.sort = {"red": "A", "yellow": "B"}
        log("색깔별 분류: 빨강 → 보관함 A, 노랑 → 보관함 B")
    log(f"시작: 목표 색 {colors}  (로그 사진 {LOGDIR})")
    arm_mode("manual"); time.sleep(0.4)
    if "--holding" in sys.argv:              # 이미 블록을 든 상태에서 넣기만(2026-10-06 정면 맞추기 시험용)
        held = arm_now()[G]
        log(f"블록 든 상태로 시작 (그리퍼 {held:.1f}) → 보관함 A 로")
        t_one = time.time()
        try:
            pk.carry(True)
            pk.pose("fold", grip=held + 4, sec=4.5)   # 그리퍼는 닫은 채 그대로
            ok = pk.go_to_box()
            if ok:
                pk.drop(held)
                drive_for(x=-V_FWD, sec=3.0)
            r = "성공" if ok else "실패"
        except KeyboardInterrupt:
            stop(); log("사용자 중단"); return
        log(f"결과: {r}")
        record_trial("red", r, time.time() - t_one)
        stop(); return
    try:
        pk.look(grip=pk.free_grip(), sec=2.5)
        pk.calib_empty_grip()
        # 보관함 바로 앞에서 시작하면 벽에 막혀 못 찾는다 → 물러나서 돌아선 뒤 시작(2026-10-06)
        m = find_marker(pk.snap(pk.front, settle=0.3), ids=ALL_IDS)
        if m and m["dist"] < 0.48:
            log(f"보관함이 {m['dist']:.2f}m 앞이라 물러나서 돌아섬")
            pk.pose("fold", grip=pk.free_grip(), sec=2.5)
            drive_for(x=-V_FWD, sec=3.0)
            drive_for(theta=TURN_SEARCH, sec=180 / TURN_SEARCH)
        n, fails = 0, 0
        while True:
            t_one = time.time()
            r = pk.run_one()
            log(f"결과: {r}")
            if r != "없음":
                record_trial(getattr(pk, "last_color", ""), r, time.time() - t_one)
            if r == "성공":
                n += 1
            fails = fails + 1 if r == "실패" else 0
            # 한 번 실패했다고 끝내지 않는다(2026-10-06: 4개 중 3개째에서 멈춤). 두 번 연속 실패나 블록이 없으면 끝
            if r == "없음" or fails >= 2 or once:
                break
        log(f"끝: {n}개 넣음")
    except KeyboardInterrupt:
        log("사용자 중단")
    finally:
        stop()
        try:
            # 끝나면 홈(쉬는) 자세로. 블록을 들고 있으면 그리퍼는 닫은 채로
            # (2026-10-06: 실패로 끝나며 그리퍼를 열어 들고 있던 블록을 떨어뜨림)
            pk.pose("home", grip=pk.free_grip(), sec=3.0)
        except Exception as e:
            log(f"홈 자세로 못 돌아감: {e}")


if __name__ == "__main__":
    main()
