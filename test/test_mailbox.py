"""Tests for MailBox class and mailbox_* tools.

Covers:
    * Group management (create, add/remove member, group_info)
    * Posting (chat, auto-create group, mentions, ask, auto-add)
    * Thread reading (empty, summary, full, mark_read)
    * Unread tracking (new member, after post, after mark_read)
    * Check (no groups, unread available)
    * Bridging (human gets inbox entry, agent does not)
    * Tool layer (mailbox_post, mailbox_read, mailbox_check)
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import MailBox, MailBoxPostTool, MailBoxReadTool, MailBoxCheckTool


class TestMailBox(unittest.TestCase):
    """Tests for the MailBox class itself."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mbox = MailBox(base=self.tmpdir, self_handle="@test-agent")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── group management ────────────────────────────────────────────────

    def test_create_group(self):
        r = self.mbox.create_group("task-1", subject="Test task")
        self.assertEqual(r["group_id"], "task-1")
        self.assertEqual(r["subject"], "Test task")
        self.assertEqual(len(r["members"]), 1)
        self.assertEqual(r["members"][0]["handle"], "@test-agent")
        self.assertEqual(r["members"][0]["role"], "owner")

    def test_create_group_twice_no_duplicate(self):
        self.mbox.create_group("g1")
        r = self.mbox.create_group("g1", subject="updated")
        self.assertEqual(r["subject"], "updated")
        self.assertEqual(len(r["members"]), 1)

    def test_add_member(self):
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@human-pm", kind="human", role="reviewer")
        r = self.mbox._load_roster("g1")
        self.assertEqual(len(r["members"]), 2)
        m = r["members"][1]
        self.assertEqual(m["handle"], "@human-pm")
        self.assertEqual(m["kind"], "human")
        self.assertEqual(m["role"], "reviewer")

    def test_add_member_replace(self):
        """Adding same handle replaces existing entry."""
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@test-agent", kind="agent", role="member")
        r = self.mbox._load_roster("g1")
        self.assertEqual(len(r["members"]), 1)
        self.assertEqual(r["members"][0]["role"], "member")

    def test_remove_member(self):
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@human")
        self.mbox.remove_member("g1", "@human")
        r = self.mbox._load_roster("g1")
        self.assertEqual(len(r["members"]), 1)

    def test_group_info(self):
        self.mbox.create_group("g1", subject="Test")
        self.mbox.add_member("g1", "@human-pm", kind="human")
        info = self.mbox.group_info("g1")
        self.assertEqual(info["group_id"], "g1")
        self.assertEqual(info["subject"], "Test")
        self.assertEqual(len(info["members"]), 2)

    # ── posting ─────────────────────────────────────────────────────────

    def test_post_chat(self):
        self.mbox.create_group("g1")
        msg = self.mbox.post("g1", "hello", "world")
        self.assertEqual(msg["subject"], "hello")
        self.assertEqual(msg["body"], "world")
        self.assertEqual(msg["from"], "@test-agent")
        self.assertEqual(msg["type"], "chat")
        self.assertEqual(msg["priority"], "normal")

    def test_post_auto_creates_group(self):
        msg = self.mbox.post("new-group", "first post", "body content")
        self.assertEqual(msg["gid"], "new-group")
        r = self.mbox._load_roster("new-group")
        self.assertEqual(r["subject"], "first post")

    def test_post_with_mentions(self):
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@human", kind="human")
        msg = self.mbox.post("g1", "hello", "world", mentions=["@human"])
        self.assertIn("@human", msg["mentions"])

    def test_post_ask_sets_urgent_request(self):
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@human-pm", kind="human")
        msg = self.mbox.post("g1", "question", "need answer", ask="@human-pm")
        self.assertEqual(msg["priority"], "urgent")
        self.assertEqual(msg["type"], "request")
        self.assertIn("@human-pm", msg["mentions"])

    def test_post_auto_adds_unknown_mention(self):
        self.mbox.create_group("g1")
        msg = self.mbox.post("g1", "hi", "body", mentions=["@stranger"])
        r = self.mbox._load_roster("g1")
        handles = [m["handle"] for m in r["members"]]
        self.assertIn("@stranger", handles)

    # ── thread / read ───────────────────────────────────────────────────

    def test_read_empty(self):
        self.mbox.create_group("g1")
        self.assertEqual(self.mbox.read("g1"), [])

    def test_read_summary_last_10(self):
        self.mbox.create_group("g1")
        for i in range(15):
            self.mbox.post("g1", f"msg {i}", str(i))
        msgs = self.mbox.read("g1", depth="summary")
        self.assertEqual(len(msgs), 10)
        self.assertEqual(msgs[0]["subject"], "msg 5")

    def test_read_full(self):
        self.mbox.create_group("g1")
        for i in range(15):
            self.mbox.post("g1", f"msg {i}", str(i))
        msgs = self.mbox.read("g1", depth="full")
        self.assertEqual(len(msgs), 15)

    def test_read_mark_read(self):
        self.mbox.create_group("g1")
        self.mbox.post("g1", "test", "body")
        self.mbox.read("g1", mark_read=True, for_handle="@test-agent")
        self.assertEqual(self.mbox.unread_for("g1", "@test-agent"), 0)

    # ── unread ──────────────────────────────────────────────────────────

    def test_unread_new_member_all_unread(self):
        """New member with last_read_id=None sees all existing as unread."""
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@newbie", kind="agent")
        self.assertEqual(self.mbox.unread_for("g1", "@newbie"), 0)

    def test_unread_after_post(self):
        self.mbox.create_group("g1")
        self.mbox.post("g1", "m1", "")
        self.mbox.post("g1", "m2", "")
        self.assertEqual(self.mbox.unread_for("g1", "@test-agent"), 2)

    def test_unread_after_mark_read_then_post(self):
        self.mbox.create_group("g1")
        self.mbox.post("g1", "old", "")
        self.mbox.mark_read("g1", "@test-agent")
        self.mbox.post("g1", "new", "")
        self.assertEqual(self.mbox.unread_for("g1", "@test-agent"), 1)

    def test_unread_unknown_handle(self):
        self.mbox.create_group("g1")
        self.assertEqual(self.mbox.unread_for("g1", "@nobody"), 0)

    # ── check ───────────────────────────────────────────────────────────

    def test_check_no_groups(self):
        r = self.mbox.check("@test-agent")
        self.assertFalse(r["attention"])
        self.assertEqual(r["groups"], [])

    def test_check_has_unread(self):
        self.mbox.create_group("g1", subject="check test")
        self.mbox.add_member("g1", "@checker", kind="agent")
        self.mbox.post("g1", "new", "")
        # checker joined after post, last_read_id=None → unread=1
        r = self.mbox.check("@checker")
        self.assertTrue(r["attention"])
        self.assertEqual(len(r["groups"]), 1)
        self.assertEqual(r["groups"][0]["gid"], "g1")

    def test_check_default_handle(self):
        """check() uses self_handle when no handle given."""
        self.mbox.create_group("g1")
        self.mbox.post("g1", "update", "")
        r = self.mbox.check()
        self.assertTrue(r["attention"])

    # ── bridging ────────────────────────────────────────────────────────

    def test_bridge_to_human(self):
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@human-pm", kind="human")
        self.mbox.post("g1", "attention", "please review", mentions=["@human-pm"])
        inbox_path = os.path.join(self.tmpdir, "inbox", "human-pm.jsonl")
        self.assertTrue(os.path.exists(inbox_path))
        with open(inbox_path) as f:
            entry = json.loads(f.readline())
        self.assertIn("attention", entry["subject"])
        self.assertEqual(entry["from"], "@group/g1")

    def test_no_bridge_to_agent(self):
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@agent-x", kind="agent")
        self.mbox.post("g1", "hello", "world", mentions=["@agent-x"])
        inbox_path = os.path.join(self.tmpdir, "inbox", "agent-x.jsonl")
        self.assertFalse(os.path.exists(inbox_path))

    def test_bridge_appends_inbox(self):
        """Multiple bridges to same human append to same inbox file."""
        self.mbox.create_group("g1")
        self.mbox.add_member("g1", "@human", kind="human")
        self.mbox.post("g1", "msg1", "", mentions=["@human"])
        self.mbox.post("g1", "msg2", "", mentions=["@human"])
        inbox_path = os.path.join(self.tmpdir, "inbox", "human.jsonl")
        with open(inbox_path) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)

    # ── kind guessing ───────────────────────────────────────────────────

    def test_guess_kind_human(self):
        for name in ("lead", "human", "pm", "user", "reviewer", "boss", "you"):
            self.assertEqual(self.mbox._guess_kind(f"@{name}"), "human")

    def test_guess_kind_agent(self):
        for name in ("agent-a", "worker", "coder", "helper", "bot"):
            self.assertEqual(self.mbox._guess_kind(f"@{name}"), "agent")


