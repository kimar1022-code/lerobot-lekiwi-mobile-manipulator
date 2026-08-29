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

같은 공유기에 붙은 폰·태블릿에서도 `http://192.168.75.137:8080` 으로 접속 가능.

## 화면

| 구역 | 내용 |
|------|------|
| CAM_01 // BELLY | 로봇 배 Arducam. **거꾸로 달려 있어 180° 자동 보정** |
| CAM_02 // WRIST | 손목 USB 카메라 |
| CAM_03 // EXTERNAL | 데스크탑 Logitech C270 (로봇을 밖에서 봄) |
| MODEL // LIVE POSE | 관절값을 실시간으로 반영하는 와이어프레임 3D 모델 |
| DRIVE | 바퀴 주행 (버튼 / 키보드) |
| MANIPULATOR | 팔 관절 6개 슬라이더 |

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
- `EMERGENCY STOP` — 바퀴 정지 + 팔 잠금

## 안전 장치

- **주행 워치독**: 0.6초 동안 명령이 안 오면 바퀴 자동 정지.
  브라우저를 닫거나 네트워크가 끊겨도 로봇이 달아나지 않음
- 팔 제어를 꺼둔 동안에는 **현재 자세를 계속 보내** 제자리를 유지

## 만들면서 걸렸던 것 (다시 겪지 말 것)

1. **`pynput` 미설치** — 키보드 주행 쓰는 스크립트를 처음 돌려서 드러남.
   `VIRTUAL_ENV=~/lerobot/.venv uv pip install pynput`
2. **`rerun-sdk` 미설치 + 뷰어 PATH** — 파이썬 패키지만으론 부족하고
   실행파일이 `~/lerobot/.venv/bin/rerun` 에 있어 PATH에 넣어야 함.
   (이 GUI를 쓰면 rerun 자체가 필요 없음)
3. **`send_action` 은 팔 목표값이 반드시 있어야 함** — 바퀴 값만 보내면
   `sync_write` 가 빈 딕셔너리로 터지고 Pi 로그에 `Message fetching failed` 가 쏟아짐.
   팔을 안 움직일 때도 **현재 자세를 같이 보내야** 한다.
4. **카메라는 numpy 배열(RGB)로 옴** — 이름이 `jpeg` 라 헷갈리지만
   `LeKiwiClient` 가 디코딩해서 준다. `if frame:` 로 판정하면
   "truth value of an array is ambiguous" 예외.
5. **HTML id 에 점(`.`)** — 관절 키가 `arm_shoulder_pan.pos` 라
   `querySelector('#v_arm_shoulder_pan.pos')` 가 "id + class" 로 해석돼 `null`.
   `getElementById` 를 쓸 것.
6. **`my_lekiwi_teleop.py` 의 기본 IP 가 옛 주소(.107)** 였음 → `.20` 으로 수정함.

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

### 각도 변환 — 여기서 제일 많이 틀렸다

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

## 3D 모델 구성 — 두 URDF 를 합쳤다 (2026-08-29 최종)

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

계산 결과 **xyz=[0, 0.0283, 0.007], rpy=[0, 0, 90°]** — 딱 떨어지는 값이라
시행착오가 아니라 정답임을 알 수 있다.

### 메시

| 폴더 | 내용 | 크기 |
|------|------|------|
| `static/meshes6/` | LeKiwi 베이스 (mm 단위, URDF 에 scale 0.001) | 4.4MB |
| `static/meshes_so101/` | SO101 팔 (m 단위) | 684KB |

둘 다 정점 격자 병합으로 간소화했다(`/tmp/decimate.py` 방식).
JSON 의 각 visual 에 `dir` 필드로 어느 폴더인지 적어 둔다.
