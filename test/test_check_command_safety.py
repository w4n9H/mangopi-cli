"""Tests for _check_command_safety() — covers 7 categories of dangerous
command rules and the safe-command branches.

Categories (matched against mangopi_cli.dangerous_i18n):
    1: rm / unlink
    2: mkfs / fdisk / parted / dd
    3: chmod 7xx7 / chown ... root
    4: sudo rm / su - / su root
    5: kill -9 1 / killall -9 / pkill -9
    6: export PATH / unset PATH / writing into /etc/
    7: history -c / > /dev/null 2>&1
"""
import os
import sys
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_check_command_safety.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import _check_command_safety, _i18n  # noqa: E402


# ── Dangerous category id → i18n key map (mirrors dangerous_i18n in mangopi_cli.py) ──

DANGEROUS_KEYS = {
    1: "safety.danger.rm",
    2: "safety.danger.mkfs",
    3: "safety.danger.chmod",
    4: "safety.danger.sudo",
    5: "safety.danger.kill",
    6: "safety.danger.env",
    7: "safety.danger.history",
}


def _expected_reason(category_id):
    """Resolve the i18n string for a given danger category (1-7)."""
    return _i18n(DANGEROUS_KEYS[category_id])


# ── Shared assertions ────────────────────────────────────────────────────────


class _CommandSafetyBase(unittest.TestCase):
    """Base class: helpers for asserting _check_command_safety() outcomes.

    Subclasses get `assertSafe(cmd)` and `assertDangerous(cmd, category_id)`
    so the per-test bodies stay readable.
    """

    def assertSafe(self, cmd):
        """Command must be classified as safe (is_dangerous=False, reason=None)."""
        is_dangerous, reason = _check_command_safety(cmd)
        self.assertFalse(
            is_dangerous,
            f"expected safe, got dangerous for command: {cmd!r}",
        )
        self.assertIsNone(
            reason,
            f"expected reason=None, got reason={reason!r} for command: {cmd!r}",
        )

    def assertDangerous(self, cmd, category_id):
        """Command must be classified as dangerous in the given category (1-7)."""
        is_dangerous, reason = _check_command_safety(cmd)
        self.assertTrue(
            is_dangerous,
            f"expected dangerous (category {category_id}), got safe for command: {cmd!r}",
        )
        expected_reason = _expected_reason(category_id)
        self.assertEqual(
            reason,
            expected_reason,
            f"expected reason {expected_reason!r} (category {category_id}), "
            f"got reason {reason!r}",
        )


# ── 1. Empty and whitespace-only commands — safe ─────────────────────────────


class TestEmptyAndWhitespace(_CommandSafetyBase):
    """Empty / whitespace-only commands should never trip a danger rule."""

    def test_01_empty_string(self):
        self.assertSafe("")

    def test_02_whitespace_only(self):
        self.assertSafe("   \t  \n  ")


# ── 2. Common safe commands ─────────────────────────────────────────────────


class TestSafeCommonCommands(_CommandSafetyBase):
    """Everyday commands that must remain classified as safe."""

    def test_03_safe_ls(self):
        self.assertSafe("ls -la")

    def test_04_safe_cat(self):
        self.assertSafe("cat /etc/hosts")

    def test_05_safe_echo(self):
        self.assertSafe("echo hello world")

    def test_06_safe_chmod_644(self):
        self.assertSafe("chmod 644 file.txt")

    def test_07_safe_chmod_755(self):
        self.assertSafe("chmod -R 755 dir/")

    def test_08_safe_chown(self):
        self.assertSafe("chown user:user file")

    def test_09_safe_kill_15(self):
        self.assertSafe("kill -15 1234")

    def test_10_safe_kill_9_normal_pid(self):
        self.assertSafe("kill -9 1234")

    def test_11_safe_su_user(self):
        self.assertSafe("su postgres")

    def test_12_safe_export_other(self):
        self.assertSafe("export FOO=bar")

    def test_13_safe_unset_other(self):
        self.assertSafe("unset FOO")

    def test_14_safe_history_no_c(self):
        self.assertSafe("history | grep foo")

    def test_15_safe_write_tmp(self):
        self.assertSafe("echo foo > /tmp/file")


# ── 3. Category 1: rm / unlink ──────────────────────────────────────────────


