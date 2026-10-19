"""本地上传文件的路径守卫。

安全背景：`ChatRequest.image_path` / MCP 工具参数都可以直接传入任意字符串，
而视觉工具会把文件内容 base64 编码后发给第三方模型。若不限制目录，
一个被诱导的 `image_path` 就能把本机任意文件（截图之外的东西）外发出去。

约定：只有经过 `POST /api/vision/upload` 落到 `backend/data/uploads/` 下的文件才允许被识别。
"""
from pathlib import Path

# backend/ 目录（本文件 = backend/app/core/paths.py）
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BACKEND_ROOT / "data" / "uploads"


def ensure_upload_path(image_path: str, upload_dir: Path | None = None) -> Path:
    """校验并返回上传目录内的绝对路径；越界或不存在则抛 ValueError。"""
    raw = str(image_path or "").strip()
    if not raw:
        raise ValueError("缺少图片路径")
    base = (upload_dir or UPLOAD_DIR).resolve()
    p = Path(raw)
    candidate = (p if p.is_absolute() else BACKEND_ROOT / p).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise ValueError("只允许识别通过 /api/vision/upload 上传的截图") from None
    if not candidate.is_file():
        raise ValueError(f"截图不存在: {candidate.name}")
    return candidate
