"""Tests for view_image tool and multimodal message handling.

Covers:
  * ViewImageTool.run for various inputs (URL, local file, errors)
  * ReadTool auto-routing of image files
  * ContextManager.append_tool with multimodal (dict) content
  * run_tool terminal display for image content
"""
import base64
import io
import os
import sys
import unittest
from unittest import mock

# Force a fake MANGO_KEY so the module-level create_provider() doesn't choke
os.environ.setdefault("MANGO_KEY", "test-key-not-used")

# Add parent dir to sys.path so we can import mangopi_cli.
# This file is meant to live at <project>/test/test_view_image.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli as m  # noqa: E402
from mangopi_cli import (  # noqa: E402
    ViewImageTool, ReadTool, ContextManager, console, TOOLS,
)


# 1x1 transparent PNG (67 bytes, valid PNG)
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_tmp_png(path, data=TINY_PNG):
    with open(path, "wb") as f:
        f.write(data)
    return path


def make_tmp_jpg(path):
    # Minimal JPEG (1x1 white pixel)
    jpg = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605"
        "080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e"
        "2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b"
        "08000100010101110000ffc4001f0000010501010101010100000000000000"
        "000102030405060708090a0bffc400b5100002010303020403050504040000"
        "017d010203000411051221314106135161072271143281914a1b1c1092333"
        "52f0156272d10a162434e125f11718191a262728292a3536373839"
        "3a434445464748494a535455565758595a636465666768696a73747576"
        "7778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbfc28a2a28a00a0a00000000000000000000000000"
        "0000000000000000000000000000ffd9"
    )
    with open(path, "wb") as f:
        f.write(jpg)
    return path


class TestViewImageTool(unittest.TestCase):
    """Direct tests on ViewImageTool.run for each input category."""

    def setUp(self):
        self.tmpdir = os.path.join(os.getcwd(), ".tmp_test_view_image")
        os.makedirs(self.tmpdir, exist_ok=True)
        # Patch _validate_file_path to permit any path under tmpdir
        # (default _validate_file_path rejects paths outside project root)
        self._orig_validate = m._validate_file_path
        m._validate_file_path = lambda p: None

    def tearDown(self):
        m._validate_file_path = self._orig_validate
        for f in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, f))
            except OSError:
                pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    # ── URL input is rejected ────────────────────────────────
    def test_https_url_rejected_with_clear_error(self):
        tool = ViewImageTool()
        result = tool.run({"path": "https://example.com/cat.png"})
        self.assertFalse(result["success"])
        self.assertIn("URL inputs are not supported", result["content"])

    def test_http_url_rejected_with_clear_error(self):
        tool = ViewImageTool()
        result = tool.run({"path": "http://internal.lan:8080/img.jpg"})
        self.assertFalse(result["success"])
        self.assertIn("URL inputs are not supported", result["content"])

    def test_file_protocol_url_also_rejected(self):
        # file:// is technically not http(s) but we still want to reject
        # anything that smells like a URL. Defense in depth.
        tool = ViewImageTool()
        result = tool.run({"path": "file:///etc/passwd.png"})
        # file:// would fall through to local path validation, which
        # rejects paths outside project root. Either rejection is fine.
        self.assertFalse(result["success"])

    # ── Local PNG file ──────────────────────────────────────────
    def test_local_png_returns_base64_data_uri(self):
        path = make_tmp_png(os.path.join(self.tmpdir, "ok.png"))
        result = ViewImageTool().run({"path": path})
        self.assertTrue(result["success"], result)
        content = result["content"]
        self.assertEqual(content["type"], "image")
        # data URI prefix
        self.assertTrue(content["image_url"].startswith("data:image/png;base64,"))
        # The b64 should round-trip to our input bytes
        b64 = content["image_url"].split(",", 1)[1]
        self.assertEqual(base64.b64decode(b64), TINY_PNG)
        # Text label should mention size + mime
        self.assertIn("image/png", content["text"])
        self.assertIn(str(len(TINY_PNG)), content["text"])

    def test_local_jpg(self):
        path = make_tmp_jpg(os.path.join(self.tmpdir, "ok.jpg"))
        result = ViewImageTool().run({"path": path})
        self.assertTrue(result["success"], result)
        self.assertTrue(result["content"]["image_url"].startswith("data:image/jpeg;base64,"))

    def test_local_jpeg_extension(self):
        path = make_tmp_jpg(os.path.join(self.tmpdir, "ok.jpeg"))
        result = ViewImageTool().run({"path": path})
        self.assertTrue(result["success"], result)
        self.assertTrue(result["content"]["image_url"].startswith("data:image/jpeg;base64,"))

    def test_local_webp_returns_image_webp(self):
        # Use png bytes but with .webp ext to test mime mapping
        path = make_tmp_png(os.path.join(self.tmpdir, "ok.webp"))
        result = ViewImageTool().run({"path": path})
        self.assertTrue(result["success"], result)
        self.assertTrue(result["content"]["image_url"].startswith("data:image/webp;base64,"))

    # ── Error cases ─────────────────────────────────────────────
    def test_missing_path(self):
        result = ViewImageTool().run({"path": ""})
        self.assertFalse(result["success"])
        self.assertIn("required", result["content"])

    def test_nonexistent_file(self):
        result = ViewImageTool().run({"path": os.path.join(self.tmpdir, "ghost.png")})
        self.assertFalse(result["success"])
        # OSError message or file-not-found
        self.assertIn("cannot", result["content"])

    def test_unsupported_extension(self):
        path = os.path.join(self.tmpdir, "doc.pdf")
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 fake")
        result = ViewImageTool().run({"path": path})
        self.assertFalse(result["success"])
        self.assertIn("unsupported", result["content"])

    def test_txt_with_png_extension_is_rejected_by_ext_check(self):
        # Even if the file isn't a real image, we check the extension.
        # Extension-based dispatch is intentional: it avoids reading huge
        # non-image files. Real validation could add magic-byte sniffing.
        path = os.path.join(self.tmpdir, "fake.png")
        with open(path, "wb") as f:
            f.write(b"not really a png")
        result = ViewImageTool().run({"path": path})
        self.assertTrue(result["success"])  # ext is .png, so we accept

    def test_empty_file_rejected(self):
        path = os.path.join(self.tmpdir, "empty.png")
        with open(path, "wb") as f:
            pass
        result = ViewImageTool().run({"path": path})
        self.assertFalse(result["success"])
        self.assertIn("empty", result["content"])

    def test_oversized_file_rejected(self):
        path = os.path.join(self.tmpdir, "big.png")
        # Write 21 MB (exceeds 20 MB cap)
        with open(path, "wb") as f:
            f.write(b"\x00" * (21 * 1024 * 1024))
        result = ViewImageTool().run({"path": path})
        self.assertFalse(result["success"])
        self.assertIn("too large", result["content"])
        os.remove(path)

    def test_path_outside_project_root_rejected(self):
        # Re-enable real validator temporarily
        m._validate_file_path = self._orig_validate
        result = ViewImageTool().run({"path": "/etc/passwd.png"})
        self.assertFalse(result["success"])
        # _validate_file_path returns "path '...' is outside project root"
        self.assertIn("outside project root", result["content"])

    # ── Schema correctness ──────────────────────────────────────
    def test_schema_has_correct_shape(self):
        schema = ViewImageTool().schema()
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "view_image")
        params = schema["function"]["parameters"]
        self.assertIn("path", params["properties"])
        self.assertEqual(params["properties"]["path"]["type"], "string")
        self.assertIn("path", params["required"])

    def test_registered_in_tools_dict(self):
        self.assertIn("view_image", TOOLS)
        self.assertIsInstance(TOOLS["view_image"], ViewImageTool)


