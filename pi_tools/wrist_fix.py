#!/usr/bin/env python3
# 팔로워 손목굽힘 궤적을 unwrap해 실제 중앙 계산 → 호밍 재설정(중앙=2047) → 범위 저장.
import json
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig
from lerobot.motors import MotorCalibration
M="arm_wrist_flex"
s=json.load(open("/tmp/wrist_samples.json"))
u=[s[0]]; off=0
for i in range(1,len(s)):
    d=s[i]-s[i-1]
    if d>2048: off-=4096
    elif d<-2048: off+=4096
    u.append(s[i]+off)
umin=min(u); umax=max(u); width=umax-umin
center_actual=int(round(((umin+umax)/2))) % 4096
homing=center_actual-2047
if homing>2047: homing-=4096
if homing<-2047: homing+=4096
rmin=2047-width//2; rmax=2047+(width-width//2)
print(f"unwrap 범위폭={width}  실제중앙={center_actual}  새호밍={homing}  새범위={rmin}~{rmax}")

cfg=LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
robot=LeKiwi(cfg); bus=robot.bus; bus.connect()
bus.disable_torque([M])
bus.write("Homing_Offset",M,int(homing),normalize=False)
bus.write("Min_Position_Limit",M,int(rmin),normalize=False)
bus.write("Max_Position_Limit",M,int(rmax),normalize=False)
cal=robot.calibration
cal[M]=MotorCalibration(id=cal[M].id, drive_mode=0, homing_offset=int(homing), range_min=int(rmin), range_max=int(rmax))
robot.calibration=cal; bus.calibration=cal
robot._save_calibration()
norm=bus.sync_read("Present_Position",[M])[M]
raw=bus.sync_read("Present_Position",[M],normalize=False)[M]
print(f"검증: 손목굽힘 raw={raw}  정규화={norm:.1f}  (범위 {rmin}~{rmax})")
bus.disconnect()
print("OK" if -100<=norm<=100 else "여전히 범위밖")
