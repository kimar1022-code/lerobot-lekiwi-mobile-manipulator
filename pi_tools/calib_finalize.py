#!/usr/bin/env python3
# 팔로워 최종 저장: step1 호밍 + 팔 측정범위(record_arm) + 그리퍼(gripper_range) + 손목회전/바퀴(무한회전).
import json
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig
from lerobot.motors import MotorCalibration

homing=json.load(open("/tmp/lekiwi_homing.json"))
arm=json.load(open("/tmp/arm_ranges.json"))
grip=json.load(open("/tmp/gripper_found.json"))

cfg=LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
robot=LeKiwi(cfg); bus=robot.bus; bus.connect()

ranges_min={}; ranges_max={}
for m in ["arm_shoulder_pan","arm_shoulder_lift","arm_elbow_flex","arm_wrist_flex"]:
    ranges_min[m]=arm["mins"][m]; ranges_max[m]=arm["maxes"][m]
ranges_min["arm_gripper"]=grip["min"]; ranges_max["arm_gripper"]=grip["max"]
for m in ["arm_wrist_roll","base_left_wheel","base_back_wheel","base_right_wheel"]:
    ranges_min[m]=0; ranges_max[m]=4095

calib={}
for name,motor in bus.motors.items():
    h = int(homing.get(name, 0))
    calib[name]=MotorCalibration(id=motor.id, drive_mode=0, homing_offset=h,
                                 range_min=int(ranges_min[name]), range_max=int(ranges_max[name]))
robot.calibration=calib
bus.write_calibration(calib)
robot._save_calibration()
print("=== 저장 완료:", robot.calibration_fpath, "===")

hdr=("관절","저장min","저장max","모터min","모터max","호밍")
print("%-16s %7s %7s %7s %7s %6s" % hdr)
ok=True
for name in bus.motors:
    lm=bus.read("Min_Position_Limit",name,normalize=False)
    lM=bus.read("Max_Position_Limit",name,normalize=False)
    ho=bus.read("Homing_Offset",name,normalize=False)
    mark = "" if (lm==calib[name].range_min and lM==calib[name].range_max) else "  <差!"
    if mark: ok=False
    print(f"{name:16s} {calib[name].range_min:>7} {calib[name].range_max:>7} {lm:>7} {lM:>7} {ho:>6}{mark}")
bus.disconnect()
print("전체 일치" if ok else "불일치 있음")
