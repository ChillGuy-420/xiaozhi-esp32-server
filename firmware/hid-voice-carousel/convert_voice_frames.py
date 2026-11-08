#!/usr/bin/env python3
"""Letterbox the five voice-mode PNGs into 480x480 RGB565 frames.

Does not read or write wallpaper.rgb565. Pixel art uses nearest-neighbor.
The other four use a single Lanczos resample. Output stays outside git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

CANVAS = 480
FRAMES = [
    ("voice-mode.png", "voice-mode.rgb565", Image.Resampling.NEAREST),
    ("voice-mode-2.png", "voice-mode-2.rgb565", Image.Resampling.LANCZOS),
    ("voice-mode-3.png", "voice-mode-3.rgb565", Image.Resampling.LANCZOS),
    ("voice-mode-4.png", "voice-mode-4.rgb565", Image.Resampling.LANCZOS),
    ("voice-mode-5.png", "voice-mode-5.rgb565", Image.Resampling.LANCZOS),
]


def rgb565_bytes(image: Image.Image) -> bytes:
    raw = image.convert("RGB").tobytes()
    out = bytearray(CANVAS * CANVAS * 2)
    for index in range(CANVAS * CANVAS):
        red, green, blue = raw[index * 3 : index * 3 + 3]
        pixel = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        out[index * 2] = pixel & 0xFF
        out[index * 2 + 1] = pixel >> 8
    return bytes(out)


def fit(source: Image.Image, resample: Image.Resampling) -> tuple[Image.Image, dict]:
    image = Image.new("RGB", source.size, (0, 0, 0))
    image.paste(source.convert("RGBA"), mask=source.convert("RGBA").getchannel("A"))
    width, height = image.size
    scale = min(CANVAS / width, CANVAS / height)
    fitted_w = max(1, int(round(width * scale)))
    fitted_h = max(1, int(round(height * scale)))
    if fitted_w > CANVAS or fitted_h > CANVAS:
        raise SystemExit(f"fitted size {fitted_w}x{fitted_h} exceeds the panel")
    resized = image.resize((fitted_w, fitted_h), resample)
    canvas = Image.new("RGB", (CANVAS, CANVAS), (0, 0, 0))
    left = (CANVAS - fitted_w) // 2
    top = (CANVAS - fitted_h) // 2
    canvas.paste(resized, (left, top))
    return canvas, {
        "source_px": [width, height],
        "scale": round(scale, 6),
        "fitted_px": [fitted_w, fitted_h],
        "origin": [left, top],
        "resample": resample.name,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = []
    sheet = Image.new("RGB", (CANVAS, CANVAS * len(FRAMES)), (0, 0, 0))
    for row, (png_name, raw_name, resample) in enumerate(FRAMES):
        source_path = args.src / png_name
        source_bytes = source_path.read_bytes()
        fitted, meta = fit(Image.open(source_path), resample)
        raw = rgb565_bytes(fitted)
        if len(raw) != 460800:
            raise SystemExit(f"{raw_name} is {len(raw)} bytes")
        if raw_name == "wallpaper.rgb565":
            raise SystemExit("refusing to write the desktop asset")
        (args.out / raw_name).write_bytes(raw)
        fitted.save(args.out / f"{Path(raw_name).stem}-fit.png")
        sheet.paste(fitted, (0, row * CANVAS))
        width_scale = meta["fitted_px"][0] / meta["source_px"][0]
        height_scale = meta["fitted_px"][1] / meta["source_px"][1]
        if abs(width_scale - height_scale) > 0.02:
            raise SystemExit(f"{png_name} was stretched")
        meta.update({
            "png": png_name,
            "rgb565": raw_name,
            "png_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "rgb565_sha256": hashlib.sha256(raw).hexdigest(),
            "desktop_asset": False,
        })
        report.append(meta)
    sheet.save(args.out / "contact-sheet.png")
    (args.out / "fit-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps([{"png": item["png"], "source_px": item["source_px"], "fitted_px": item["fitted_px"], "resample": item["resample"]} for item in report]))


if __name__ == "__main__":
    main()
