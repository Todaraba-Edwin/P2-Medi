"""브랜드 시트(images/logo_can_i_ppiyak.png, 1536x1024)를 그림별 투명 PNG로 자른다. Pillow와 표준 라이브러리만 쓴다.

실행(저장소 루트에서): backend/.venv/bin/python frontend/scripts/crop-brand.py
배정 원본: tickets/frontend/FE-06.md §3.1(사용자 배정 2026-11-07). 원본 시트와 images/는 읽기만 한다.

하는 일
1. 시트 가장자리에서 이어진 "거의 흰" 영역(배경과 발밑 그림자)을 배경으로 본다. 외곽선 안쪽의 흰색·크림색은 이어져 있지 않아 남는다.
2. 로고의 글자 안쪽 구멍(a·P 등)은 가장자리와 이어져 있지 않으므로 글자 구역에 한해 따로 배경으로 돌린다.
3. 배경과 맞닿은 테두리 2px은 안쪽 색을 기준으로 알파를 계산하고 색을 안쪽 색으로 바꾼다(흰 테두리 할로 방지).
4. 그림마다 연결 성분의 외접 사각형 + 여백으로 잘라 public/brand/에 저장하고, 로고 심볼로 favicon·앱 아이콘을 만든다.
5. 부품이 쓸 크기 표를 src/components/brand/assets.generated.ts로 쓴다.
6. 다크 모드용 워드마크 logo-dark.png: 같은 로고에서 갈색 글자만 흰색(#FFFFFF)으로 바꾼다(FE-12-06 A). 말풍선 테두리·파랑 획·밑줄은 그대로다.
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SHEET = ROOT / "images" / "logo_can_i_ppiyak.png"
FRONTEND = ROOT / "frontend"
OUT_DIR = FRONTEND / "public" / "brand"
APP_DIR = FRONTEND / "src" / "app"
TABLE = FRONTEND / "src" / "components" / "brand" / "assets.generated.ts"

SHEET_SIZE = (1536, 1024)
WHITE = 254  # 시트 배경 값
NEAR_WHITE_MIN = 222  # 그림자(약 229~241) 포함
NEAR_WHITE_SPREAD = 16  # 채널 차이가 이보다 크면 색이 있는 것으로 본다(연한 파랑 밑줄 등)
BAND = 2  # 배경과 맞닿은 테두리 두께(px)
PAD = 6  # 자른 그림 둘레 여백(px)
MAX_SIDE = 512  # 긴 변 상한. 원본보다 키우지 않는다
MIN_COMPONENT = 12  # 이보다 작은 점은 잡음으로 버린다
MAX_BYTES = 150 * 1024

# 눈대중 위치(FE-06 §3.1). 이 상자와 겹치는 연결 성분을 모아 외접 사각형을 다시 구한다.
ASSETS: dict[str, tuple[int, int, int, int]] = {
    "mascot-question": (110, 80, 520, 505),
    "mascot-search": (575, 110, 945, 505),
    "icon-pill": (1040, 175, 1450, 460),
    "icon-pill-square": (50, 580, 380, 895),
    "face": (405, 595, 715, 890),
    "face-square": (735, 580, 1050, 895),
    "logo": (1060, 595, 1510, 870),
}
SYMBOL_BOX = (1066, 631, 1232, 748)  # 로고 안의 캡슐 말풍선 심볼(글자·밑줄 제외). 실행 때 성분 하나가 통째로 드는지 확인한다

# 아이콘: (경로, 한 변, 배경, 심볼이 차지하는 비율)
ICONS = [
    (APP_DIR / "icon.png", 32, None, 0.96),  # favicon: 투명 배경, 최대한 크게
    (APP_DIR / "apple-icon.png", 180, (255, 255, 255), 0.74),  # iOS는 투명을 검게 칠하므로 흰 배경
    (OUT_DIR / "icon-192.png", 192, (255, 255, 255), 0.74),
    (OUT_DIR / "icon-512.png", 512, (255, 255, 255), 0.74),
]


def near_white(p: tuple[int, int, int]) -> bool:
    lo = min(p)
    return lo >= NEAR_WHITE_MIN and max(p) - lo <= NEAR_WHITE_SPREAD


def flood(width: int, height: int, seeds: list[int], passable: bytearray, eight: bool = False) -> bytearray:
    """seeds에서 passable(1)인 칸으로 이어진 영역(1)을 돌려준다."""
    seen = bytearray(width * height)
    queue = deque()
    for s in seeds:
        if passable[s] and not seen[s]:
            seen[s] = 1
            queue.append(s)
    while queue:
        i = queue.popleft()
        x, y = i % width, i // width
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if (dx or dy) and (eight or not (dx and dy)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        j = ny * width + nx
                        if passable[j] and not seen[j]:
                            seen[j] = 1
                            queue.append(j)
    return seen


def components(width: int, height: int, mask: bytearray, eight: bool) -> list[dict]:
    """mask(1)의 연결 성분 목록. 각 성분은 칸 목록과 외접 사각형을 갖는다."""
    seen = bytearray(width * height)
    out = []
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        cells = []
        x0 = y0 = 10**9
        x1 = y1 = -1
        while queue:
            i = queue.popleft()
            cells.append(i)
            x, y = i % width, i // width
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (dx or dy) and (eight or not (dx and dy)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            j = ny * width + nx
                            if mask[j] and not seen[j]:
                                seen[j] = 1
                                queue.append(j)
        out.append({"cells": cells, "box": (x0, y0, x1, y1)})
    return out


def inside(box: tuple[int, int, int, int], area: tuple[int, int, int, int]) -> bool:
    return box[0] >= area[0] and box[1] >= area[1] and box[2] <= area[2] and box[3] <= area[3]


def build_rgba(sheet: Image.Image) -> tuple[Image.Image, bytearray]:
    """배경을 투명하게 만든 시트 전체(RGBA)와 배경 표를 돌려준다."""
    width, height = sheet.size
    px = list(sheet.get_flattened_data() if hasattr(sheet, "get_flattened_data") else sheet.getdata())
    white = bytearray(1 if near_white(p) else 0 for p in px)

    border = [x for x in range(width)] + [(height - 1) * width + x for x in range(width)]
    border += [y * width for y in range(height)] + [y * width + width - 1 for y in range(height)]
    bg = flood(width, height, border, white)

    # 로고 글자 안쪽 구멍: 가장자리와 이어지지 않은 흰 영역 중 로고 상자 안이면서 심볼 밖인 것만 배경으로 돌린다
    enclosed = bytearray(1 if white[i] and not bg[i] else 0 for i in range(width * height))
    holes = 0
    for comp in components(width, height, enclosed, eight=False):
        if inside(comp["box"], ASSETS["logo"]) and not inside(comp["box"], SYMBOL_BOX):
            holes += 1
            for i in comp["cells"]:
                bg[i] = 1
    print(f"로고 글자 구멍 {holes}개를 투명 처리")

    # 배경까지의 거리(체비쇼프, BAND+1까지만)
    dist = bytearray(BAND + 2 if not b else 0 for b in bg)
    frontier = [i for i in range(width * height) if bg[i]]
    for d in range(1, BAND + 2):
        nxt = []
        for i in frontier:
            x, y = i % width, i // width
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height:
                        j = ny * width + nx
                        if not bg[j] and dist[j] > d:
                            dist[j] = d
                            nxt.append(j)
        frontier = nxt

    out = bytearray(width * height * 4)
    reach = BAND + 2
    for i, p in enumerate(px):
        o = i * 4
        if bg[i]:
            continue  # 투명(0,0,0,0)
        if dist[i] > BAND:
            out[o : o + 4] = bytes((p[0], p[1], p[2], 255))
            continue
        # 테두리: 가장 가까운 안쪽 칸의 색을 본래 색으로 보고 알파를 계산한다
        x, y = i % width, i // width
        best = None
        best_d = 10**9
        darkest = p
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    j = ny * width + nx
                    if bg[j]:
                        continue
                    q = px[j]
                    if sum(q) < sum(darkest):
                        darkest = q
                    if dist[j] > BAND:
                        dd = dx * dx + dy * dy
                        if dd < best_d:
                            best_d, best = dd, q
        fore = best or darkest  # 가는 획은 안쪽 칸이 없다 → 주변에서 가장 진한 색
        gap = [WHITE - c for c in fore]
        ch = max(range(3), key=lambda k: gap[k])
        alpha = 1.0 if gap[ch] <= 0 else max(0.0, min(1.0, (WHITE - p[ch]) / gap[ch]))
        out[o : o + 4] = bytes((fore[0], fore[1], fore[2], round(alpha * 255)))
    return Image.frombytes("RGBA", (width, height), bytes(out)), bg


def is_brown(p: tuple[int, int, int, int]) -> bool:
    """로고의 갈색 획(글자·말풍선 테두리). 파랑(b>r)과 흰·크림은 아니다. 알파가 있는 칸만 본다"""
    r, g, b, a = p
    return a >= 40 and r >= g >= b and r - b >= 12 and r + g + b <= 330


def dark_logo(rgba: Image.Image, logo_comps: list[dict]) -> Image.Image:
    """다크 모드용 워드마크(FE-12-06 A): 로고의 갈색 글자만 흰색(#FFFFFF)으로 바꾼다.
    말풍선 심볼 테두리(갈색)·파랑 획·밑줄은 그대로 둔다. 말풍선 테두리는 글자와 이어진 성분이 아니어서 가장 왼쪽 성분으로 가려낸다."""
    width, height = rgba.size
    px = rgba.load()
    mask = bytearray(width * height)
    for comp in logo_comps:
        for i in comp["cells"]:
            if is_brown(px[i % width, i // width]):
                mask[i] = 1
    brown = [c for c in components(width, height, mask, eight=True) if len(c["cells"]) >= MIN_COMPONENT]
    capsule = min(brown, key=lambda c: c["box"][0])  # 말풍선 테두리는 왼쪽 끝에서 시작한다
    out = rgba.copy()
    opx = out.load()
    changed = 0
    for comp in brown:
        if comp is capsule:
            continue
        for i in comp["cells"]:
            x, y = i % width, i // width
            opx[x, y] = (255, 255, 255, opx[x, y][3])
        changed += 1
    print(f"다크 워드마크: 갈색 글자 성분 {changed}개를 흰색으로(말풍선 테두리 1개 유지)")
    return out


def crop_union(rgba: Image.Image, comps: list[dict]) -> Image.Image:
    """성분들의 외접 사각형 + 여백으로 자르고, 고른 성분 밖의 칸(잡음·이웃 그림)은 지운다."""
    width, height = rgba.size
    x0 = min(c["box"][0] for c in comps)
    y0 = min(c["box"][1] for c in comps)
    x1 = max(c["box"][2] for c in comps)
    y1 = max(c["box"][3] for c in comps)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    keep = bytearray(w * h)
    for comp in comps:
        for i in comp["cells"]:
            keep[(i // width - y0) * w + (i % width - x0)] = 255
    part = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    part.paste(rgba.crop((x0, y0, x1 + 1, y1 + 1)), (0, 0), Image.frombytes("L", (w, h), bytes(keep)))
    canvas = Image.new("RGBA", (w + PAD * 2, h + PAD * 2), (0, 0, 0, 0))
    canvas.paste(part, (PAD, PAD))
    if max(canvas.size) > MAX_SIDE:
        scale = MAX_SIDE / max(canvas.size)
        canvas = resize(canvas, (round(canvas.width * scale), round(canvas.height * scale)))
    return canvas


def resize(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """알파를 미리 곱한 채로 줄이거나 키운다(테두리에 배경색이 번지지 않게)."""
    return img.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")


def make_icon(symbol: Image.Image, side: int, background: tuple[int, int, int] | None, fill: float) -> Image.Image:
    box = symbol.getbbox()
    art = symbol.crop(box) if box else symbol
    scale = side * fill / max(art.size)
    art = resize(art, (max(1, round(art.width * scale)), max(1, round(art.height * scale))))
    canvas = Image.new("RGBA", (side, side), (*background, 255) if background else (0, 0, 0, 0))
    canvas.alpha_composite(art, ((side - art.width) // 2, (side - art.height) // 2))
    return canvas


def save(img: Image.Image, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=True)
    return path.stat().st_size


def main() -> int:
    sheet = Image.open(SHEET).convert("RGB")
    if sheet.size != SHEET_SIZE:
        print(f"시트 크기가 다르다: {sheet.size} (기대 {SHEET_SIZE}). 위치 표를 다시 맞춰야 한다")
        return 1
    width, height = sheet.size
    rgba, bg = build_rgba(sheet)

    fg = bytearray(0 if b else 1 for b in bg)
    every = components(width, height, fg, eight=True)
    comps = [c for c in every if len(c["cells"]) >= MIN_COMPONENT]
    print(f"그림 성분 {len(comps)}개, 버린 잡음 {len(every) - len(comps)}개")
    used: set[int] = set()
    results: dict[str, Image.Image] = {}
    for name, area in ASSETS.items():
        mine = [(k, c) for k, c in enumerate(comps) if inside(c["box"], area)]
        if not mine:
            print(f"{name}: 상자 안에 그림이 없다")
            return 1
        used.update(k for k, _ in mine)
        results[name] = crop_union(rgba, [c for _, c in mine])
        if name == "logo":
            # 다크 모드용 워드마크(FE-12-06 A): 같은 그림에서 글자만 흰색으로 바꾼다
            results["logo-dark"] = crop_union(dark_logo(rgba, [c for _, c in mine]), [c for _, c in mine])
            symbol = [c for _, c in mine if inside(c["box"], SYMBOL_BOX)]
            if len(symbol) != 1:
                print(f"로고에서 심볼을 하나로 집지 못했다(SYMBOL_BOX 확인): {len(symbol)}개")
                return 1
            results["symbol"] = crop_union(rgba, symbol)
    leftover = [c["box"] for k, c in enumerate(comps) if k not in used]
    if leftover:
        print(f"어느 그림에도 들지 않은 성분 {len(leftover)}개: {leftover[:8]}")
        return 1

    rows = []
    failed = False
    for name, img in results.items():
        path = OUT_DIR / f"{name}.png"
        size = save(img, path)
        rows.append((name, f"/brand/{name}.png", img.width, img.height))
        over = "  ← 150KB 초과" if size > MAX_BYTES else ""
        failed |= size > MAX_BYTES
        print(f"{path.relative_to(ROOT)}  {img.width}x{img.height}  {size:,} B{over}")
    for path, side, background, fill in ICONS:
        size = save(make_icon(results["symbol"], side, background, fill), path)
        print(f"{path.relative_to(ROOT)}  {side}x{side}  {size:,} B")

    lines = [
        "// 생성 파일이다. 손으로 고치지 않는다.",
        "// 원본: images/logo_can_i_ppiyak.png (배정: tickets/frontend/FE-06.md §3.1)",
        "// 다시 만들기(저장소 루트): backend/.venv/bin/python frontend/scripts/crop-brand.py",
        "export const BRAND_ASSETS = {",
    ]
    lines += [f'  "{name}": {{ src: "{src}", width: {w}, height: {h} }},' for name, src, w, h in rows]
    lines += ["} as const;", "", "export type BrandAssetName = keyof typeof BRAND_ASSETS;", ""]
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text("\n".join(lines), encoding="utf-8")
    print(f"{TABLE.relative_to(ROOT)} 갱신")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
