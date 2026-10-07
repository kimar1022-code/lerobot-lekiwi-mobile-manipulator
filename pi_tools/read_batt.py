#!/usr/bin/env python3
# 모터 배터리 전압을 읽어 출력(V).
# 상태줄에서 쓰므로 평소엔 조용히 실패하지만, --debug 를 주면 이유를 보여준다.
import sys, os

DEBUG = '--debug' in sys.argv

def bail(msg):
    if DEBUG:
        print(f'[실패] {msg}')
    sys.exit(0 if not DEBUG else 1)

# 호스트 데몬이 포트를 쓰는 중이면 열지 않는다.
# 리눅스는 같은 시리얼 포트를 두 프로그램이 동시에 열 수 있어서, 여기서 읽으면
# 호스트의 모터 명령과 패킷이 섞여 호스트가 "Port is in use" 로 죽는다(2026-10-05 3회).
# --force 를 주면 그래도 읽는다(호스트를 끈 상태에서 점검할 때).
if "--force" not in sys.argv:
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ")
        except OSError:
            continue
        if b"lekiwi_host" in cmd and b"host_watchdog" not in cmd:
            # 호스트가 10초마다 기록해 둔 전압을 쓴다 (lekiwi_host_plus.py)
            try:
                v, t = open(os.path.expanduser("~/lekiwi_motor_v.txt")).read().replace("\\n", " ").split()[:2]
                import time
                if time.time() - float(t) < 60:
                    print(v)
                    sys.exit(0)
            except (OSError, ValueError):
                pass
            bail("호스트 실행 중인데 최근 전압 기록이 없음 (--force 로 포트 직접 읽기)")

# scservo_sdk 는 lerobot venv 에만 있다. 시스템 python 으로 실행돼도 찾아가게 한다.
try:
    import scservo_sdk as scs
except ImportError:
    venv = os.path.expanduser('~/lerobot/.venv')
    import glob
    hits = glob.glob(f'{venv}/lib/python3*/site-packages')
    if hits:
        sys.path.insert(0, hits[0])
    try:
        import scservo_sdk as scs
    except ImportError as e:
        bail(f'scservo_sdk 없음 ({e}). venv: {venv}')

try:
    ph = scs.PortHandler('/dev/ttyACM0')
    if not ph.openPort():
        bail('포트 열기 실패 - 호스트 데몬이 쓰는 중이거나 USB 미연결')
    ph.setBaudRate(1000000)
    pk = scs.PacketHandler(0)
    for mid in (1, 2, 4, 5, 6, 3):
        v, comm, err = pk.read1ByteTxRx(ph, mid, 62)
        if comm == scs.COMM_SUCCESS and 50 < v < 200:
            print(f'{v/10.0:.1f}')
            ph.closePort()
            sys.exit(0)
    ph.closePort()
    bail('모터 무응답 - 모터 배터리 전원이 꺼져 있는지 확인')
except SystemExit:
    raise
except Exception as e:
    bail(f'예외: {e}')
