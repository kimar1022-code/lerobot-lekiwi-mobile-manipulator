#!/usr/bin/env python3
# 팔 전용 미러링 테스트 (헤드리스). 리더팔 -> LeKiwi 팔. 부드러운 램프 시작. stop파일로 종료.
import os, time
from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
IP=os.environ.get("LEKIWI_IP","192.168.75.20")
STOP="/tmp/arm_teleop_stop"
if os.path.exists(STOP): os.remove(STOP)
RAMP_S=2.5; FPS=30
JOINTS=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]

robot=LeKiwiClient(LeKiwiClientConfig(remote_ip=IP, id="my_lekiwi"))
leader=SO101Leader(SO101LeaderConfig(port="/dev/ttyACM0", id="my_leader"))
robot.connect(); leader.connect()
print("연결됨. follower:", robot.is_connected, "leader:", leader.is_connected)

def base_zero(): return {"x.vel":0.0,"y.vel":0.0,"theta.vel":0.0}

obs=robot.get_observation()
start={j: obs.get(f"arm_{j}.pos", 0.0) for j in JOINTS}
print("부드러운 시작(램프) 중...")
t0=time.time()
while True:
    a=min(1.0,(time.time()-t0)/RAMP_S)
    lead=leader.get_action()
    act={}
    for j in JOINTS:
        tgt=lead.get(f"{j}.pos",0.0)
        act[f"arm_{j}.pos"]= start[j]*(1-a)+tgt*a
    act.update(base_zero())
    robot.send_action(act)
    if a>=1.0: break
    time.sleep(1.0/FPS)
print("램프 완료 -> 미러링 시작! 리더팔을 천천히 움직여보세요")
while not os.path.exists(STOP):
    lead=leader.get_action()
    act={f"arm_{j}.pos": lead.get(f"{j}.pos",0.0) for j in JOINTS}
    act.update(base_zero())
    robot.send_action(act)
    time.sleep(1.0/FPS)
robot.disconnect(); leader.disconnect()
print("미러링 종료")
