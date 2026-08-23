#!/usr/bin/env python3
# 팔로워 그리퍼: 위치제한을 먼저 풀고(0~4095), 모터로 양방향 몰아 물리적 끝(min/max)을 찾는다.
# (그리퍼는 기어 때문에 손으로 안 움직여서 모터로 구동해 측정)
import time, json
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig
from lerobot.motors.feetech import OperatingMode

G="arm_gripper"
STEP=12; SETTLE=0.12; STALL_TH=4; STALL_MAX=4; TRAVEL_CAP=2200

cfg=LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
robot=LeKiwi(cfg); bus=robot.bus; bus.connect()
def pos(): return bus.sync_read("Present_Position",[G],normalize=False)[G]

lim_min=bus.read("Min_Position_Limit",G,normalize=False)
lim_max=bus.read("Max_Position_Limit",G,normalize=False)
print(f"현재 그리퍼 제한: {lim_min} ~ {lim_max}")
bus.disable_torque([G])
bus.write("Min_Position_Limit",G,0,normalize=False)
bus.write("Max_Position_Limit",G,4095,normalize=False)
print("제한 해제(0~4095) 완료")

bus.write("Operating_Mode",G,OperatingMode.POSITION.value)
bus.enable_torque([G])
start=pos(); print("시작 위치:", start)

def sweep(direction):
    cur=pos(); target=cur; stalls=0; travelled=0
    while travelled<TRAVEL_CAP:
        target=max(0,min(4095,target+direction*STEP))
        bus.write("Goal_Position",G,int(target),normalize=False)
        time.sleep(SETTLE)
        new=pos()
        stalls = stalls+1 if abs(new-cur)<STALL_TH else 0
        cur=new; travelled+=STEP
        if stalls>=STALL_MAX or target in (0,4095): break
    bus.write("Goal_Position",G,int(cur),normalize=False); time.sleep(0.2)
    return cur

hi=sweep(+1); print("+방향 끝:", hi)
time.sleep(0.3)
lo=sweep(-1); print("-방향 끝:", lo)

mn,mx=sorted([lo,hi])
print(f"=== 그리퍼 물리범위: min={mn} max={mx} (폭={mx-mn}) ===")
mid=(mn+mx)//2
bus.write("Goal_Position",G,int(mid),normalize=False); time.sleep(0.5)
bus.disable_torque([G])
bus.disconnect()
json.dump({"min":int(mn),"max":int(mx)},open("/tmp/gripper_found.json","w"))
print("저장 완료")
