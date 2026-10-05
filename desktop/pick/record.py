"""시연 영상 녹화: 글로벌(크게) + 배·손목(작게) 합친 화면과 글로벌 원본을 함께 저장.

python record.py 이름        → ~/Videos/lekiwi/이름_합본.mp4, 이름_글로벌.mp4
멈추기: Ctrl+C 또는 ~/Videos/lekiwi/STOP 파일 만들기
"""
import os
import subprocess
import sys
import time

import cv2
import numpy as np
from robot_api import Cam

FPS = 15
OUT = os.path.expanduser("~/Videos/lekiwi")
os.makedirs(OUT, exist_ok=True)
name = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y%m%d_%H%M%S")
stopf = os.path.join(OUT, "STOP")
if os.path.exists(stopf):
    os.remove(stopf)

cams = {n: Cam(n) for n in ("desk", "front", "wrist")}
time.sleep(1.5)


def label(img, text):
    cv2.rectangle(img, (0, 0), (len(text) * 11 + 12, 24), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 80), 1, cv2.LINE_AA)
    return img


tmp_c, tmp_g = [os.path.join(OUT, f".{name}_{k}.avi") for k in ("c", "g")]
four = cv2.VideoWriter_fourcc(*"MJPG")
wc = cv2.VideoWriter(tmp_c, four, FPS, (960, 480))
wg = cv2.VideoWriter(tmp_g, four, FPS, (640, 480))
n, t0 = 0, time.time()
print("녹화 시작:", name, flush=True)
try:
    while not os.path.exists(stopf):
        f = {k: (c.frame if c.frame is not None else np.zeros((480, 640, 3), np.uint8)) for k, c in cams.items()}
        g = cv2.resize(f["desk"], (640, 480))
        small = [label(cv2.resize(f["front"], (320, 240)), "BELLY CAM"),
                 label(cv2.resize(f["wrist"], (320, 240)), "WRIST CAM")]
        comp = np.hstack([label(g.copy(), "GLOBAL CAM"), np.vstack(small)])
        wc.write(comp); wg.write(g); n += 1
        time.sleep(max(0, t0 + n / FPS - time.time()))
except KeyboardInterrupt:
    pass
wc.release(); wg.release()
for tmp, suf in ((tmp_c, "합본"), (tmp_g, "글로벌")):
    out = os.path.join(OUT, f"{name}_{suf}.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "23", out], check=True)
    os.remove(tmp)
    print("저장:", out, flush=True)
print(f"{n}프레임, {n / FPS:.0f}초", flush=True)
