#!/usr/bin/env python3
# LeKiwi 모터 ID 스캔: ID 1~20을 핑해서 어떤 모터가 어떤 ID로 등록됐는지 확인.
# 사용법: python scan_motors.py [포트] [통신속도]   기본 /dev/ttyACM0 1000000
import sys
import scservo_sdk as scs

EXPECTED = {
    1: "팔-어깨회전 (shoulder_pan)",
    2: "팔-어깨들기 (shoulder_lift)",
    3: "팔-팔꿈치  (elbow_flex)",
    4: "팔-손목굽힘 (wrist_flex)",
    5: "팔-손목회전 (wrist_roll)",
    6: "팔-그리퍼  (gripper)",
    7: "바퀴-왼쪽  (base_left_wheel)",
    8: "바퀴-뒤쪽  (base_back_wheel)",
    9: "바퀴-오른쪽 (base_right_wheel)",
}

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000
    print(f"포트: {port}  /  통신속도: {baud}")
    print("=" * 55)
    port_handler = scs.PortHandler(port)
    packet_handler = scs.PacketHandler(0)  # Feetech SCS/STS 프로토콜
    if not port_handler.openPort():
        print(f"포트를 열 수 없습니다: {port}")
        print("   → USB 케이블 연결 확인, 또는 sudo chmod 666 " + port); return 1
    if not port_handler.setBaudRate(baud):
        print(f"통신속도 설정 실패: {baud}"); return 1
    found = {}
    print("ID 1~20 스캔 중...\n")
    for motor_id in range(1, 21):
        model, comm, err = packet_handler.ping(port_handler, motor_id)
        if comm == scs.COMM_SUCCESS and err == 0:
            found[motor_id] = model
            label = EXPECTED.get(motor_id, "(LeKiwi에서 쓰지 않는 ID)")
            print(f"  ID {motor_id:2d}  (모델 {model})  {label}")
    port_handler.closePort()
    print("\n" + "=" * 55)
    print(f"발견된 모터: {len(found)}개  →  {sorted(found)}")
    missing = sorted(set(EXPECTED) - set(found))
    extra = sorted(set(found) - set(EXPECTED))
    if len(found) == 9 and not missing:
        print("\n모터 ID 1~9가 모두 설정돼 있습니다.")
        print("   → ID 굽는 단계를 건너뛰고 바로 캘리브레이션으로 갑니다."); return 0
    if missing:
        print(f"\n없는 ID: {missing}")
        for m in missing: print(f"     ID {m} = {EXPECTED[m]}")
    if extra:
        print(f"\n예상 밖 ID: {extra}  (공장 초기값은 보통 1번입니다)")
    print("\n→ ID 설정이 필요합니다. setup_one.py 로 하나씩 등록하세요.")
    return 2

if __name__ == "__main__":
    sys.exit(main())
