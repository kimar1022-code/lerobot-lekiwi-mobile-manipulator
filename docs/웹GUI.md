# LeKiwi 웹 조종 GUI

카메라 3대 + 3D 모델 + 주행/팔 조종을 한 화면에서. 매트릭스 테마.

## 실행

```bash
# 1) Pi에서 호스트 데몬
ssh lekiwi '~/lekiwi_tools/run_host.sh -b'

# 2) 데스크탑에서 웹 서버
cd ~/lerobot && ./.venv/bin/python lekiwi_web.py

# 3) 브라우저
http://localhost:8080
```

같은 공유기에 붙은 폰 · 태블릿에서도 `http://192.168.75.137:8080` 으로 접속 가능.

## 화면

| 구역 | 내용 |
|------|------|
| CAM_01 // BELLY | 로봇 배 Arducam. **거꾸로 달려 있어 180° 자동 보정** |
| CAM_02 // WRIST | 손목 USB 카메라 |
| CAM_03 // EXTERNAL | 데스크탑 Logitech C270 (로봇을 밖에서 봄) |
| MODEL // LIVE POSE | 관절값을 실시간으로 반영하는 3D 모델 + 바닥 맵(지나온 길) |
| DRIVE | 바퀴 주행 (버튼 / 키보드) |
| MANIPULATOR | 팔 관절 6개 슬라이더 |
| AUTO PICK | 자율 집기 시작 · 멈춤, 진행 단계 6칸, 로그 |
| 맨 위 줄 | 로봇 연결, Pi 켜짐 · 배터리 %(충전 중이면 「충전 중」), 모터 배터리 전압 |

## 조종

| 키 | 동작 |
|---|---|
| `W` `S` | 앞 / 뒤 |
| `A` `D` | 왼쪽 / 오른쪽 (게걸음) |
| `Z` `X` | 좌회전 / 우회전 |
| VEL / ROT 슬라이더 | 속도 조절 |

3D 모델은 **드래그로 시점 회전, 휠로 확대**.

### 팔 조종

- `ARM UNLOCK` 을 눌러야 슬라이더가 로봇에 전달됨
- 켤 때 **현재 자세를 읽어와서** 시작하므로 갑자기 튀지 않음
- 리더팔로 조종할 거면 여긴 잠근 채로 둘 것
- `EMERGENCY STOP` - 바퀴 정지 + 팔 잠금

## 안전 장치

- **주행 워치독**: 0.6초 동안 명령이 안 오면 바퀴 자동 정지.
  브라우저를 닫거나 네트워크가 끊겨도 로봇이 달아나지 않음
- 팔 제어를 꺼둔 동안에는 **현재 자세를 계속 보내** 제자리를 유지

## 만들면서 걸렸던 것 (다시 겪지 말 것)

1. **`pynput` 미설치** - 키보드 주행 쓰는 스크립트를 처음 돌려서 드러남.
   `VIRTUAL_ENV=~/lerobot/.venv uv pip install pynput`
2. **`rerun-sdk` 미설치 + 뷰어 PATH** - 파이썬 패키지만으론 부족하고
   실행파일이 `~/lerobot/.venv/bin/rerun` 에 있어 PATH에 넣어야 함.
   (이 GUI를 쓰면 rerun 자체가 필요 없음)
3. **`send_action` 은 팔 목표값이 반드시 있어야 함** - 바퀴 값만 보내면
   `sync_write` 가 빈 딕셔너리로 터지고 Pi 로그에 `Message fetching failed` 가 쏟아짐.
   팔을 안 움직일 때도 **현재 자세를 같이 보내야** 한다.
4. **카메라는 numpy 배열(RGB)로 옴** - 이름이 `jpeg` 라 헷갈리지만
   `LeKiwiClient` 가 디코딩해서 준다. `if frame:` 로 판정하면
   "truth value of an array is ambiguous" 예외.
5. **HTML id 에 점(`.`)** - 관절 키가 `arm_shoulder_pan.pos` 라
   `querySelector('#v_arm_shoulder_pan.pos')` 가 "id + class" 로 해석돼 `null`.
   `getElementById` 를 쓸 것.
