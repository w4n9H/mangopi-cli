#!/usr/bin/env python3
"""Test _check_command_safety() —— 覆盖 7 类危险命令规则及安全命令分支。"""

import sys
import os

# 将项目根目录加到 sys.path，以便 import mangopi_cli 中的 _check_command_safety
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangopi_cli import _check_command_safety, _i18n

# ── 危险类别 → i18n key 映射（与 mangopi_cli.py 中的 dangerous_i18n 保持一致）──

DANGEROUS_KEYS = {
    1: "safety.danger.rm",
    2: "safety.danger.mkfs",
    3: "safety.danger.chmod",
    4: "safety.danger.sudo",
    5: "safety.danger.kill",
    6: "safety.danger.env",
    7: "safety.danger.history",
}

# ── 计数器与辅助函数 ─────────────────────────────────────────

passed = 0
failed = 0


def _t(name, cmd, expected_dangerous, expected_id=None):
    """运行一个测试用例。

    expected_dangerous=True 时必须同时提供 expected_id（1-7），
    表示预期命中的危险类别。
    """
    global passed, failed
    is_dangerous, reason = _check_command_safety(cmd)
    try:
        assert bool(is_dangerous) == bool(expected_dangerous), (
            f"expected dangerous={expected_dangerous}, got dangerous={is_dangerous} "
            f"for command: {cmd!r}"
        )
        if expected_dangerous:
            assert expected_id is not None, "expected_id is required when expected_dangerous=True"
            expected_reason = _i18n(DANGEROUS_KEYS[expected_id])
            assert reason == expected_reason, (
                f"expected reason {expected_reason!r} (id={expected_id}), "
                f"got reason {reason!r}"
            )
        else:
            assert reason is None, f"expected reason=None, got reason={reason!r} for command: {cmd!r}"
        passed += 1
        print(f"  ✓ {name}")
    except AssertionError as e:
        failed += 1
        print(f"  ✗ {name}  FAIL: {e}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {name}  ERROR: {type(e).__name__}: {e}")


def _td(name, cmd, expected_id):
    """便捷包装: 预期命中危险类别 expected_id（1-7）的命令。"""
    _t(name, cmd, True, expected_id=expected_id)


# ── 1. 空命令与纯空白命令 —— 安全 ───────────────────────────

def test_01_empty_string():
    _t("空字符串视为安全", "", False)


def test_02_whitespace_only():
    _t("纯空白命令视为安全", "   \t  \n  ", False)


# ── 2. 常见安全命令 ────────────────────────────────────────

def test_03_safe_ls():
    _t("ls 视为安全", "ls -la", False)


def test_04_safe_cat():
    _t("cat 视为安全", "cat /etc/hosts", False)


def test_05_safe_echo():
    _t("echo 视为安全", "echo hello world", False)


def test_06_safe_chmod_normal_mode():
    _t("chmod 644 视为安全", "chmod 644 file.txt", False)


def test_07_safe_chmod_755():
    _t("chmod 755 视为安全", "chmod -R 755 dir/", False)


def test_08_safe_chown():
    _t("chown 非 root 视为安全", "chown user:user file", False)


def test_09_safe_kill_15():
    _t("kill -15 视为安全", "kill -15 1234", False)


def test_10_safe_kill_9_pid():
    _t("kill -9 普通 PID 视为安全", "kill -9 1234", False)


def test_11_safe_su_user():
    _t("su 普通用户视为安全", "su postgres", False)


def test_12_safe_export_other():
    _t("export 非 PATH 视为安全", "export FOO=bar", False)


def test_13_safe_unset_other():
    _t("unset 非 PATH 视为安全", "unset FOO", False)


def test_14_safe_history_no_c():
    _t("history 无 -c 视为安全", "history | grep foo", False)


def test_15_safe_write_tmp():
    _t("重定向到 /tmp 视为安全", "echo foo > /tmp/file", False)


# ── 3. 类别 1: rm / unlink ─────────────────────────────────

def test_20_rm_rf():
    _td("rm -rf 视为危险 (类别1)", "rm -rf /", 1)


def test_21_rm_fr():
    _td("rm -fr 视为危险 (类别1)", "rm -fr foo", 1)


def test_22_rm_r():
    _td("rm -r 视为危险 (类别1)", "rm -r build/", 1)


