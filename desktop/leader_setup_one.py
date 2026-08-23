#!/usr/bin/env python3
# 리더팔 모터 하나만 연결한 상태에서 지정 관절 이름으로 ID를 새기고 검증.
import sys
from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig
TARGET={"shoulder_pan":1,"shoulder_lift":2,"elbow_flex":3,"wrist_flex":4,"wrist_roll":5,"gripper":6}
def main():
    if len(sys.argv)<2 or sys.argv[1] not in TARGET:
        print("사용법: leader_setup_one.py <관절이름>"); print("가능:", ", ".join(TARGET)); return 1
    motor=sys.argv[1]; tid=TARGET[motor]
    lead=SO101Leader(SO101LeaderConfig(port="/dev/ttyACM0", id="my_leader"))
    bus=lead.bus
    print(f">>> {motor} 에 ID {tid} 새기는 중... (리더 모터 1개만 연결돼 있어야 함)")
    try:
        bus.setup_motor(motor)
    except Exception as e:
        print("실패:", e)
        try: bus.disconnect()
        except: pass
        return 2
    import scservo_sdk as scs
    try: bus.disconnect()
    except: pass
    ph=scs.PortHandler("/dev/ttyACM0"); ph.openPort(); ph.setBaudRate(1000000)
    pk=scs.PacketHandler(0)
    _,comm,err=pk.ping(ph,tid); ph.closePort()
    ok = (comm==scs.COMM_SUCCESS and err==0)
    print(f"{'성공' if ok else '경고'}: {motor} = ID {tid} {'확인됨' if ok else '응답없음-재확인필요'}")
    return 0 if ok else 3
if __name__=="__main__":
    sys.exit(main())
