"""LeKiwi 자율 색깔 블록 집기 → 보관함 넣기.

  찾기(제자리 회전) → 다가가기(배캠) → 손목캠에 보이면 넘겨받기 → 바퀴로 기준점 맞추기
  → 집기(가르친 자세) → 집었는지 확인 → 마커 찾기(회전) → 보관함 앞 접근 → 넣기 → 반복

팔은 poses.json 에 저장한 자세(look / pick / drop)만 쓰고, 위치 맞추기는 옴니휠로 한다.
웹 서버(lekiwi_web.py)를 거쳐 명령하므로 동작 중에도 브라우저로 화면을 볼 수 있다.

사용법:  python auto_pick.py red yellow        (색을 안 주면 red yellow)
         python auto_pick.py red --once        (한 개만 집고 끝)
"""
import json
import os
import sys
import time

import cv2
import numpy as np

from approach_marker import find_marker
from color_detect import detect, roi_px
from robot_api import Cam, arm_mode, arm_now, arm_target, drive, drive_for, move_to, stop

HERE = os.path.dirname(os.path.abspath(__file__))
POSES = os.path.join(HERE, "poses.json")
LOGDIR = os.path.join(HERE, "logs", time.strftime("%Y%m%d_%H%M%S"))
G = "arm_gripper.pos"

# 주행 속도 (느리게 시작. 2026-10-05 방향 실측: x+ 전진 / y+ 왼쪽 / theta+ 반시계)
V_FWD = 0.06
TURN_SEARCH = 20.0      # 찾을 때 회전 속도(도/초). theta 명령 1초 = 실측 약 15.2°/15 → 거의 정확
K_TURN = 0.08           # 배캠 x 오차(px) → 회전속도
ALIGN_TOL = 10          # 손목캠 기준점 허용 오차(px)
ALIGN_V = 0.04          # 미세 이동 속도


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def save(name, img):
    os.makedirs(LOGDIR, exist_ok=True)
    cv2.imwrite(os.path.join(LOGDIR, f"{time.strftime('%H%M%S')}_{name}.jpg"), img)