class TestCategory1Rm(_CommandSafetyBase):
    """Category 1 — rm / unlink patterns."""

    def test_20_rm_rf(self):
        self.assertDangerous("rm -rf /", 1)

    def test_21_rm_fr(self):
        self.assertDangerous("rm -fr foo", 1)

    def test_22_rm_r(self):
        self.assertDangerous("rm -r build/", 1)

    def test_23_rm_f(self):
        self.assertDangerous("rm -f file", 1)

    def test_24_rm_no_flag(self):
        self.assertDangerous("rm foo", 1)

    def test_25_unlink(self):
        self.assertDangerous("unlink /tmp/file", 1)

    def test_26_rm_case_insensitive(self):
        self.assertDangerous("RM -RF /", 1)

    def test_27_rm_strip_whitespace(self):
        self.assertDangerous("   rm -rf /  ", 1)


class TestCategory1RmFalsePositives(_CommandSafetyBase):
    """Words that contain 'rm' as a substring must not trigger the rm rule.

    The regex uses \\b word boundaries, so 'rmdir', bare 'rm', and 'firmware'
    should all be classified as safe.
    """

    def test_28_rmdir_safe(self):
        # rmdir is not rm; \brm\s+ cannot match the start of "rmdir".
        self.assertSafe("rmdir old_dir")

    def test_29_rm_alone_safe(self):
        # Bare 'rm' has no \s+ after it; no rm-pattern can match.
        self.assertSafe("rm")

    def test_30_firmware_word_boundary(self):
        # 'firmware' contains 'rm', but \b cannot match between 'fi' and 'rm'.
        self.assertSafe("firmware_update_tool")


# ── 4. Category 2: mkfs / fdisk / parted / dd ───────────────────────────────


class TestCategory2DiskOps(_CommandSafetyBase):
    """Category 2 — disk-destroying commands."""

    def test_31_mkfs_ext4(self):
        self.assertDangerous("mkfs.ext4 /dev/sda1", 2)

    def test_32_mkfs_bare(self):
        self.assertDangerous("mkfs /dev/sda1", 2)

    def test_33_fdisk(self):
        self.assertDangerous("fdisk -l", 2)

    def test_34_parted(self):
        self.assertDangerous("parted /dev/sda", 2)

    def test_35_dd_if_of(self):
        self.assertDangerous("dd if=/dev/zero of=/dev/sda", 2)

    def test_36_dd_if_of_pipe(self):
        self.assertDangerous("gunzip -c disk.img | dd if=/dev/stdin of=/dev/sda", 2)


# ── 5. Category 3: chmod 7xx7 / chown root ──────────────────────────────────


class TestCategory3ChmodChown(_CommandSafetyBase):
    """Category 3 — chmod 7xx7 (and sticky/sgid variants) and chown ... root."""

    def test_40_chmod_777(self):
        self.assertDangerous("chmod 777 file", 3)

    def test_41_chmod_R_777(self):
        self.assertDangerous("chmod -R 777 /var/www", 3)

    def test_42_chmod_1777(self):
        self.assertDangerous("chmod 1777 /tmp", 3)

    def test_43_chmod_2777(self):
        self.assertDangerous("chmod 2777 dir", 3)

    def test_44_chmod_0777(self):
        self.assertDangerous("chmod 0777 file", 3)

    def test_45_chown_root(self):
        self.assertDangerous("chown user:root file", 3)

    def test_46_chown_R_root(self):
        self.assertDangerous("chown -R root /etc", 3)


class TestCategory3ChmodChownFalsePositives(_CommandSafetyBase):
    """chmod modes that don't end in '7' must NOT trigger the 7xx7 rule."""

    def test_47_chmod_644_safe(self):
        self.assertSafe("chmod 644 file")

    def test_48_chmod_2700_safe(self):
        # 2700 = 2,7,0,0 — the \d*7\d*7 pattern requires a trailing 7, so
        # this should NOT match.
        self.assertSafe("chmod 2700 dir")


# ── 6. Category 4: sudo rm / su - / su root ─────────────────────────────────


class TestCategory4SudoSu(_CommandSafetyBase):
    """Category 4 — sudo + rm, su -, su root.

    Note: 'sudo rm ...' will typically match the rm pattern (category 1)
    first, because that pattern appears earlier in dangerous_patterns
    and we return on the first hit.
    """

    def test_50_sudo_rm_matches_rm_first(self):
        # Matches both rm (cat 1) and sudo (cat 4); first hit in
        # dangerous_patterns wins → category 1.
        self.assertDangerous("sudo rm -rf /var/log", 1)

    def test_51_su_dash_c(self):
        self.assertDangerous("su -c whoami", 4)

    def test_52_su_root(self):
        self.assertDangerous("su root", 4)


