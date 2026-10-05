"""보관함용 ArUco 마커 인쇄 파일(A4, 300dpi PDF) 만들기.

검은 마커 한 변 = 3.5cm (거리 계산에 쓰는 실제 크기).
ID 0 = 정면, ID 1~3 = 나머지 면(나중에 필요하면).
※ 인쇄할 때 반드시 '실제 크기(100%)' — '페이지에 맞춤' 끄기.
"""
import os
import sys
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

DPI = 300
CM = DPI / 2.54                     # 1cm 당 픽셀
DICT = cv2.aruco.DICT_4X4_50        # 칸이 커서 멀리서도 잘 읽힘
MARKER_CM = float(sys.argv[1]) if len(sys.argv) > 1 else 3.5
CELLS = 6                           # 4x4 무늬 + 검은 테두리 1칸씩
cell_px = round(MARKER_CM * CM / CELLS)
M_PX = cell_px * CELLS              # 69*6 = 414px = 3.505cm

W, H = round(21.0 * CM), round(29.7 * CM)
page = Image.new("L", (W, H), 255)
d = ImageDraw.Draw(page)
font = lambda s: ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", s)
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

d.text((round(1.5 * CM), round(1.2 * CM)), f"LeKiwi 보관함 마커 — ArUco 4x4_50, 검은 사각형 한 변 {MARKER_CM}cm",
       fill=0, font=ImageFont.truetype(FONT, 46))
d.text((round(1.5 * CM), round(2.0 * CM)), "인쇄: 실제 크기(100%) · '페이지에 맞춤' 끄기 · 아래 자로 크기 확인",
       fill=0, font=ImageFont.truetype(FONT, 38))

aruco = cv2.aruco.getPredefinedDictionary(DICT)
labels = {0: "ID 0 — 정면", 1: "ID 1 — 오른쪽", 2: "ID 2 — 뒤", 3: "ID 3 — 왼쪽"}
margin = cell_px if MARKER_CM < 3.5 else round(1.0 * CM)  # 흰 여백(작은 판은 무늬 1칸)
for k, mid in enumerate(labels):
    col, row = k % 2, k // 2
    x0 = round((2.5 + col * 8.5) * CM); y0 = round((4.0 + row * 8.0) * CM)
    img = cv2.aruco.generateImageMarker(aruco, mid, M_PX)
    page.paste(Image.fromarray(img), (x0, y0))
    # 자르는 선(점선): 마커 바깥 1cm
    bx0, by0, bx1, by1 = x0 - margin, y0 - margin, x0 + M_PX + margin, y0 + M_PX + margin
    for t in range(bx0, bx1, 30):
        d.line([(t, by0), (min(t + 15, bx1), by0)], fill=120, width=2)
        d.line([(t, by1), (min(t + 15, bx1), by1)], fill=120, width=2)
    for t in range(by0, by1, 30):
        d.line([(bx0, t), (bx0, min(t + 15, by1))], fill=120, width=2)
        d.line([(bx1, t), (bx1, min(t + 15, by1))], fill=120, width=2)
    d.text((bx0, by1 + 15), labels[mid] + ("  ← 먼저 이것만 붙이기" if mid == 0 else ""),
           fill=0, font=ImageFont.truetype(FONT, 40))

# 10cm 자 (mm 눈금) — 인쇄 후 실제 자로 대보기
rx, ry = round(1.5 * CM), round(22.0 * CM)
d.line([(rx, ry), (rx + round(10 * CM), ry)], fill=0, width=3)
for mm in range(0, 101):
    x = rx + round(mm * CM / 10)
    h = 50 if mm % 10 == 0 else (32 if mm % 5 == 0 else 18)
    d.line([(x, ry), (x, ry + h)], fill=0, width=3 if mm % 10 == 0 else 2)
    if mm % 10 == 0:
        d.text((x - 10, ry + 55), str(mm // 10), fill=0, font=ImageFont.truetype(FONT, 34))
d.text((rx, ry + 110), f"이 자가 실제 10cm 이고 검은 사각형이 {MARKER_CM}cm 이면 정상", fill=0,
       font=ImageFont.truetype(FONT, 38))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"aruco_box_{MARKER_CM}cm.pdf")
page.save(out, resolution=DPI)
page.save(out.replace(".pdf", ".png"), dpi=(DPI, DPI))
print(out, f"마커 {M_PX}px = {M_PX / CM:.3f}cm")
