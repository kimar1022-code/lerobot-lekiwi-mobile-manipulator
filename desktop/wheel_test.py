#!/usr/bin/env python3
import os, time
from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
IP=os.environ.get("LEKIWI_IP","192.168.75.20")
robot=LeKiwiClient(LeKiwiClientConfig(remote_ip=IP, id="my_lekiwi"))
print("연결 시도:", IP)
robot.connect()
print("연결됨:", robot.is_connected)
obs=robot.get_observation()
keys=[k for k in obs if not hasattr(obs[k],"shape")]
print("관측 수신 OK. 상태키 예시:", keys[:6])

def drive(name, x, y, th, dur=1.5):
    print(f"  >> {name}  (x={x} y={y} th={th})  {dur}s")
    t0=time.time()
    while time.time()-t0<dur:
        robot.send_action({"x.vel":x,"y.vel":y,"theta.vel":th})
        time.sleep(0.05)
    # 정지
    for _ in range(5):
        robot.send_action({"x.vel":0.0,"y.vel":0.0,"theta.vel":0.0}); time.sleep(0.05)

print("바퀴 테스트 시작 (각 1.5초, 사이 정지)")
drive("좌회전", 0.0, 0.0, 30.0)
time.sleep(0.7)
drive("우회전", 0.0, 0.0, -30.0)
time.sleep(0.7)
drive("전진", 0.1, 0.0, 0.0)
time.sleep(0.7)
drive("후진", -0.1, 0.0, 0.0)
time.sleep(0.7)
drive("좌게걸음", 0.0, 0.1, 0.0)
time.sleep(0.7)
drive("우게걸음", 0.0, -0.1, 0.0)
robot.send_action({"x.vel":0.0,"y.vel":0.0,"theta.vel":0.0})
time.sleep(0.3)
robot.disconnect()
print("바퀴 테스트 완료")