def test_23_rm_f():
    _td("rm -f 视为危险 (类别1)", "rm -f file", 1)


def test_24_rm_no_flag():
    _td("rm 无参数 视为危险 (类别1)", "rm foo", 1)


def test_25_unlink():
    _td("unlink 视为危险 (类别1)", "unlink /tmp/file", 1)


def test_26_rm_case_insensitive():
    _td("RM 大写 仍视为危险 (类别1)", "RM -RF /", 1)


def test_27_rm_strip_whitespace():
    _td("rm 前后空白自动裁剪", "   rm -rf /  ", 1)


def test_28_rmdir_safe():
    """rmdir 不是 rm, \brm\s+ 无法在 "rmdir" 中匹配, 应视为安全。"""
    _t("rmdir 不应触发 rm 规则", "rmdir old_dir", False)


def test_29_rm_alone_safe():
    """裸 'rm' 没有 \s+ 跟随, 任何 rm 模式都无法命中。"""
    _t("裸 rm 不应触发", "rm", False)


def test_30_firmware_word_boundary():
    """firmware 中含有 'rm' 子串, 但 \b 无法在 fi 与 rm 之间匹配, 应视为安全。"""
    _t("firmware 不应触发 rm 规则", "firmware_update_tool", False)


# ── 4. 类别 2: mkfs / fdisk / parted / dd ──────────────────

def test_31_mkfs_ext4():
    _td("mkfs.ext4 视为危险 (类别2)", "mkfs.ext4 /dev/sda1", 2)


def test_32_mkfs_bare():
    _td("mkfs 视为危险 (类别2)", "mkfs /dev/sda1", 2)


def test_33_fdisk():
    _td("fdisk 视为危险 (类别2)", "fdisk -l", 2)


def test_34_parted():
    _td("parted 视为危险 (类别2)", "parted /dev/sda", 2)


def test_35_dd_if_of():
    _td("dd if= of= 视为危险 (类别2)", "dd if=/dev/zero of=/dev/sda", 2)


def test_36_dd_if_of_pipe():
    _td("dd 复合管道 仍视为危险 (类别2)", "gunzip -c disk.img | dd if=/dev/stdin of=/dev/sda", 2)


# ── 5. 类别 3: chmod 危险模式 / chown root ────────────────

def test_40_chmod_777():
    _td("chmod 777 视为危险 (类别3)", "chmod 777 file", 3)


def test_41_chmod_R_777():
    _td("chmod -R 777 视为危险 (类别3)", "chmod -R 777 /var/www", 3)


def test_42_chmod_1777():
    _td("chmod 1777 (sticky+777) 视为危险 (类别3)", "chmod 1777 /tmp", 3)


def test_43_chmod_2777():
    _td("chmod 2777 (sgid+777) 视为危险 (类别3)", "chmod 2777 dir", 3)


def test_44_chmod_0777():
    _td("chmod 0777 视为危险 (类别3)", "chmod 0777 file", 3)


def test_45_chown_root():
    _td("chown ... root 视为危险 (类别3)", "chown user:root file", 3)


def test_46_chown_dash_R_root():
    _td("chown -R root 视为危险 (类别3)", "chown -R root /etc", 3)


def test_47_chmod_644_safe():
    _t("chmod 644 不应触发 (非 7X7X)", "chmod 644 file", False)


def test_48_chmod_2700_safe():
    """chmod 2700 = 2,7,0,0 —— 模式 \d*7\d*7 要求以 7 结尾, 2700 不匹配。"""
    _t("chmod 2700 不应触发 (末位非 7)", "chmod 2700 dir", False)


# ── 6. 类别 4: sudo rm / su - / su root ───────────────────

def test_50_sudo_rm():
    """'sudo rm ...' 同时命中 rm 模式 (类别1) 与 sudo 模式 (类别4),
    由于 rm 模式在 dangerous_patterns 列表中更靠前, '先命中先返回' 判为类别1。"""
    _td("sudo rm 命中 rm 模式优先 (类别1)", "sudo rm -rf /var/log", 1)


def test_51_su_dash_c():
    """'su -' 末尾的 - 因 \b 缺失不会触发, 真实场景用 'su -c' 才会命中。"""
    _td("su -c 视为危险 (类别4)", "su -c whoami", 4)


