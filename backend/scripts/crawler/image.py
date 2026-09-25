"""图片下载与压缩：WebP 小图输出（控制体积，供前端图形化）"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger("crawler.image")

# 图片类型 → 输出规格（长边像素 / WebP 质量）
IMAGE_SPECS = {
    "character": {"max_side": 512, "quality": 82},
    "weapon": {"max_side": 512, "quality": 82},
    "artifact": {"max_side": 256, "quality": 80},
    "food": {"max_side": 256, "quality": 80},
    "material": {"max_side": 256, "quality": 80},
    "default": {"max_side": 512, "quality": 82},
}


def compress_image(src_bytes: bytes, dest: Path, max_side: int, quality: int) -> int:
    """压缩并保存为 WebP，返回字节数"""
    from PIL import Image

    import io

    img = Image.open(io.BytesIO(src_bytes))
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    # WebP 支持 RGBA，直接保存
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="WEBP", quality=quality, method=6)
    return dest.stat().st_size


def download_image(url: str, client: httpx.Client) -> bytes:
    """下载图片，带退避重试"""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            r = client.get(url, timeout=60)
            if r.status_code in (429, 567) or r.status_code >= 500:
                last_exc = httpx.HTTPStatusError(
                    f"Server error {r.status_code} for url {r.url}", request=r.request, response=r
                )
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.content
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code in (429, 567) or e.response.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except httpx.TransportError as e:
            last_exc = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"图片下载多次失败: {url}") from last_exc


def save_game_image(
    client: httpx.Client,
    url: str,
    game_dir: Path,
    entry_type: str,
    entry_name: str,
) -> dict:
    """下载并压缩单张图片。返回 {path, size_bytes, status}"""
    spec = IMAGE_SPECS.get(entry_type, IMAGE_SPECS["default"])
    dest = game_dir / "images" / entry_type / f"{entry_name}.webp"
    try:
        raw = download_image(url, client)
        size = compress_image(raw, dest, spec["max_side"], spec["quality"])
        rel = str(dest.relative_to(game_dir)).replace("\\", "/")
        return {"path": rel, "size_bytes": size, "status": "ok"}
    except Exception as e:  # noqa: BLE001
        logger.warning("图片下载失败 %s %s: %s", entry_type, entry_name, e)
        return {"path": "", "size_bytes": 0, "status": f"error: {e}"}