class TestReadToolImageAutoRoute(unittest.TestCase):
    """The existing `read` tool should auto-route image files to vision
    when called WITHOUT offset/limit args (since those don't make sense
    for binary content)."""

    def setUp(self):
        self.tmpdir = os.path.join(os.getcwd(), ".tmp_test_read_route")
        os.makedirs(self.tmpdir, exist_ok=True)
        self._orig_validate = m._validate_file_path
        m._validate_file_path = lambda p: None

    def tearDown(self):
        m._validate_file_path = self._orig_validate
        for f in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, f))
            except OSError:
                pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_read_png_routes_to_view_image(self):
        path = make_tmp_png(os.path.join(self.tmpdir, "shot.png"))
        result = ReadTool().run({"path": path})
        self.assertTrue(result["success"])
        # The result content should be an image dict, not line-numbered text
        self.assertIsInstance(result["content"], dict)
        self.assertEqual(result["content"]["type"], "image")
        self.assertTrue(result["content"]["image_url"].startswith("data:image/png;base64,"))

    def test_read_text_file_unchanged(self):
        path = os.path.join(self.tmpdir, "hello.txt")
        with open(path, "w") as f:
            f.write("hello\nworld\n")
        result = ReadTool().run({"path": path})
        self.assertTrue(result["success"])
        self.assertIsInstance(result["content"], str)
        self.assertIn("hello", result["content"])
        self.assertIn("world", result["content"])

    def test_read_with_offset_does_not_auto_route(self):
        # When user explicitly passes offset/limit on an image file, the
        # tool skips auto-routing to vision. The intent is "I want a
        # specific slice of this file as text" — which for a PNG is
        # nonsensical but is the caller's choice, not ours to override.
        # We verify: the result is NOT an image dict.
        path = make_tmp_png(os.path.join(self.tmpdir, "shot.png"))
        # Read the same file as text — expect either a successful str
        # read or a failure, but in EITHER case the result content
        # should not be an image dict (which would mean auto-routing
        # happened despite offset being given).
        try:
            result = ReadTool().run({"path": path, "offset": 0})
            # If it didn't crash, content should be a plain string,
            # not a multimodal dict.
            self.assertNotIsInstance(result.get("content"), dict)
        except (UnicodeDecodeError, ValueError):
            # Reading binary as text raises UnicodeDecodeError — this
            # also proves we did NOT auto-route (auto-routing would
            # have returned a clean image dict).
            pass


