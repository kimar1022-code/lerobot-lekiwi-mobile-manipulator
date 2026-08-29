#!/usr/bin/env python3
"""리더팔 / 로봇 관절값을 실시간으로 보여준다.

웹서버(lekiwi_web.py)가 떠 있어야 하며, API 로만 읽으므로 포트 충돌이 없다.

사용법:
    python3 watch_leader.py        (Ctrl+C 로 종료)

리더팔을 움직이면서 숫자가 바뀌는지 눈으로 확인하는 용도.
"""
import json
import sys
import time
import urllib.request

KEYS = ['arm_shoulder_pan', 'arm_shoulder_lift', 'arm_elbow_flex',
        'arm_wrist_flex', 'arm_wrist_roll', 'arm_gripper']
LAB = dict(zip(KEYS, ['어깨돌림', '어깨들기', '팔꿈치 ', '손목굽힘', '손목돌림', '그리퍼 ']))
URL = 'http://localhost:8080/api/pose'

start = {}          # 시작할 때의 리더팔 값 — 얼마나 움직였는지 비교용
peak = {k: 0.0 for k in KEYS}

print(__doc__)
print('  관절        리더팔      로봇     지금까지 움직인 폭')
print('  ' + '-' * 52)

try:
    while True:
        try:
            d = json.load(urllib.request.urlopen(URL, timeout=2))
        except Exception as e:
            sys.stdout.write(f'\r  서버 응답 없음: {e}          ')
            sys.stdout.flush()
            time.sleep(1)
            continue

        L = d.get('l') or {}
        C = d.get('c') or {}
        lines = []
        for k in KEYS:
            lv = L.get(k + '.pos')
            cv = C.get(k + '.pos')
            if lv is not None:
                if k not in start:
                    start[k] = lv
                peak[k] = max(peak[k], abs(lv - start[k]))
            mark = ' ←움직임' if peak[k] > 3 else ''
            ls = f'{lv:8.1f}' if lv is not None else '      --'
            cs = f'{cv:8.1f}' if cv is not None else '      --'
            lines.append(f'  {LAB[k]}  {ls}  {cs}      {peak[k]:6.1f}{mark}')

        # 커서를 위로 올려 같은 자리에 다시 그린다
        sys.stdout.write('\033[6A' if start else '')
        sys.stdout.write('\n'.join(lines) + '\n')
        sys.stdout.flush()
        time.sleep(0.2)
except KeyboardInterrupt:
    print('\n  종료.')
