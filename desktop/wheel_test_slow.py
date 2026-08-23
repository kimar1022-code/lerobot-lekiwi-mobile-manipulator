#!/usr/bin/env python3
import os, time
from lerobot.robots.lekiwi import LeKiwiClient, LeKiwiClientConfig
IP=os.environ.get("LEKIWI_IP","192.168.75.20")
robot=LeKiwiClient(LeKiwiClientConfig(remote_ip=IP, id="my_lekiwi"))
robot.connect()
print("연결됨:", robot.is_connected)

def stop(n=6):
    for _ in range(n):
        robot.send_action({"x.vel":0.0,"y.vel":0.0,"theta.vel":0.0}); time.sleep(0.05)

def drive(name, x, y, th, dur=3.0):
    print(f"[{time.strftime('%H:%M:%S')}] {name}", flush=True)
    t0=time.time()
    while time.time()-t0<dur:
        robot.send_action({"x.vel":x,"y.vel":y,"theta.vel":th}); time.sleep(0.05)
    stop()

print(">>> 5초 뒤 시작합니다. 로봇 바퀴를 봐주세요...", flush=True)
stop(); time.sleep(5)
drive("1. 좌회전", 0.0,0.0,25.0); time.sleep(3)
drive("2. 우회전", 0.0,0.0,-25.0); time.sleep(3)
drive("3. 전진",   0.08,0.0,0.0); time.sleep(3)
drive("4. 후진",   -0.08,0.0,0.0); time.sleep(3)
drive("5. 좌게걸음",0.0,0.08,0.0); time.sleep(3)
drive("6. 우게걸음",0.0,-0.08,0.0)
stop()
robot.disconnect()
print("완료")
