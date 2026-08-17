"""Shipped extension — view_image: 本地图片载入视觉上下文.
Shipped extension — view_image: load a local image into the model's vision context.

v0.1.49 从核心移出 (插件化). 按需启用:
  * 复制/软链本文件到 preset 扩展目录: ~/.mangocli/presets/<name>/extensions/ (需设 MANGO_PRESET=<name>)

v0.1.49 起 read 不再自动路由图片, 需要视觉时显式调用本工具.
Since v0.1.49 `read` no longer auto-routes images; call this tool explicitly for vision.

契约: 顶层仅 `from mangopi_cli import ToolBase`; 核心符号 (_validate_file_path) 晚于
扩展扫描点, 在函数体内延迟导入 (导入期半初始化契约).
"""
from mangopi_cli import ToolBase

import base64
import mimetypes
import os

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class ViewImageTool(ToolBase):
    name = "view_image"
    description = (
        "Load a local image (screenshot, UI mockup, error screen, diagram) into the model's vision context. "
        "Accepts an absolute path to a file on disk; URLs are not supported. "
        "Supported formats: png, jpg, jpeg, gif, webp.")
    params = {"path": {"type": "string",
                       "description": "Absolute path to a local image file (png/jpg/jpeg/gif/webp). "
                                      "URL inputs are rejected."}}
    preview_lines = 0
    preview_width = 200
    use_spinner = True
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB hard cap
    guidance = ("Use **view_image** for screenshots, UI mockups, error screens, and diagrams. "
                "Pass an absolute local file path (.png/.jpg/.jpeg/.gif/.webp); URLs are rejected. "
                "The `read` tool reads text only — call `view_image` explicitly for vision.")

    @staticmethod
    def _is_url(s: str) -> bool: return s.startswith("http://") or s.startswith("https://")

    def preview(self, args): return (args.get("path") or "")[:self.preview_width]

    def run(self, args):
        path = (args.get("path") or "").strip()
        if not path:
            return self.fail("view_image error: 'path' is required")
        if self._is_url(path):
            return self.fail("view_image error: URL inputs are not supported. "
                             "Download the image to a local file first, then pass the file path.")
        import mangopi_cli as m  # 延迟导入: _validate_file_path 定义晚于扩展扫描点
        err = m._validate_file_path(path)
        if err:
            return self.fail(f"view_image error: {err}")
        try:
            size = os.path.getsize(path)
        except OSError as e:
            return self.fail(f"view_image error: cannot stat file: {e}")
        if size == 0:
            return self.fail("view_image error: image file is empty")
        if size > self.MAX_BYTES:
            return self.fail(f"view_image error: image too large ({size:,} bytes, max {self.MAX_BYTES})")
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS:
            return self.fail(f"view_image error: unsupported image format '{ext}' (supported: png,jpg,jpeg,gif,webp)")
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except OSError as e:
            return self.fail(f"view_image error: cannot read file: {e}")
        mime, _ = mimetypes.guess_type(path)
        if not mime:
            mime = "image/png"
        data_uri = f"data:{mime};base64,{b64}"
        return self.ok({"type": "image", "text": f"Image: {path} ({size} bytes,{mime})", "image_url": data_uri})


tools = [ViewImageTool()]