6. **`my_lekiwi_teleop.py` 의 기본 IP 가 옛 주소(.107)** 였음 → `.20` 으로 수정함.
7. **3D 모델이 「STL 불러오는 중」에서 멈추고 「SERVER DOWN」** (2026-10-07) - 브라우저는 같은 주소
   (`localhost:8080`)에 연결을 6개까지만 연다. 카메라 영상(`<img>` 로 계속 흘러오는 MJPEG)이 하나에 하나씩
   연결을 붙잡고, Chrome 은 새로고침해도 이전 영상 연결을 끊지 않아 3개씩 쌓였다. 6개가 차면 3D 파일도,
   상태 정보(`/api/state`)도 줄만 서고 안 받아진다. 서버는 정상이라 `curl` 로는 멀쩡해 보인다.
   - 영상은 다른 주소 이름으로 받는다. 화면을 `localhost` 로 열면 영상은 `127.0.0.1` 로(반대도 같음).
     브라우저는 둘을 다른 주소로 보고 연결 6개를 따로 센다.
   - 영상은 3D 모델을 다 받은 뒤에 켠다(20초 넘게 걸리면 먼저 켬).
   - 페이지를 떠날 때(`pagehide`) 영상 연결을 끊는다.
   - 이미 쌓인 연결은 웹 서버를 다시 켜면 풀린다. 다시 켜도 팔 힘은 유지되고 로봇에 자동으로 다시 붙는다.
   - 원인 찾기: `ss -tnp state established '( dport = :8080 )'` 로 chrome 연결 수를 셌다.
8. **상태 표시용 배터리 읽기가 로봇 호스트를 죽임** (2026-10-05~06) - 모터 포트를 따로 열어 전압을 읽으면
   호스트의 모터 명령과 패킷이 섞여 「Port is in use」 로 죽었다. 호스트가 10초마다 직접 읽어 파일로 남기고
   (`pi_tools/lekiwi_host_plus.py`), 화면은 그 파일을 SSH 로 가져온다.

## 파일

```
~/lerobot/
├── lekiwi_web.py            서버 (Flask + LeKiwiClient)
├── lekiwi_web.html          화면
├── static/three.module.js   3D 라이브러리 (로컬 보관, 인터넷 없어도 됨)
└── my_lekiwi_teleop.py      리더팔+키보드 조종 (기존 방식)
```

## 설정 바꾸기

`lekiwi_web.py` 위쪽:

```python
PI_IP = "192.168.75.20"      # 로봇 IP
WEB_PORT = 8080
DESK_CAM = 0                 # 데스크탑 웹캠 번호
FRONT_ROTATE_180 = True      # 배 카메라 뒤집힘 보정
```

환경변수로도 됨: `LEKIWI_IP=... WEB_PORT=... python lekiwi_web.py`

## 3D 디지털 트윈 (2026-08-29 추가)

실제 STL 로 만든 LeKiwi 전체 모델(베이스+옴니휠+팔)이 로봇 자세를 실시간으로 따라간다.

### 출처

| 항목 | 출처 |
|------|------|
| 전체 URDF | `github.com/SIGRobotics-UIUC/LeKiwi` → `URDF/LeKiwi.urdf` |
| 메시(STL) | 같은 저장소 `URDF/meshes/` |
| 관절 가동범위 | `github.com/TheRobotStudio/SO-ARM100` → `Simulation/SO101/so101_new_calib.urdf` |

로컬 보관 위치: `static/lekiwi_full.urdf`, `static/meshes6/`, `static/lekiwi_model.json`

### 각도 변환 - 여기서 제일 많이 틀렸다

lerobot 이 관절값을 각도로 바꾸는 정의(`MotorNormMode.DEGREES`)를 그대로 따라야 한다:

```
mid   = (range_min + range_max) / 2      <- 이 위치가 0도
각도  = (raw - mid) * 360 / 4095
```