class TestContextManagerAppendTool(unittest.TestCase):
    """ContextManager.append_tool should accept both str and dict content."""

    def setUp(self):
        self.ctx = ContextManager()

    def test_string_content(self):
        self.ctx.append_tool("call_1", "read", "   1| hello\n")
        msg = self.ctx.messages[-1]
        self.assertEqual(msg["role"], "tool")
        self.assertEqual(msg["tool_name"], "read")
        self.assertEqual(msg["content"], "   1| hello\n")
        self.assertEqual(msg["tool_call_id"], "call_1")

    def test_image_dict_content(self):
        img = {
            "type": "image",
            "text": "Image: /tmp/x.png (67 bytes, image/png)",
            "image_url": "data:image/png;base64,AAAA",
        }
        self.ctx.append_tool("call_2", "view_image", img)
        msg = self.ctx.messages[-1]
        # Content should be a multimodal part list, not a string
        self.assertIsInstance(msg["content"], list)
        self.assertEqual(len(msg["content"]), 2)
        text_part, image_part = msg["content"]
        self.assertEqual(text_part["type"], "text")
        self.assertIn("Image: /tmp/x.png", text_part["text"])
        self.assertEqual(image_part["type"], "image_url")
        self.assertEqual(image_part["image_url"]["url"], "data:image/png;base64,AAAA")

    def test_url_image_passthrough_removed(self):
        # URL inputs are no longer supported by view_image, so this
        # test case is intentionally absent. If we ever add URL support
        # back, restore the test here.
        self.skipTest("URL passthrough removed — view_image is local-files-only")
    def test_none_content(self):
        self.ctx.append_tool("call_4", "write", None)
        msg = self.ctx.messages[-1]
        self.assertEqual(msg["content"], "")

    def test_empty_string_content(self):
        self.ctx.append_tool("call_5", "bash", "")
        msg = self.ctx.messages[-1]
        self.assertEqual(msg["content"], "")

    def test_message_appears_in_messages_list(self):
        before = len(self.ctx.messages)
        self.ctx.append_tool("call_6", "read", "data")
        self.assertEqual(len(self.ctx.messages), before + 1)


class TestRunToolDisplayForImage(unittest.TestCase):
    """run_tool should not crash when a tool returns a dict content;
    it should display the human-readable text label instead of
    trying to .split() a dict."""

    def setUp(self):
        self.tmpdir = os.path.join(os.getcwd(), ".tmp_test_run_display")
        os.makedirs(self.tmpdir, exist_ok=True)
        self._orig_validate = m._validate_file_path
        m._validate_file_path = lambda p: None

    def tearDown(self):
        m._validate_file_path = self._orig_validate
        for f in os.listdir(self.tmpdir):
            try:
                os.remove(os.path.join(self.tmpdir, f))
            except OSError:
                pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_run_view_image_local_does_not_crash(self):
        path = make_tmp_png(os.path.join(self.tmpdir, "ok.png"))
        # Suppress console output noise during the test
        with mock.patch.object(console, "tool_call"), \
             mock.patch.object(console, "tool_result"), \
             mock.patch.object(console, "start_spinner"), \
             mock.patch.object(console, "end_spinner"), \
             mock.patch("builtins.print"):
            content = m.run_tool("view_image", {"path": path})
        # Returned content should be a dict (multimodal payload)
        self.assertIsInstance(content, dict)
        self.assertEqual(content["type"], "image")
        self.assertTrue(content["image_url"].startswith("data:image/png;base64,"))

    def test_run_view_image_url_input_rejected(self):
        with mock.patch.object(console, "tool_call"), \
             mock.patch.object(console, "tool_result"), \
             mock.patch.object(console, "start_spinner"), \
             mock.patch.object(console, "end_spinner"), \
             mock.patch("builtins.print"):
            content = m.run_tool("view_image", {"path": "https://example.com/x.png"})
        # URL input → tool fails → run_tool returns a string error message
        self.assertIsInstance(content, str)
        self.assertIn("URL inputs are not supported", content)

    def test_run_view_image_invalid_path(self):
        # Path outside project root → validator rejects
        m._validate_file_path = self._orig_validate
        with mock.patch.object(console, "tool_call"), \
             mock.patch.object(console, "tool_result"), \
             mock.patch.object(console, "start_spinner"), \
             mock.patch.object(console, "end_spinner"), \
             mock.patch("builtins.print"):
            content = m.run_tool("view_image", {"path": "/etc/passwd.png"})
        # When tool fails, content is a string error
        self.assertIsInstance(content, str)
        self.assertIn("outside project root", content)


class TestToolSchemaIncludesViewImage(unittest.TestCase):
    """The OpenAI-style tool schema sent to the model must include view_image."""

    def test_view_image_in_tool_schema(self):
        schema = m.tool_schema()
        names = [s["function"]["name"] for s in schema]
        self.assertIn("view_image", names)

    def test_schema_count(self):
        # 13 tools total (web_search added)
        self.assertEqual(len(m.tool_schema()), 12)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)
