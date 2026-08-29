#!/usr/bin/env python3
"""3D 트윈에 쓰는 메시를 공개 저장소에서 받아 브라우저용으로 준비한다.

세 곳에서 가져온다.
  · LeKiwi 베이스   SIGRobotics-UIUC/LeKiwi          (URDF + STL, mm 단위)
  · SO-101 팔       TheRobotStudio/SO-ARM100         (URDF + STL, m 단위)
  · PincOpen 그리퍼 kimar1022-code/smart-factory-soarm101 (DAE)

원본 STL 은 옴니휠 하나가 15MB 나 돼 브라우저가 멈춘다. 정점을 격자로 묶어
합쳐 삼각형을 줄이고(약 7%), 법선을 미리 계산해 넣어 로딩을 빠르게 만든다.

사용법:
    python3 fetch_meshes.py          # static/ 아래에 준비
"""
import json
import os
import struct
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'static')

LEKIWI = 'https://raw.githubusercontent.com/SIGRobotics-UIUC/LeKiwi/main'
SOARM = 'https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/main/Simulation/SO101'
PINC = 'https://raw.githubusercontent.com/kimar1022-code/smart-factory-soarm101/main'


def get(url, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return
    with urllib.request.urlopen(url, timeout=60) as r, open(dst, 'wb') as f:
        f.write(r.read())


# ── STL 읽기/쓰기 ────────────────────────────────────────────────────
def read_stl(path):
    with open(path, 'rb') as f:
        n = struct.unpack('<I', f.read(84)[80:84])[0]
        data = np.frombuffer(f.read(n * 50), dtype=np.uint8)
    if len(data) < n * 50:
        return None
    return data.reshape(n, 50)[:, 12:48].copy().view('<f4').reshape(n, 3, 3)


def write_stl(path, tris):
    """법선까지 계산해 넣는다(브라우저가 다시 계산하지 않게)."""
    n = len(tris)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    nz = np.cross(b - a, c - a)
    ln = np.linalg.norm(nz, axis=1, keepdims=True)
    ln[ln == 0] = 1
    buf = np.zeros((n, 50), dtype=np.uint8)
    buf[:, 0:12] = (nz / ln).astype('<f4').reshape(n, 3).view(np.uint8)
    buf[:, 12:48] = tris.astype('<f4').reshape(n, 9).view(np.uint8)
    with open(path, 'wb') as f:
        f.write(b'\0' * 80)
        f.write(struct.pack('<I', n))
        f.write(buf.tobytes())


def simplify(tris, cells=26):
    """정점 격자 병합. 같은 칸에 든 정점을 대표점 하나로 합친다."""
    v = tris.reshape(-1, 3)
    lo, hi = v.min(0), v.max(0)
    size = (hi - lo).max()
    if size <= 0:
        return tris
    cell = size / cells
    key = np.floor((v - lo) / cell).astype(np.int64)
    k = (key[:, 0] * 1_000_003 + key[:, 1]) * 1_000_003 + key[:, 2]
    uniq, inv = np.unique(k, return_inverse=True)
    rep = np.zeros((len(uniq), 3))
    cnt = np.bincount(inv, minlength=len(uniq)).reshape(-1, 1)
    for i in range(3):
        rep[:, i] = np.bincount(inv, weights=v[:, i], minlength=len(uniq))
    rep /= cnt
    nv = rep[inv].reshape(-1, 3, 3)
    a, b, c = nv[:, 0], nv[:, 1], nv[:, 2]
    ok = ~(np.all(a == b, 1) | np.all(b == c, 1) | np.all(a == c, 1))
    return nv[ok]


def convert(src, dst, thresh=1200):
    t = read_stl(src)
    if t is None:
        return 0
    out = simplify(t) if len(t) > thresh else t
    write_stl(dst, out)
    return len(out)


# ── DAE(COLLADA) -> 삼각형 ───────────────────────────────────────────
def parse_dae(path):
    root = ET.parse(path).getroot()
    src = {}
    for s in root.iter():
        if s.tag.endswith('}source'):
            for ch in s:
                if ch.tag.endswith('}float_array'):
                    src['#' + s.get('id')] = np.fromstring(ch.text, sep=' ')
    tris = []
    for geo in root.iter():
        if not geo.tag.endswith('}mesh'):
            continue
        vmap = {}
        for v in geo:
            if v.tag.endswith('}vertices'):
                for inp in v:
                    if inp.get('semantic') == 'POSITION':
                        vmap['#' + v.get('id')] = inp.get('source')
        for prim in geo:
            if prim.tag.split('}')[-1] not in ('triangles', 'polylist'):
                continue
            inputs = [i for i in prim if i.tag.endswith('}input')]
            stride = max(int(i.get('offset', 0)) for i in inputs) + 1
            off = psrc = None
            for i in inputs:
                if i.get('semantic') == 'VERTEX':
                    off = int(i.get('offset', 0))
                    psrc = vmap.get(i.get('source'), i.get('source'))
            arr = src.get(psrc)
            if arr is None:
                continue
            p = None
            for ch in prim:
                if ch.tag.endswith('}p'):
                    p = np.fromstring(ch.text, sep=' ', dtype=np.int64)
            if p is None:
                continue
            idx = p.reshape(-1, stride)[:, off]
            idx = idx[:len(idx) // 3 * 3]
            tris.append(arr.reshape(-1, 3)[idx].reshape(-1, 3, 3))
    return np.concatenate(tris) if tris else None


def vec(s, d=(0, 0, 0)):
    return [float(x) for x in s.split()] if s else list(d)


def main():
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, '_tmp')
    os.makedirs(tmp, exist_ok=True)

    print('three.js 받는 중...')
    get('https://unpkg.com/three@0.160.0/build/three.module.js',
        os.path.join(OUT, 'three.module.js'))
    get('https://unpkg.com/three@0.160.0/examples/jsm/loaders/STLLoader.js',
        os.path.join(OUT, 'STLLoader.js'))

    print('URDF 받는 중...')
    get(f'{LEKIWI}/URDF/LeKiwi.urdf', os.path.join(tmp, 'lekiwi_full.urdf'))
    get(f'{SOARM}/so101_new_calib.urdf', os.path.join(tmp, 'so101.urdf'))
    get(f'{PINC}/Assets/SO101_unity/so101.urdf', os.path.join(tmp, 'pincopen.urdf'))

    # ── LeKiwi 베이스 메시 ──
    print('LeKiwi 베이스 메시...')
    lk = ET.parse(os.path.join(tmp, 'lekiwi_full.urdf')).getroot()
    names = {m.get('filename', '').split('/')[-1] for m in lk.iter('mesh')}
    d6 = os.path.join(OUT, 'meshes6')
    os.makedirs(d6, exist_ok=True)
    tot = 0
    for fn in sorted(n for n in names if n):
        raw = os.path.join(tmp, 'lk_' + fn)
        get(f'{LEKIWI}/URDF/meshes/{urllib.parse.quote(fn)}', raw)
        tot += convert(raw, os.path.join(d6, fn))
    print(f'  삼각형 {tot:,}')

    # ── SO-101 팔 메시 ──
    print('SO-101 팔 메시...')
    so = ET.parse(os.path.join(tmp, 'so101.urdf')).getroot()
    names = {m.get('filename', '').split('/')[-1] for m in so.iter('mesh')}
    ds = os.path.join(OUT, 'meshes_so101')
    os.makedirs(ds, exist_ok=True)
    tot = 0
    for fn in sorted(n for n in names if n):
        raw = os.path.join(tmp, 'so_' + fn)
        get(f'{SOARM}/assets/{urllib.parse.quote(fn)}', raw)
        tot += convert(raw, os.path.join(ds, fn))
    print(f'  삼각형 {tot:,}')

    # ── PincOpen 그리퍼 (DAE -> STL) ──
    print('PincOpen 그리퍼 메시...')
    dp = os.path.join(OUT, 'meshes_pinc2')
    os.makedirs(dp, exist_ok=True)
    tot = 0
    for src_name, out_name in [('base', 'base'), ('left_proximal', 'left_proximal'),
                               ('left_distal', 'left_distal'),
                               ('right_proximal', 'right_proximal'),
                               ('right_distal', 'right_distal'),
                               ('Interface_ARM100', 'Interface_ARM100')]:
        raw = os.path.join(tmp, f'pinc_{src_name}.dae')
        get(f'{PINC}/Assets/SO101_unity/meshes/PincOpen/visual/{src_name}.dae', raw)
        t = parse_dae(raw)
        if t is None:
            continue
        out = simplify(t) if len(t) > 1200 else t
        write_stl(os.path.join(dp, out_name + '.stl'), out)
        tot += len(out)
    print(f'  삼각형 {tot:,}')

    print('모델 구조(JSON) 만드는 중...')
    build_model(tmp)
    print(f'\n완료. {OUT} 아래에 준비됐다.')


def build_model(tmp):
    """세 URDF 를 합쳐 브라우저가 읽을 JSON 하나로 만든다.

    · 베이스는 LeKiwi URDF
    · 팔은 SO-101 URDF (이쪽 각도 정의가 lerobot 과 같아 부호 보정이 필요 없다)
    · 그리퍼는 PincOpen (Unity URDF 의 확정 장착값 사용)
    """
    so = ET.parse(os.path.join(tmp, 'so101.urdf')).getroot()
    limits = {}
    for J in so.findall('joint'):
        lim = J.find('limit')
        if lim is not None and lim.get('lower'):
            limits[J.get('name')] = (float(lim.get('lower')), float(lim.get('upper')))

    # 1) LeKiwi 에서 베이스만 (팔은 SO-101 로 갈아끼운다)
    lk = ET.parse(os.path.join(tmp, 'lekiwi_full.urdf')).getroot()
    ARM_ROOT = 'Base_08q-v1'
    lkj = [{'name': J.get('name'), 'type': J.get('type'),
            'parent': J.find('parent').get('link'), 'child': J.find('child').get('link'),
            'xyz': vec(J.find('origin').get('xyz') if J.find('origin') is not None else None),
            'rpy': vec(J.find('origin').get('rpy') if J.find('origin') is not None else None),
            'axis': vec(J.find('axis').get('xyz') if J.find('axis') is not None else None, (0, 0, 1))}
           for J in lk.findall('joint')]
    kids = {}
    for j in lkj:
        kids.setdefault(j['parent'], []).append(j['child'])
    arm_side, stack = set(), [ARM_ROOT]
    while stack:
        n = stack.pop()
        if n in arm_side:
            continue
        arm_side.add(n)
        stack += kids.get(n, [])

    SKIP = ('94868A713', 'Battery---Battery')
    links, mount = {}, None
    for L in lk.findall('link'):
        if L.get('name') in arm_side:
            continue
        vis = []
        for v in L.findall('visual'):
            o, g = v.find('origin'), v.find('geometry/mesh')
            if g is None:
                continue
            fn = g.get('filename', '').split('/')[-1]
            if any(k in fn for k in SKIP):
                continue
            vis.append({'mesh': fn, 'dir': 'meshes6',
                        'xyz': vec(o.get('xyz') if o is not None else None),
                        'rpy': vec(o.get('rpy') if o is not None else None),
                        'scale': vec(g.get('scale'), (1, 1, 1))})
        links[L.get('name')] = vis
    joints = [j for j in lkj if j['child'] not in arm_side]
    for j in lkj:
        if j['child'] == ARM_ROOT:
            mount = j

    # 2) SO-101 팔 (so_ 접두사)
    for L in so.findall('link'):
        vis = []
        for v in L.findall('visual'):
            o, g = v.find('origin'), v.find('geometry/mesh')
            if g is None:
                continue
            vis.append({'mesh': g.get('filename', '').split('/')[-1], 'dir': 'meshes_so101',
                        'xyz': vec(o.get('xyz') if o is not None else None),
                        'rpy': vec(o.get('rpy') if o is not None else None),
                        'scale': vec(g.get('scale'), (1, 1, 1))})
        links['so_' + L.get('name')] = vis
    for J in so.findall('joint'):
        o, a, lim = J.find('origin'), J.find('axis'), J.find('limit')
        nm = J.get('name')
        joints.append({'name': ('arm_' + nm) if lim is not None else ('so_' + nm),
                       'type': J.get('type'),
                       'parent': 'so_' + J.find('parent').get('link'),
                       'child': 'so_' + J.find('child').get('link'),
                       'xyz': vec(o.get('xyz') if o is not None else None),
                       'rpy': vec(o.get('rpy') if o is not None else None),
                       'axis': vec(a.get('xyz') if a is not None else None, (0, 0, 1)),
                       'lower': float(lim.get('lower')) if lim is not None and lim.get('lower') else None,
                       'upper': float(lim.get('upper')) if lim is not None and lim.get('upper') else None})

    # 베이스와 팔을 잇는 변환.
    # 같은 부품(팔 베이스)을 두 URDF 가 각각 어떻게 놓았는지 비교해서 구한다:
    #   so_base_link = LeKiwi_link * lk_visual * so_visual⁻¹
    def R(r, p, y):
        cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
        return (np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
                @ np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
                @ np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]]))

    def T(xyz, rpy):
        M = np.eye(4); M[:3, :3] = R(*rpy); M[:3, 3] = xyz
        return M

    lk_vis = so_vis = None
    for L in lk.findall('link'):
        if L.get('name') == ARM_ROOT:
            v = L.find('visual'); o = v.find('origin')
            lk_vis = T(vec(o.get('xyz')), vec(o.get('rpy')))
    for L in so.findall('link'):
        if L.get('name') == 'base_link':
            for v in L.findall('visual'):
                if 'base_so101' in v.find('geometry/mesh').get('filename', ''):
                    o = v.find('origin')
                    so_vis = T(vec(o.get('xyz')), vec(o.get('rpy')))
    rel = T(mount['xyz'], mount['rpy']) @ lk_vis @ np.linalg.inv(so_vis)
    Rm = rel[:3, :3]
    pitch = np.arctan2(-Rm[2, 0], np.hypot(Rm[0, 0], Rm[1, 0]))
    roll = np.arctan2(Rm[2, 1], Rm[2, 2]); yaw = np.arctan2(Rm[1, 0], Rm[0, 0])
    joints.append({'name': 'base_to_arm', 'type': 'fixed',
                   'parent': mount['parent'], 'child': 'so_base_link',
                   'xyz': [float(x) for x in rel[:3, 3]], 'rpy': [roll, pitch, yaw],
                   'axis': [0, 0, 1], 'lower': None, 'upper': None})

    # 3) PincOpen 그리퍼 (순정 조는 빼고 갈아끼운다)
    links.pop('so_moving_jaw_so101_v1_link', None)
    joints = [j for j in joints if j['child'] != 'so_moving_jaw_so101_v1_link']
    links['so_gripper_link'] = []      # PincOpen 이 그 자리를 대신한다

    MESH = {'pincopen_adapter_link': 'Interface_ARM100.stl',
            'pincopen_base_link': 'base.stl',
            'pincopen_left_proximal_link': 'left_proximal.stl',
            'pincopen_left_distal_link': 'left_distal.stl',
            'pincopen_right_proximal_link': 'right_proximal.stl',
            'pincopen_right_distal_link': 'right_distal.stl'}
    for k, v in MESH.items():
        links[k] = [{'mesh': v, 'dir': 'meshes_pinc2',
                     'xyz': [0, 0, 0], 'rpy': [0, 0, 0], 'scale': [1, 1, 1]}]

    pu = ET.parse(os.path.join(tmp, 'pincopen.urdf')).getroot()
    for J in pu.findall('joint'):
        ch = J.find('child').get('link')
        if ch not in MESH:
            continue
        o, a, lim = J.find('origin'), J.find('axis'), J.find('limit')
        par = J.find('parent').get('link')
        joints.append({'name': 'arm_gripper' if J.get('name') == 'gripper' else J.get('name'),
                       'type': J.get('type'),
                       'parent': 'so_gripper_link' if par == 'gripper_link' else par,
                       'child': ch,
                       'xyz': vec(o.get('xyz') if o is not None else None),
                       'rpy': vec(o.get('rpy') if o is not None else None),
                       'axis': vec(a.get('xyz') if a is not None else None, (0, 0, 1)),
                       'lower': float(lim.get('lower')) if lim is not None and lim.get('lower') else None,
                       'upper': float(lim.get('upper')) if lim is not None and lim.get('upper') else None})

    with open(os.path.join(OUT, 'lekiwi_model.json'), 'w') as f:
        json.dump({'links': links, 'joints': joints}, f, indent=1)
    print(f'  링크 {len(links)}개 / 조인트 {len(joints)}개')


if __name__ == '__main__':
    main()
