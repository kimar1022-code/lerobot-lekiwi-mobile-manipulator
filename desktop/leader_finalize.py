#!/usr/bin/env python3
# 리더팔 궤적 unwrap -> 각 관절 중앙정렬(homing) + 범위 저장. wrist_roll은 무한회전.
import json
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
from lerobot.motors import MotorCalibration

samples=json.load(open("/tmp/leader_samples.json"))
def unwrap(s):
    u=[s[0]]; off=0
    for i in range(1,len(s)):
        d=s[i]-s[i-1]
        if d>2048: off-=4096
        elif d<-2048: off+=4096
        u.append(s[i]+off)
    return u

lead=SO101Leader(SO101LeaderConfig(port="/dev/ttyACM0", id="my_leader"))
bus=lead.bus; bus.connect()
bus.disable_torque()
FULL="wrist_roll"
calib={}
print(f"{'관절':12s} {'폭':>6} {'중앙':>6} {'호밍':>6} {'범위min':>7} {'범위max':>7}")
for name, motor in bus.motors.items():
    s=samples[name]; u=unwrap(s)
    umin, umax = min(u), max(u); width=umax-umin
    center=int(round((umin+umax)/2))%4096
    homing=center-2047
    if homing>2047: homing-=4096
    if homing<-2047: homing+=4096
    if name==FULL:
        rmin, rmax = 0, 4095
    else:
        margin=int(width*0.08)
        rmin=max(0,2047-width//2-margin); rmax=min(4095,2047+(width-width//2)+margin)
    bus.write("Homing_Offset", name, int(homing), normalize=False)
    bus.write("Min_Position_Limit", name, int(rmin), normalize=False)
    bus.write("Max_Position_Limit", name, int(rmax), normalize=False)
    calib[name]=MotorCalibration(id=motor.id, drive_mode=0, homing_offset=int(homing),
                                 range_min=int(rmin), range_max=int(rmax))
    print(f"{name:12s} {width:>6} {center:>6} {homing:>6} {rmin:>7} {rmax:>7}")
lead.calibration=calib; bus.calibration=calib
lead._save_calibration()
print("저장:", lead.calibration_fpath)
# 검증
norm=bus.sync_read("Present_Position")
allok=True
for name in bus.motors:
    v=norm[name]
    if name=="wrist_roll":
        print(f"  검증 {name:12s}: {v:7.1f} (무한회전-참고)"); continue
    lo,hi=((-1,101) if name=="gripper" else (-101,101))
    ok=lo<=v<=hi; allok=allok and ok
    print(f"  검증 {name:12s}: {v:7.1f} {'OK' if ok else '범위밖!'}")
bus.disconnect()
print("=== 리더팔 캘리 완료 ===" if allok else "=== 일부 범위밖(재확인) ===")
