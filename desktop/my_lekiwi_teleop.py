#!/usr/bin/env python
"""LeKiwi 조종 스크립트 (SO-101 리더팔 + 키보드 주행)

공식 예제(examples/lekiwi/teleoperate.py)를 우리 환경에 맞게 고친 것:
  - SO100Leader -> SO101Leader  (우리 팔은 SO-101)
  - remote_ip   -> 우리 라즈베리파이 IP
  - 리더팔 포트  -> 자동 탐지 (환경변수로 덮어쓸 수 있음)

실행 전 조건:
  라즈베리파이에서 호스트 데몬이 먼저 떠 있어야 합니다.
      python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=my_lekiwi

조종법:
  팔    -> 리더팔을 손으로 움직이면 따라옵니다
  W/S   -> 앞으로 / 뒤로
  A/D   -> 왼쪽 / 오른쪽 (게걸음)
  Z/X   -> 좌회전 / 우회전
  R/F   -> 속도 올리기 / 내리기 (빠름 0.4 / 보통 0.25 / 느림 0.1 m/s)
  Ctrl+C -> 종료
"""

import glob
import os
import time

from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.teleoperators.keyboard.teleop_keyboard import KeyboardTeleop, KeyboardTeleopConfig
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
from lerobot.utils.robot_utils import precise_sleep
from lerobot.utils.visualization_utils import init_rerun, log_rerun_data

# ─── 설정 ────────────────────────────────────────────────────────────
FPS = 30

PI_IP = os.environ.get("LEKIWI_IP", "192.168.75.20")  # 라즈베리파이 IP
ROBOT_ID = os.environ.get("LEKIWI_ID", "my_lekiwi")  # Pi 호스트의 --robot.id 와 같아야 함
LEADER_ID = os.environ.get("LEADER_ID", "my_leader")  # 리더팔 캘리브레이션 이름
USE_RERUN = os.environ.get("USE_RERUN", "1") == "1"  # 화면 시각화 (0으로 끄기)
# ─────────────────────────────────────────────────────────────────────


def find_leader_port() -> str:
    """리더팔이 꽂힌 시리얼 포트를 찾습니다. LEADER_PORT 로 직접 지정도 가능."""
    if port := os.environ.get("LEADER_PORT"):
        return port

    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    if not ports:
        raise SystemExit(
            "리더팔을 찾을 수 없습니다.\n"
            "  - USB 케이블이 데스크탑에 꽂혀 있는지 확인하세요\n"
            "  - 포트를 직접 지정하려면: LEADER_PORT=/dev/ttyACM0 python my_lekiwi_teleop.py"
        )
    if len(ports) > 1:
        raise SystemExit(
            f"시리얼 포트가 여러 개 보입니다: {ports}\n"
            f"어느 것이 리더팔인지 지정해 주세요: LEADER_PORT={ports[0]} python my_lekiwi_teleop.py"
        )
    return ports[0]


def main():
    leader_port = find_leader_port()
    print(f"라즈베리파이 : {PI_IP}  (로봇 이름: {ROBOT_ID})")
    print(f"리더팔       : {leader_port}  (이름: {LEADER_ID})")
    print()

    robot = LeKiwiClient(LeKiwiClientConfig(remote_ip=PI_IP, id=ROBOT_ID))
    leader_arm = SO101Leader(SO101LeaderConfig(port=leader_port, id=LEADER_ID))
    keyboard = KeyboardTeleop(KeyboardTeleopConfig(id="my_keyboard"))

    robot.connect()
    leader_arm.connect()
    keyboard.connect()

    if not (robot.is_connected and leader_arm.is_connected and keyboard.is_connected):
        raise SystemExit("로봇 또는 조종 장치가 연결되지 않았습니다.")

    if USE_RERUN:
        init_rerun(session_name="lekiwi_teleop")

    print("조종 시작! (W/A/S/D 이동, Z/X 회전, R/F 속도, Ctrl+C 종료)")
    try:
        while True:
            t0 = time.perf_counter()

            observation = robot.get_observation()

            # 리더팔 관절값 -> 팔로워 팔 명령 (arm_ 접두사를 붙여 구분)
            arm_action = {f"arm_{k}": v for k, v in leader_arm.get_action().items()}

            # 키보드 입력 -> 바퀴 속도 명령
            base_action = robot._from_keyboard_to_base_action(keyboard.get_action())

            action = {**arm_action, **base_action} if base_action else arm_action
            robot.send_action(action)

            if USE_RERUN:
                log_rerun_data(observation=observation, action=action)

            precise_sleep(max(1.0 / FPS - (time.perf_counter() - t0), 0.0))
    except KeyboardInterrupt:
        print("\n종료합니다...")
    finally:
        robot.disconnect()
        leader_arm.disconnect()
        keyboard.disconnect()


if __name__ == "__main__":
    main()
