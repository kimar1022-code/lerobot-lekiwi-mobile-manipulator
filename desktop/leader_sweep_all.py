#!/usr/bin/env python3
# 리더팔 6개 호밍 초기화 후, 모든 관절을 끝~끝 쓸면 raw(actual) 궤적 기록. stop파일로 종료.
import json, os, time
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
STOP="/tmp/leader_stop"
if os.path.exists(STOP): os.remove(STOP)
lead=SO101Leader(SO101LeaderConfig(port="/dev/ttyACM0", id="my_leader"))
bus=lead.bus; bus.connect()
motors=list(bus.motors.keys())
bus.disable_torque()
for m in motors:
    bus.write("Homing_Offset", m, 0, normalize=False)
    bus.write("Min_Position_Limit", m, 0, normalize=False)
    bus.write("Max_Position_Limit", m, 4095, normalize=False)
print("호밍 초기화 완료. 모든 관절을 끝~끝 쓸어주세요")
samples={m:[] for m in motors}
n=0
while not os.path.exists(STOP):
    pos=bus.sync_read("Present_Position", normalize=False, num_retry=3)
    for m in motors: samples[m].append(int(pos[m]))
    n+=1
    if n%100==0:
        json.dump(samples, open("/tmp/leader_samples.json","w"))
    time.sleep(0.02)
json.dump(samples, open("/tmp/leader_samples.json","w"))
bus.disconnect()
print("기록 종료, 샘플수:", n)