def test_52_su_root():
    _td("su root 视为危险 (类别4)", "su root", 4)


def test_53_su_dash_alone_safe():
    """已知限制: 'su -' (单独) 因 \b 缺失不触发, 视为安全。"""
    _t("裸 'su -' 不应触发 (词边界限制)", "su -", False)


def test_54_sudo_other_safe():
    """sudo 后接非 rm 命令, 不应触发。"""
    _t("sudo apt 不应触发", "sudo apt update", False)


# ── 7. 类别 5: kill -9 PID 1 / killall -9 / pkill -9 ─────

def test_60_kill_9_pid1():
    _td("kill -9 1 视为危险 (类别5)", "kill -9 1", 5)


def test_61_kill_9_negative_pid():
    _td("kill -9 -1 视为危险 (类别5)", "kill -9 -1", 5)


def test_62_kill_9_negative_pid_long():
    _td("kill -9 -1234 视为危险 (类别5)", "kill -9 -1234", 5)


def test_63_killall_9():
    _td("killall -9 视为危险 (类别5)", "killall -9 nginx", 5)


def test_64_pkill_9():
    _td("pkill -9 视为危险 (类别5)", "pkill -9 python", 5)


def test_65_pkill_f_safe():
    """pkill -f 不带 -9, 不应触发。"""
    _t("pkill -f 不应触发", "pkill -f nginx", False)


# ── 8. 类别 6: export PATH / unset PATH / 写入 /etc/ ─────

def test_70_export_PATH():
    _td("export PATH= 视为危险 (类别6)", "export PATH=/usr/local/bin:$PATH", 6)


def test_71_unset_PATH():
    _td("unset PATH 视为危险 (类别6)", "unset PATH", 6)


def test_72_echo_etc():
    _td("echo > /etc/ 视为危险 (类别6)", "echo nameserver 8.8.8.8 > /etc/resolv.conf", 6)


def test_73_append_etc():
    _td(">> /etc/ 视为危险 (类别6)", "echo foo >> /etc/hosts", 6)


def test_74_cat_redirect_etc():
    _td("cat > /etc/ 视为危险 (类别6)", "cat > /etc/passwd", 6)


def test_75_export_PATH_case():
    _td("EXPORT PATH= 大写仍视为危险 (类别6)", "EXPORT PATH=/tmp", 6)


def test_76_cat_etc_safe():
    """读取 /etc/ 不应触发 (仅重定向才触发)。"""
    _t("cat /etc/hosts 不应触发", "cat /etc/hosts", False)


# ── 9. 类别 7: history -c / /dev/null 2>&1 ────────────────

def test_80_history_c():
    _td("history -c 视为危险 (类别7)", "history -c", 7)


def test_81_dev_null_redirect():
    _td("> /dev/null 2>&1 视为危险 (类别7)", "echo foo > /dev/null 2>&1", 7)


def test_82_dev_null_redirect_alt():
    """>> 形式也应匹配 (>>? 涵盖 > 和 >>)。"""
    _td(">> /dev/null 2>&1 视为危险 (类别7)", "echo foo >> /dev/null 2>&1", 7)


# ── 10. 综合场景 ─────────────────────────────────────────

def test_90_multi_category_first_wins():
    """rm 与 sudo 同时出现, rm 模式更靠前, 优先命中类别 1。"""
    _td("rm -rf 配合 sudo 仍判为类别1 (rm)", "sudo rm -rf /tmp/x", 1)


def test_91_sudo_before_rm_hits_rm():
    """'sudo bash -c rm ...' 仍因含 rm 子串, 命中 rm 模式 (类别1) 优先于 sudo 模式 (类别4)。"""
    _td("sudo 在前的命令仍判为类别1 (rm 先命中)", "sudo bash -c 'rm -rf /'", 1)


def test_92_dd_in_safe_context():
    """dd 出现在 echo 中也算 dd 模式命中, 类别 2。"""
    _td("dd 出现在 echo 中 仍视为危险 (类别2)", "echo dd if=/dev/zero of=/dev/null", 2)


# ── 入口 ───────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== _check_command_safety 单元测试 ===\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()

    print(f"\n{'='*40}")
    print(f"通过: {passed}  失败: {failed}  总计: {passed + failed}")
    if failed:
        sys.exit(1)
