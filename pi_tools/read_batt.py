#!/usr/bin/env python3
# 모터 배터리 전압을 읽어 출력(V). 포트 사용중/실패면 아무것도 출력 안함.
import sys
try:
    import scservo_sdk as scs
    ph=scs.PortHandler("/dev/ttyACM0")
    if not ph.openPort(): sys.exit(0)
    ph.setBaudRate(1000000)
    pk=scs.PacketHandler(0)
    for mid in (1,2,4,5,6,3):
        v,comm,err=pk.read1ByteTxRx(ph, mid, 62)   # STS3215 Present_Voltage @62, 0.1V 단위
        if comm==scs.COMM_SUCCESS and 50<v<200:
            print(f"{v/10.0:.1f}"); ph.closePort(); sys.exit(0)
    ph.closePort()
except Exception:
    pass
