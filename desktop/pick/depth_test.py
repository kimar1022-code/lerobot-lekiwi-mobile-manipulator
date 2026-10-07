# 깊이 AI(Depth Anything V2 Small) 시험: 사진 → 깊이맵 + 칸 10개별 "바닥 끝" 높이와 cm
import sys, time, cv2, numpy as np
from transformers import pipeline
from PIL import Image
from calib_cam import floor_cm
pipe = pipeline("depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=0)
pipe(Image.new("RGB", (640, 480)))                       # 첫 실행은 느려서 미리 한 번
# 바닥 끝 (x, y) → 범퍼 기준 앞쪽 cm: 렌즈 보정값 + 카메라 높이 · 숙임(calib_cam.py)
# 예전엔 실측 세 점(y 260·284·342)을 직선으로 이었는데, 30cm 보다 가까우면 직선 연장이라
# 화면 맨 아래가 -10cm 로 나왔음 → 보정값 계산으로 바꿈(2026-10-07, 세 점과 0.1cm 안으로 일치)
def xy2cm(x, y):
    r = floor_cm(x, y)
    if r is None or r[0] > 70: return None              # 70cm 넘으면 실측 확인 범위 밖
    return r[0]
for p in sys.argv[1:]:
    img = Image.open(p).convert("RGB")
    t = time.time(); d = pipe(img)["predicted_depth"]; dt = time.time() - t
    d = cv2.resize(np.asarray(d.squeeze().cpu() if hasattr(d, "cpu") else d, np.float32), img.size)
    n = (d - d.min()) / (d.max() - d.min() + 1e-6)          # 클수록 가까움
    H, W = n.shape
    vis = cv2.applyColorMap((n * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    res = []
    for k in range(10):
        x0, x1 = k * W // 10, (k + 1) * W // 10
        y = H - 15                                         # 맨 아래 가장자리는 잡음이 있어 건너뜀
        # 칸 안 세로줄 여러 개 중 15% 이상이 끊기면 거기가 바닥 끝(평균 내면 작은 물체가 묻힘)
        # 한 줄만 반짝 끊기는 잡음은 무시: 3줄 연속으로 끊겨야 인정
        cols, bad = n[:, x0:x1:4], 0
        while y > 5:
            bad = bad + 1 if np.mean(cols[y - 5] >= cols[y] - 0.004) >= 0.15 else 0
            if bad >= 3:
                y += 2; break
            y -= 1
        cm = xy2cm((x0 + x1) / 2, y); res.append(f"{'>70' if cm is None else round(cm)}")
        cv2.line(vis, (x0, y), (x1, y), (0, 255, 0), 3)
        cv2.putText(vis, res[-1], (x0 + 4, max(y - 8, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    out = p.rsplit(".", 1)[0] + "_depth.jpg"
    cv2.imwrite(out, np.hstack([cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR), vis]))
    print(p.split("/")[-1], f"{dt*1000:.0f}ms", "칸별 cm:", " ".join(res))
