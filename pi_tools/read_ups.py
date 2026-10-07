#!/usr/bin/env python3
"""라즈베리파이 UPS(X1200) 배터리 상태.

퓨얼게이지 MAX17040/48 계열, I2C 주소 0x36
  0x02 VCELL : 셀 전압
  0x04 SOC   : 남은 용량(%)

출력:  <퍼센트> <전압> <AC|BAT|?>
  세 번째 칸: X1200 의 정전 감지 핀(GPIO6)으로 본 충전기 연결 여부. AC=꽂힘(충전 중), BAT=배터리만.
  충전 중에는 충전기가 전압을 밀어 올려 전압환산 %가 실제보다 높게 나온다(2026-10-06 4%→68%).
SOC 레지스터가 엉뚱한 값을 줄 때가 있어(리셋 직후 학습 전) 전압으로도 계산해
둘 중 더 그럴듯한 값을 쓴다.

--debug 를 주면 원본 값과 실패 이유를 보여준다.
"""
import sys
DEBUG = '--debug' in sys.argv
ADDR, BUS = 0x36, 1

def bail(msg):
    if DEBUG: print(f'[실패] {msg}')
    sys.exit(1 if DEBUG else 0)

try:
    from smbus2 import SMBus
except ImportError:
    try: from smbus import SMBus
    except ImportError: bail('smbus2 없음 -> sudo apt install python3-smbus2')

try:
    with SMBus(BUS) as bus:
        raw_v = bus.read_word_data(ADDR, 0x02)
        raw_s = bus.read_word_data(ADDR, 0x04)
except PermissionError:
    bail('/dev/i2c-1 권한 없음 -> sudo usermod -aG i2c $USER 후 재로그인')
except Exception as e:
    bail(f'I2C 읽기 실패: {e}')

swap = lambda w: ((w & 0xFF) << 8) | (w >> 8)
v, s = swap(raw_v), swap(raw_s)

volt = (v >> 4) * 1.25 / 1000        # 12비트, 1.25mV
soc  = s / 256.0                      # 상위=정수%, 하위=1/256%

# 리튬이온 1셀 방전곡선으로 전압 -> % (대략)
def volt_pct(c):
    pts = [(3.00,0),(3.30,8),(3.50,25),(3.70,50),(3.80,60),(4.00,85),(4.20,100)]
    if c <= pts[0][0]: return 0.0
    if c >= pts[-1][0]: return 100.0
    for (v1,p1),(v2,p2) in zip(pts, pts[1:]):
        if v1 <= c <= v2:
            return p1 + (c-v1)/(v2-v1)*(p2-p1)
    return 0.0

vp = volt_pct(volt)

# SOC 가 0~100 밖이거나 전압 기반과 25%p 넘게 어긋나면 전압 쪽을 믿는다
use = soc
why = 'SOC'
if not (0.0 < soc <= 100.0) or abs(soc - vp) > 25:
    use, why = vp, '전압'

if DEBUG:
    print(f'  원본 VCELL=0x{raw_v:04x}->{v}  SOC=0x{raw_s:04x}->{s}')
    print(f'  전압 {volt:.2f}V  |  SOC레지스터 {soc:.1f}%  |  전압환산 {vp:.1f}%  ->  {why} 사용')

def ac_state():
    # gpiod 는 lerobot venv 에만 있다. 시스템 python 으로 실행돼도 찾아가게 한다.
    try:
        import gpiod
    except ImportError:
        import glob, os
        hits = glob.glob(os.path.expanduser("~/lerobot/.venv/lib/python3*/site-packages"))
        if hits:
            sys.path.insert(0, hits[0])
        try:
            import gpiod
        except ImportError:
            return "?"
    try:
        from gpiod.line import Direction, Value
        with gpiod.request_lines("/dev/gpiochip4", consumer="ups-pld",
                                 config={6: gpiod.LineSettings(direction=Direction.INPUT)}) as req:
            return "AC" if req.get_value(6) == Value.ACTIVE else "BAT"
    except Exception:
        return "?"

ac = ac_state()
if DEBUG:
    print(f'  충전기: {ac}')
print(f'{use:.1f} {volt:.2f} {ac}')