class TestMailBoxTools(unittest.TestCase):
    """Tests for the 3 mailbox_* tool classes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mbox = MailBox(base=self.tmpdir, self_handle="@test-agent")
        self.patcher = mock.patch("mangopi_cli.mailbox", self.mbox)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── mailbox_post ────────────────────────────────────────────────────

    def test_post_basic(self):
        r = MailBoxPostTool().run({"gid": "g1", "subject": "hello", "body": "world"})
        self.assertTrue(r["success"])
        msgs = self.mbox.read("g1")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["subject"], "hello")

    def test_post_minimal(self):
        r = MailBoxPostTool().run({"gid": "g1", "subject": "minimal"})
        self.assertTrue(r["success"])
        self.assertEqual(len(self.mbox.read("g1")), 1)

    def test_post_with_to(self):
        r = MailBoxPostTool().run({"gid": "g1", "subject": "hi", "to": "@human"})
        self.assertTrue(r["success"])
        roster = self.mbox._load_roster("g1")
        self.assertIn("@human", [m["handle"] for m in roster["members"]])

    def test_post_with_priority(self):
        r = MailBoxPostTool().run({"gid": "g1", "subject": "urgent", "priority": "urgent"})
        self.assertTrue(r["success"])
        self.assertEqual(self.mbox.read("g1")[0]["priority"], "urgent")

    def test_post_preview(self):
        p = MailBoxPostTool().preview({"gid": "my-task", "subject": "hello"})
        self.assertIn("my-task", p)

    # ── mailbox_read ────────────────────────────────────────────────────

    def test_read_empty(self):
        self.mbox.create_group("empty-g")
        r = MailBoxReadTool().run({"gid": "empty-g"})
        self.assertTrue(r["success"])
        self.assertIn("(no messages)", r["content"])

    def test_read_with_messages(self):
        self.mbox.create_group("g1")
        self.mbox.post("g1", "msg1", "body1")
        self.mbox.post("g1", "msg2", "body2")
        r = MailBoxReadTool().run({"gid": "g1"})
        self.assertTrue(r["success"])
        self.assertIn("msg1", r["content"])
        self.assertIn("msg2", r["content"])
        self.assertIn("Members:", r["content"])

    def test_read_mark_read(self):
        self.mbox.create_group("g1")
        self.mbox.post("g1", "test", "body")
        MailBoxReadTool().run({"gid": "g1", "mark_read": True})
        self.assertEqual(self.mbox.unread_for("g1", "@test-agent"), 0)

    def test_read_full(self):
        self.mbox.create_group("g1")
        for i in range(15):
            self.mbox.post("g1", f"msg {i}", "")
        r = MailBoxReadTool().run({"gid": "g1", "depth": "full"})
        self.assertTrue(r["success"])
        self.assertIn("msg 0", r["content"])
        self.assertIn("msg 14", r["content"])

    def test_read_preview(self):
        p = MailBoxReadTool().preview({"gid": "my-group"})
        self.assertEqual(p, "my-group")

    # ── mailbox_check ───────────────────────────────────────────────────

    def test_check_no_updates(self):
        r = MailBoxCheckTool().run({})
        self.assertTrue(r["success"])
        self.assertIn("no unread", r["content"])

    def test_check_has_updates(self):
        self.mbox.create_group("g1", subject="check test")
        self.mbox.add_member("g1", "@test-agent", kind="agent")
        self.mbox.post("g1", "update", "")
        r = MailBoxCheckTool().run({})
        self.assertTrue(r["success"])
        self.assertIn("g1", r["content"])


if __name__ == "__main__":
    unittest.main()
