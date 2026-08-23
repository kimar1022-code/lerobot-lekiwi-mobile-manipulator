#!/usr/bin/env python3
# 팔로워 캘리 1단계: 팔을 "가운데 자세"로 둔 상태에서 실행 → 호밍(0점 기준) 설정
import json
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig
from lerobot.motors.feetech import OperatingMode

cfg = LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
robot = LeKiwi(cfg)
bus = robot.bus
bus.connect()
print("연결됨. 팔 토크 해제 후 호밍 설정 중...")
bus.disable_torque(robot.arm_motors)
for name in robot.arm_motors:
    bus.write("Operating_Mode", name, OperatingMode.POSITION.value)
homing = bus.set_half_turn_homings(robot.arm_motors)
homing = {k: int(v) for k, v in homing.items()}
json.dump(homing, open("/tmp/lekiwi_homing.json", "w"))
print("호밍 오프셋 저장 완료:")
for k, v in homing.items():
    print(f"  {k}: {v}")
bus.disconnect()
print("1단계 완료 - 이제 관절을 끝에서 끝까지 움직일 준비 하세요")