class Picker:
    def __init__(self, colors):
        self.colors = colors
        self.P = json.load(open(POSES))
        self.front, self.wrist = Cam("front"), Cam("wrist")
        time.sleep(1.0)

    # ── 공통 ──────────────────────────────────────────────
    def snap(self, cam, settle=0.0):
        t = time.time() + settle
        if settle:
            time.sleep(settle)
        return cam.get(newer_than=t, timeout=3)

    def save_poses(self):
        json.dump(self.P, open(POSES, "w"), indent=1, ensure_ascii=False)

    def look(self, grip=None, sec=2.5):
        pose = dict(self.P["look"])
        pose[G] = arm_now()[G] if grip is None else grip
        move_to(pose, sec=sec)

    def front_blocks(self, img):
        """배캠에서 목표 색 블록. 보관함 안(마커 주변)에 든 것은 뺀다."""
        dets = detect(img, colors=self.colors, roi=roi_px("front", img.shape), cam="front")
        m = find_marker(img)
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
        turned = 0.0
        for sign, deg in self.SWEEP:
            end = time.time() + deg / TURN_SEARCH
            t = time.time()
            while time.time() < end:
                drive(theta=sign * TURN_SEARCH)
                img = self.front.get(newer_than=t); t = time.time()
                if finder(img):
                    stop()
                    # 도는 중 본 화면은 살짝 늦으므로 멈춘 뒤 다시 보고 확정
                    img = self.snap(self.front, settle=0.4)
                    if found := finder(img):
                        turned += sign * TURN_SEARCH * (deg / TURN_SEARCH - (end - time.time()))
                        log(f"{what} 발견 (약 {turned:+.0f}° 지점, +왼쪽/-오른쪽)")
                        return found
            stop()
            turned += sign * deg
        log(f"{what} 못 찾음 (좌우 훑고 한 바퀴 돌았음)")
        return None

    # ── ② 블록으로 다가가기 → 손목캠에 보이면 정지 ───────────
    def approach_block(self, first, timeout=40):
        tx, ty = first["cx"], first["cy"]
        t0 = last_seen = time.time()
        while time.time() - t0 < timeout:
            w = self.wrist_block(self.wrist.frame) if self.wrist.frame is not None else None
            if w:
                stop(); log(f"손목캠이 블록을 봄 → 넘겨받기 ({w['cx']:.0f},{w['cy']:.0f})")
                return True
            img = self.snap(self.front)
            dets = self.front_blocks(img)
            if dets:   # 직전 위치에서 가장 가까운 블록을 계속 쫓는다(다른 블록으로 갈아타기 방지)
                d = min(dets, key=lambda d: (d["cx"] - tx) ** 2 + (d["cy"] - ty) ** 2)
                if (d["cx"] - tx) ** 2 + (d["cy"] - ty) ** 2 < 120 ** 2:
                    tx, ty, last_seen = d["cx"], d["cy"], time.time()
            err = tx - img.shape[1] / 2
            if time.time() - last_seen < 0.5:
                th = float(np.clip(-K_TURN * err, -15, 15))
                drive(x=V_FWD if abs(err) < 70 else 0.0, theta=th)
            elif time.time() - last_seen < 3.0:
                # 배캠 아래로 사라짐(너무 가까움) → 손목캠에 잡힐 때까지 천천히 앞으로
                drive(x=0.04)
            else:
                stop(); log("블록을 놓침"); return False
        stop(); log("다가가기 시간 초과"); return False

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

    def align(self, max_iter=14):
        tgt = np.array(self.P["target_px"])
        Jinv = np.linalg.pinv(np.array(self.P["wrist_jac"]))
        for i in range(max_iter):
            w = self.wrist_block(self.snap(self.wrist, settle=0.4))
            if not w:
                log("정렬 중 블록이 손목캠에서 사라짐"); return False
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
        self.look(grip=held + 4)
        time.sleep(0.4)
        img = self.snap(self.wrist, settle=0.3)
        save("grasp", img)
        w = self.wrist_block(img)
        empty = self.P.get("grip_empty", 100)
        ok = held < empty - 8 and w is not None and w["area"] > 6000
        log(f"집기 {'성공' if ok else '실패'}: 그리퍼 {held:.1f} (빈손 {empty}), "
            f"손목캠 블록 면적 {w['area'] if w else 0}")
        if not ok:
            move_to({G: open_g}, sec=0.8, keys=[G])
        return ok, held

    # ── ⑤ 보관함 ──────────────────────────────────────────
    def go_to_box(self, timeout=40):
        m = self.search(find_marker, "보관함 마커")
        if not m:
            return False
        want = self.P["drop_marker"]
        t0, last_seen = time.time(), time.time()
        while time.time() - t0 < timeout:
            img = self.snap(self.front)
            m = find_marker(img)
            if m:
                last_seen = time.time()
                err = m["cx"] - want["cx"]
                if m["dist"] <= want["dist"] and abs(err) < 12:
                    stop(); log(f"보관함 앞 도착 (거리 {m['dist']:.3f}m, 좌우 {err:+.0f}px)")
                    return True
                th = float(np.clip(-K_TURN * err, -15, 15))
                x = V_FWD if (m["dist"] > want["dist"] and abs(err) < 60) else 0.0
                drive(x=x, theta=th)
            elif time.time() - last_seen > 1.0:
                stop(); log("마커를 놓침"); return False
        stop(); log("보관함 접근 시간 초과"); return False

    def drop(self, held):
        pose = dict(self.P["drop"]); pose[G] = held + 4
        move_to(pose, sec=3.0); time.sleep(0.4)
        move_to({G: self.P["look"][G]}, sec=0.8, keys=[G]); time.sleep(0.8)
        save("drop", self.snap(self.wrist))
        self.look(sec=3.0)
        log("넣기 완료")

    # ── 전체 ──────────────────────────────────────────────
    def run_one(self):
        first = self.search(lambda img: (self.front_blocks(img) or [None])[0], "블록")
        if not first:
            return "없음"
        log(f"  목표: {first['color']} ({first['cx']:.0f},{first['cy']:.0f})")
        if not self.approach_block(first):
            return "실패"
        if not self.calib_wrist_jacobian():
            return "실패"
        for attempt in range(3):
            if not self.align():
                return "실패"
            ok, held = self.grasp()
            if ok:
                break
            log(f"다시 시도 ({attempt + 1}/2)")
        else:
            return "실패"
        if not self.go_to_box():
            return "실패"
        self.drop(held)
        drive_for(x=-V_FWD, sec=2.0)        # 보관함에서 살짝 물러남
        return "성공"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    colors = args or ["red", "yellow"]
    once = "--once" in sys.argv
    pk = Picker(colors)
    log(f"시작: 목표 색 {colors}  (로그 사진 {LOGDIR})")
    arm_mode("manual"); time.sleep(0.4)
    try:
        pk.look(grip=pk.P["look"][G], sec=2.5)
        pk.calib_empty_grip()
        n = 0
        while True:
            r = pk.run_one()
            log(f"결과: {r}")
            if r == "성공":
                n += 1
            if r != "성공" or once:
                break
        log(f"끝: {n}개 넣음")
    except KeyboardInterrupt:
        log("사용자 중단")
    finally:
        stop()


if __name__ == "__main__":
    main()
