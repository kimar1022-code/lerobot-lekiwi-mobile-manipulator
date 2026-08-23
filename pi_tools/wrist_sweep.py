#!/usr/bin/env python3
# 팔로워 손목굽힘 호밍 초기화 후, 사용자가 끝~끝 쓸면 raw(actual) 궤적을 기록. stop파일로 종료.
# (범위가 엔코더 경계 0/4095를 걸칠 때 unwrap으로 재중심 잡기 위함)
import json, os, time
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig
M="arm_wrist_flex"; STOP="/tmp/wrist_stop"
if os.path.exists(STOP): os.remove(STOP)
cfg=LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
robot=LeKiwi(cfg); bus=robot.bus; bus.connect()
bus.disable_torque([M])
bus.write("Homing_Offset",M,0,normalize=False)
bus.write("Min_Position_Limit",M,0,normalize=False)
bus.write("Max_Position_Limit",M,4095,normalize=False)
print("호밍 초기화 완료. 끝~끝 쓸어주세요")
samples=[]
while not os.path.exists(STOP):
    r=bus.sync_read("Present_Position",[M],normalize=False,num_retry=5)[M]
    samples.append(int(r))
    time.sleep(0.03)
json.dump(samples, open("/tmp/wrist_samples.json","w"))
bus.disconnect()
print("기록 종료, 샘플수:", len(samples))