**0도 기준은 캘리브레이션 범위의 중앙이지 엔코더 중앙(2048)이 아니다.**
우리 로봇의 어깨들기는 중앙이 2980 이라, 2048 을 0도로 잡으면 82도나 어긋나
관절 리밋을 넘고 3D 팔이 베이스 판을 뚫고 들어간다.

정규화값에서 raw 를 되돌리는 식:
```
raw = range_min + ((norm + 100) / 200) * (range_max - range_min)     # 팔 5축
raw = range_min + (norm / 100)         * (range_max - range_min)     # 그리퍼만 0~100
```

계산된 각도는 URDF 가동범위로 잘라낸다(`Math.max/min`). 어떤 값이 와도 판을 통과하지 않는다.

### 그밖에 걸렸던 것

| 증상 | 원인 |
|------|------|
| 부품이 뿔뿔이 흩어져 조립됨 | URDF 의 `rpy` 는 `Rz·Ry·Rx` 순서. three.js 기본(`XYZ`)이라 `'ZYX'` 를 명시해야 함 |
| 모델이 화면을 초록으로 꽉 채움 | LeKiwi STL 은 mm 단위라 URDF 에 `scale="0.001"` 이 있음. 이걸 무시하면 1000배 |
| 3D 가 아예 안 움직임 | LeKiwi URDF 관절은 `continuous` 타입. `revolute` 만 찾으면 하나도 안 잡힘 |
| 브라우저가 얼어붙음 | 옴니휠 STL 이 개당 15MB(3개=45MB). 정점 격자 병합으로 삼각형 122만→8.8만 |
| 새로고침마다 수십 초 | STL 에 캐시 헤더가 없었음 → `after_request` 로 `max-age=86400` |
| 상태 표시가 멈춤 | 보정 패널 슬라이더가 팔 관절과 같은 `.joint` 클래스라 폴링이 오작동 |

### 메시 간소화

`/tmp/decimate.py` 방식(정점 격자 병합)을 썼다. trimesh 같은 라이브러리 없이 numpy 만으로 동작한다.
법선을 STL 에 미리 넣어 브라우저가 `computeVertexNormals` 를 부르지 않게 하는 것도 큰 차이를 낸다.

### 각도 보정 패널

3D 뷰 아래 `▸ 각도 보정` 에서 관절별 **방향(±)** 과 **오프셋(도)** 을 조정할 수 있다.
브라우저에 저장되며(`localStorage`), 잘 맞은 값은 `lekiwi_web.html` 의 `ADJ_DEFAULT` 에 옮겨
기본값으로 만들면 다른 PC 에서도 바로 맞는다.

## 3D 모델 구성 - 두 URDF 를 합쳤다 (2026-08-29 최종)

```
베이스(옴니휠 3개, 플레이트, Pi 케이스)  <-  LeKiwi URDF
              | base_to_arm (고정)
팔 6축 (어깨 ~ 그리퍼)                    <-  SO101 URDF
```

### 왜 나눠 썼나

LeKiwi URDF 하나로 하면 **관절 부호가 실물과 반대로 나온다.**
두 URDF 가 다른 도구로 만들어져 축 규약이 다르기 때문이다.

- LeKiwi URDF: 관절이 `continuous`(가동범위 없음), `axis=[1,0,0]` 등 제각각
- SO101 URDF: 전부 `axis=[0,0,1]`, 가동범위가 **lerobot 값과 거의 일치**
  (어깨들기 ±97.9°(lerobot) vs ±100°(URDF), 팔꿈치 ±97.5° vs ±96.8°)

즉 **SO101 URDF 의 각도 정의 = lerobot 의 각도 정의**다. 팔을 SO101 로 쓰면
부호 보정이 필요 없다(`ADJ_DEFAULT` 가 전부 sign=1, off=0).

### 두 URDF 를 잇는 변환은 계산으로 구했다

같은 부품(팔 베이스)을 두 URDF 가 각각 어떻게 놓았는지 비교하면 나온다.