class TestCategory4SudoSuFalsePositives(_CommandSafetyBase):
    """sudo/su variants that must NOT trigger."""

    def test_53_su_dash_alone_safe(self):
        # Known limitation: 'su -' alone does not match \bsu\s+- because
        # there's no word boundary between '-' and end-of-string.
        self.assertSafe("su -")

    def test_54_sudo_other_safe(self):
        self.assertSafe("sudo apt update")


# ── 7. Category 5: kill -9 PID 1 / killall -9 / pkill -9 ────────────────────


class TestCategory5Kill9(_CommandSafetyBase):
    """Category 5 — kill -9 on PID 1, killall/pkill -9, negative-PID kill -9."""

    def test_60_kill_9_pid1(self):
        self.assertDangerous("kill -9 1", 5)

    def test_61_kill_9_negative_pid(self):
        self.assertDangerous("kill -9 -1", 5)

    def test_62_kill_9_negative_pid_long(self):
        self.assertDangerous("kill -9 -1234", 5)

    def test_63_killall_9(self):
        self.assertDangerous("killall -9 nginx", 5)

    def test_64_pkill_9(self):
        self.assertDangerous("pkill -9 python", 5)


class TestCategory5Kill9FalsePositives(_CommandSafetyBase):
    """pkill/kill variants that must NOT trigger."""

    def test_65_pkill_f_safe(self):
        # pkill -f without -9 must not match.
        self.assertSafe("pkill -f nginx")


# ── 8. Category 6: export PATH / unset PATH / writing into /etc/ ────────────


class TestCategory6EnvEtcRedirect(_CommandSafetyBase):
    """Category 6 — PATH manipulation and writes under /etc/."""

    def test_70_export_PATH(self):
        self.assertDangerous("export PATH=/usr/local/bin:$PATH", 6)

    def test_71_unset_PATH(self):
        self.assertDangerous("unset PATH", 6)

    def test_72_echo_etc(self):
        self.assertDangerous("echo nameserver 8.8.8.8 > /etc/resolv.conf", 6)

    def test_73_append_etc(self):
        self.assertDangerous("echo foo >> /etc/hosts", 6)

    def test_74_cat_redirect_etc(self):
        self.assertDangerous("cat > /etc/passwd", 6)

    def test_75_export_PATH_case(self):
        self.assertDangerous("EXPORT PATH=/tmp", 6)


class TestCategory6EnvEtcRedirectFalsePositives(_CommandSafetyBase):
    """Reads from /etc/ must not trigger — only writes (redirects) do."""

    def test_76_cat_etc_safe(self):
        self.assertSafe("cat /etc/hosts")


# ── 9. Category 7: history -c / > /dev/null 2>&1 ────────────────────────────


class TestCategory7HistoryDevNull(_CommandSafetyBase):
    """Category 7 — history -c and stdout/stderr discarding redirects."""

    def test_80_history_c(self):
        self.assertDangerous("history -c", 7)

    def test_81_dev_null_redirect(self):
        self.assertDangerous("echo foo > /dev/null 2>&1", 7)

    def test_82_dev_null_redirect_alt(self):
        # '>>?' covers both '>' and '>>'.
        self.assertDangerous("echo foo >> /dev/null 2>&1", 7)


# ── 10. Multi-category / precedence scenarios ───────────────────────────────


class TestCategoryPrecedence(_CommandSafetyBase):
    """When multiple rules could match, the first one in dangerous_patterns
    wins (we return on first hit). These tests pin down that ordering."""

    def test_90_rm_with_sudo_still_category_1(self):
        # rm pattern sits before sudo pattern in dangerous_patterns.
        self.assertDangerous("sudo rm -rf /tmp/x", 1)

    def test_91_sudo_before_rm_still_category_1(self):
        # Even with 'sudo' at the front, the inner 'rm' substring is
        # matched by the rm pattern (cat 1) before sudo (cat 4).
        self.assertDangerous("sudo bash -c 'rm -rf /'", 1)

    def test_92_dd_in_safe_context(self):
        # dd appearing inside an echo string still matches the dd pattern.
        self.assertDangerous("echo dd if=/dev/zero of=/dev/null", 2)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)