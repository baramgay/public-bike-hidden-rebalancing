"""Sol 그림의 배치용 사본 생성. 원본은 수정하지 않는다.

- 아이콘: 흰 배경을 투명하게(_t: 정사각 여백, _tc: 본체만)
- 흰 배경 개념도(08·09): 미세한 회색 배경(253 안팎)을 순백으로 올려 지면에서 사각 테두리가 보이지 않게 하고 본체 범위로 자름(_w)
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "design" / "sol"
DST = SRC / "derived"


def main() -> None:
    DST.mkdir(exist_ok=True)
    meta = {}
    for f in sorted(glob.glob(str(SRC / "06_icon_*_forest*.png"))):
        if f.endswith("route_forest.png"):          # 수정본(_b)을 쓴다
            continue
        src = Image.open(f)
        if src.mode == "RGBA":                        # 요청서 02부터는 투명 배경으로 납품됨, 잔여 미세 알파(≤16)는 범위에서 제외
            img = src.crop(Image.fromarray(((np.asarray(src)[..., 3] > 16) * 255).astype(np.uint8)).getbbox())
        else:
            a = np.asarray(src.convert("RGB")).astype(float)
            dist = np.sqrt(((255 - a) ** 2).sum(axis=2))  # 흰색과의 거리
            alpha = np.clip((dist - 6) / 24, 0, 1) * 255
            img = Image.fromarray(np.dstack([a, alpha]).astype(np.uint8), "RGBA")
        img = img.crop(img.getbbox())
        pad = int(max(img.size) * 0.02)               # 본체 크기에 맞춰 넣을 때 쓰는 꽉 찬 사본(_tc)
        tight = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
        tight.paste(img, (pad, pad), img)
        tight.save(DST / os.path.basename(f).replace("_forest_b", "").replace("_forest", "").replace(".png", "_tc.png"))
        side = int(max(img.size) * 1.12)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
        name = os.path.basename(f).replace("_forest_b", "").replace("_forest", "").replace(".png", "_t.png")
        canvas.save(DST / name)
        meta[name] = {"source": Path(f).relative_to(ROOT).as_posix(),
                      "source_sha256": hashlib.sha256(Path(f).read_bytes()).hexdigest(), "size": list(canvas.size)}
    (DST / "README.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(list(meta))
    for name in ("08_data_layers_forest", "09_korea_network_forest"):
        rgb = np.asarray(Image.open(SRC / f"{name}.png").convert("RGB")).astype(float)
        w = np.clip((rgb.min(axis=2) - 232) / 18, 0, 1)[..., None]     # 가장 어두운 채널 232 이상(밝은 무채색)부터 점차 흰색으로
        out = Image.fromarray((rgb * (1 - w) + 255 * w).round().astype(np.uint8))
        x0, y0, x1, y1 = Image.fromarray(((255 - np.asarray(out).min(axis=2)) > 6).astype(np.uint8) * 255).getbbox()   # 그림 본체 범위
        pad = int(max(x1 - x0, y1 - y0) * 0.02)
        out.crop((max(0, x0 - pad), max(0, y0 - pad), min(out.width, x1 + pad), min(out.height, y1 + pad))).save(DST / f"{name}_w.png")


if __name__ == "__main__":
    main()
