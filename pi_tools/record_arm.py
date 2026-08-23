#!/usr/bin/env python3
# 팔로워 캘리 2단계: 손으로 움직이는 팔 관절 4개 범위 기록. 통신 튐(급격한 점프) 걸러냄. stop파일로 종료.
import json, os, time
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig

JOINTS=["arm_shoulder_pan","arm_shoulder_lift","arm_elbow_flex","arm_wrist_flex"]
JUMP=350   # 20ms에 이 이상 튀면 통신오류로 간주하고 무시
STOP="/tmp/record_arm_stop"
if os.path.exists(STOP): os.remove(STOP)

cfg=LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
robot=LeKiwi(cfg); bus=robot.bus; bus.connect()
bus.disable_torque(JOINTS)

def read():
    return bus.sync_read("Present_Position",JOINTS,normalize=False,num_retry=5)

last=read()
mins=dict(last); maxes=dict(last)
print("기록 시작(이상값 필터 ON)")
n=0
while not os.path.exists(STOP):
    p=read()
    for m in JOINTS:
        if abs(p[m]-last[m])<=JUMP:
            mins[m]=min(mins[m],p[m]); maxes[m]=max(maxes[m],p[m]); last[m]=p[m]
    n+=1
    if n%40==0:
        json.dump({"mins":{k:int(v) for k,v in mins.items()},"maxes":{k:int(v) for k,v in maxes.items()}},open("/tmp/arm_ranges.json","w"))
    time.sleep(0.02)
json.dump({"mins":{k:int(v) for k,v in mins.items()},"maxes":{k:int(v) for k,v in maxes.items()}},open("/tmp/arm_ranges.json","w"))
bus.disconnect()
print("기록 종료")
