#!/usr/bin/env python3
# LeKiwi 팔로워: 모터 하나만 연결한 상태에서 지정한 관절 이름으로 ID를 새기고 검증한다.
import sys
from lerobot.robots.lekiwi.lekiwi import LeKiwi
from lerobot.robots.lekiwi.config_lekiwi import LeKiwiConfig

TARGET = {
    "arm_shoulder_pan": 1, "arm_shoulder_lift": 2, "arm_elbow_flex": 3,
    "arm_wrist_flex": 4, "arm_wrist_roll": 5, "arm_gripper": 6,
    "base_left_wheel": 7, "base_back_wheel": 8, "base_right_wheel": 9,
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TARGET:
        print("사용법: setup_one.py <관절이름>")
        print("가능:", ", ".join(TARGET)); return 1
    motor = sys.argv[1]
    tid = TARGET[motor]
    cfg = LeKiwiConfig(port="/dev/ttyACM0", id="my_lekiwi")
    robot = LeKiwi(cfg)
    bus = robot.bus
    print(f">>> {motor} 에 ID {tid} 새기는 중... (모터 1개만 연결돼 있어야 함)")
    try:
        bus.setup_motor(motor)
    except Exception as e:
        print(f"실패: {e}")
        try: bus.disconnect()
        except: pass
        return 2
    import scservo_sdk as scs
    try: bus.disconnect()
    except: pass
    ph=scs.PortHandler("/dev/ttyACM0"); ph.openPort(); ph.setBaudRate(1000000)
    pk=scs.PacketHandler(0)
    model,comm,err=pk.ping(ph,tid)
    ph.closePort()
    if comm==scs.COMM_SUCCESS and err==0:
        print(f"성공: {motor} = ID {tid} 확인됨"); return 0
    print(f"경고: ID {tid} 응답없음 - 다시 확인 필요"); return 3

if __name__=="__main__":
    sys.exit(main())
