"""Sol 아이콘(순백 배경)의 흰 배경을 투명하게 만든 배치용 사본 생성. 원본은 수정하지 않는다."""
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
        a = np.asarray(Image.open(f).convert("RGB")).astype(float)
        dist = np.sqrt(((255 - a) ** 2).sum(axis=2))  # 흰색과의 거리
        alpha = np.clip((dist - 6) / 24, 0, 1) * 255
        img = Image.fromarray(np.dstack([a, alpha]).astype(np.uint8), "RGBA")
        img = img.crop(img.getbbox())
        side = int(max(img.size) * 1.12)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
        name = os.path.basename(f).replace("_forest_b", "").replace("_forest", "").replace(".png", "_t.png")
        canvas.save(DST / name)
        meta[name] = {"source": Path(f).relative_to(ROOT).as_posix(),
                      "source_sha256": hashlib.sha256(Path(f).read_bytes()).hexdigest(), "size": list(canvas.size)}
    (DST / "README.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(list(meta))


if __name__ == "__main__":
    main()