| | 팔 베이스 메시 방향 |
|---|---|
| LeKiwi `Base_08q-v1` | `xyz=[-0.04,-0.0581,-0.0024]  rpy=[90°,0°,-180°]` |
| SO101 `base_link` | `xyz=[-0.0064,0,-0.0024]  rpy=[90°,0°,90°]` |

메시가 같은 자리에 오려면
`so_base_link = LeKiwi_link * lk_visual * so_visual⁻¹`

계산 결과 **xyz=[0, 0.0283, 0.007], rpy=[0, 0, 90°]** - 딱 떨어지는 값이라
시행착오가 아니라 정답임을 알 수 있다.

### 메시

| 폴더 | 내용 | 크기 |
|------|------|------|
| `static/meshes6/` | LeKiwi 베이스 (mm 단위, URDF 에 scale 0.001) | 4.4MB |
| `static/meshes_so101/` | SO101 팔 (m 단위) | 684KB |

둘 다 정점 격자 병합으로 간소화했다(`/tmp/decimate.py` 방식).
JSON 의 각 visual 에 `dir` 필드로 어느 폴더인지 적어 둔다.


## 바닥 맵 (2026-10-07 추가)

3D 화면의 로봇이 바닥 격자 위를 실제로 움직인 만큼 돌아다니고, 지나온 길을 노란 점선으로 그린다.

### 어떻게 위치를 아나

로봇 호스트는 바퀴 세 개의 실제 회전 속도(`Present_Velocity`)를 읽어 몸체 속도로 바꿔 보내 준다
(`x.vel` · `y.vel` m/s, `theta.vel` 도/초). 웹 서버가 관측이 올 때마다 여기에 시간을 곱해 더한다.

```
x += (vx · cos θ - vy · sin θ) · dt
y += (vx · sin θ + vy · cos θ) · dt
θ += ω · dt
```

- 멈춰 있을 때 잡음이 쌓이지 않게 아주 작은 속도(4mm/s, 0.6°/s 미만)는 0 으로 본다.
- 관측이 끊겼다 이어지면 그 사이를 한 번에 더하지 않는다(dt 최대 0.2초, 관측이 0.5초 넘게 묵으면 쌓지 않음).
- 2cm 움직일 때마다 길에 점 하나를 남긴다.

| API | 내용 |
| --- | --- |
| `/api/pose` 의 `o` · `v` | 위치 [x, y, θ] · 바퀴로 잰 속도 (20Hz 로 화면이 가져감) |
| `/api/path` | 지나온 길 전체 (1초마다) |
| `/api/odom_reset` (POST) | 지금 자리를 원점으로, 길 지우기 |

### 화면 좌표

3D 모델에서 로봇 앞(배캠 받침대 쪽)은 모델의 +y, 화면(three.js, 위가 +y)에서는 -z 다.
그래서 위치 (앞 x, 왼쪽 y) 는 화면 (x, z) = (-y, -x) 로, 반시계 회전 θ 는 `rotation.y = θ` 로 옮긴다.

바퀴는 로봇과 연결돼 있으면 잰 속도로, 아니면 예전처럼 키보드 주행 명령으로 굴린다.
바퀴 하나의 회전속도는 lerobot `lekiwi.py` 의 `_body_to_wheel_raw` 와 같은 식(바퀴 반지름 0.05m,
중심~바퀴 0.125m, 배치각 150 · -90 · 30°)으로 구한다.

### 확인

| 명령 | 계산된 값 |
| --- | --- |
| 왼쪽 45° 회전 | 46° |
| 앞으로 10cm | 10.0cm |
| 앞 20cm → 왼쪽 90° → 앞 16cm | (0.20, 0.16) m, 92° |
| 같은 길로 되돌아오기 | 원점에서 0.5cm · 0.5° |

바퀴로 잰 값이라 미끄러지거나 걸리면(충전기 선 등) 실제와 어긋난다. 「원점」 버튼으로 다시 맞춘다.
방 구조(벽 · 가구)는 그리지 않는다. 보관함 마커가 보일 때 위치를 바로잡는 것이 다음 단계.
