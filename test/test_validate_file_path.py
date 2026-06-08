"""Tests for _validate_file_path() — covers every branch of the
project-root file-path validator.

Categories:
    * Valid existing files (root, subdir, dotdot-internal, dotfile)
    * Valid non-existent files (passes because isdir() is False)
    * Rejected directories (test/, project root '.', empty string)
    * Rejected outside-project-root paths (absolute, /tmp, ../, deep ../,
      sibling dir, prefix-collision 'evil' sibling)
    * Symlink to outside-file (realpath() resolves to outside)

NOTE: This file relies on `mangopi_cli.project_root == os.getcwd()`.
Run from the project root:
    python test/test_validate_file_path.py
"""
import os
import sys
import tempfile
import unittest

# Add parent dir to sys.path so we can import mangopi_cli.
# This file lives at <project>/test/test_validate_file_path.py,
# so the project root is one level up from __file__'s directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mangopi_cli  # noqa: E402


# Module-level constant for the project's root, captured at import time.
# Used by tests that need to construct sibling/parent paths.
PROJECT_ROOT = mangopi_cli.project_root


# ── Shared helpers ───────────────────────────────────────────────────────────


class _ValidateFilePathBase(unittest.TestCase):
    """Base for asserting _validate_file_path() outcomes.

    Subclasses get `assertValid(path)` and `assertInvalid(path, substring)`
    so test bodies stay readable.
    """

    def assertValid(self, path):
        """Path must be classified as valid (return value is None)."""
        result = mangopi_cli._validate_file_path(path)
        self.assertIsNone(
            result,
            f"expected None (valid), got {result!r} for path: {path!r}",
        )

    def assertInvalid(self, path, expected_error_substring):
        """Path must be classified as invalid with an error containing
        the given substring."""
        result = mangopi_cli._validate_file_path(path)
        self.assertIsNotNone(
            result,
            f"expected error containing {expected_error_substring!r}, "
            f"got None for path: {path!r}",
        )
        self.assertIn(
            expected_error_substring,
            result,
            f"expected error containing {expected_error_substring!r}, "
            f"got {result!r} for path: {path!r}",
        )


# ── 1. Valid: existing files inside project root ────────────────────────────


class TestValidExistingFiles(_ValidateFilePathBase):
    """Real files that exist inside the project root must be accepted."""

    def test_01_existing_file_in_root(self):
        self.assertValid("mangopi_cli.py")

    def test_02_existing_file_in_subdir(self):
        self.assertValid("test/test_check_command_safety.py")

    def test_03_nested_relative_path_with_dotdot_inside(self):
        # '..' segments must not push us out of the project root.
        self.assertValid("test/../mangopi_cli.py")

    def test_04_pyproject_file(self):
        self.assertValid("pyproject.toml")


# ── 2. Valid: non-existent files (not a directory) ───────────────────────────


class TestValidNonExistentFiles(_ValidateFilePathBase):
    """A non-existent path that is NOT a directory must be classified as
    valid — the validator only rejects things that resolve to a directory
    or that fall outside the project root.
    """

    def test_10_nonexistent_file_in_root(self):
        self.assertValid("_vfp_definitely_not_existing_xyz_12345.txt")

    def test_11_nonexistent_file_in_subdir(self):
        self.assertValid("test/_vfp_nonexistent_xyz_67890.py")


# ── 3. Rejected: directories inside project root ────────────────────────────


class TestRejectedDirectories(_ValidateFilePathBase):
    """Paths that resolve to a directory inside the project root must be
    rejected with the 'is a directory, not a file' message.
    """

    def test_20_test_dir_is_directory(self):
        self.assertInvalid("test", "is a directory")

    def test_21_project_root_itself(self):
        # The project root itself is a directory and must be rejected.
        self.assertInvalid(".", "is a directory")

    def test_22_empty_string_path(self):
        # An empty string is abspath()'d to cwd (= project root), so it
        # must also be rejected as a directory.
        self.assertInvalid("", "is a directory")


# ── 4. Rejected: paths outside project root ─────────────────────────────────


class TestRejectedOutsideProjectRoot(_ValidateFilePathBase):
    """Paths whose realpath() falls outside project_root must be rejected
    with the 'is outside project root' message.
    """

    def test_30_absolute_path_outside_etc(self):
        self.assertInvalid("/etc/passwd", "is outside project root")

    def test_31_absolute_path_tmp(self):
        self.assertInvalid(
            "/tmp/some_random_file_outside_project_xyz.txt",
            "is outside project root",
        )

    def test_32_parent_dir_traversal(self):
        self.assertInvalid("../etc/passwd", "is outside project root")

    def test_33_deep_parent_dir_traversal(self):
        self.assertInvalid("../../../etc/hosts", "is outside project root")

    def test_34_sibling_dir_outside(self):
        sibling = os.path.join(PROJECT_ROOT, "..", "sibling_dir_outside_project_xyz")
        self.assertInvalid(sibling, "is outside project root")

    def test_35_prefix_collision_evil_sibling(self):
        """Guard against the classic startswith() prefix-collision bug.

        Project root:  /Users/moofs/Code/mangopi-cli
        Evil sibling:  /Users/moofs/Code/mangopi-cli_evil_xyz/foo.txt

        Without the trailing os.sep, real_root.startswith(evil) would
        pass because the evil path starts with the project-root string.
        The validator MUST reject the evil sibling.
        """
        parent = os.path.dirname(PROJECT_ROOT)              # .../Code
        root_basename = os.path.basename(PROJECT_ROOT)      # mangopi-cli
        evil_sibling = os.path.join(
            parent, root_basename + "_evil_xyz", "foo.txt"
        )
        # Sanity-check the test setup itself: the evil sibling must
        # actually start with PROJECT_ROOT as a string (the bug case).
        self.assertTrue(
            os.path.abspath(evil_sibling).startswith(PROJECT_ROOT),
            "test setup: evil sibling should share a prefix with PROJECT_ROOT",
        )
        self.assertInvalid(evil_sibling, "is outside project root")


# ── 5. Symlink to outside file ──────────────────────────────────────────────


class TestSymlinkToOutsideFile(_ValidateFilePathBase):
    """A symlink inside the project root that points at a file outside the
    project root must be rejected, because _validate_file_path uses
    realpath() to resolve symlinks before checking.
    """

    def test_40_symlink_to_outside_file(self):
        # Real target outside the project (in /tmp).
        fd, outside_path = tempfile.mkstemp(prefix="vfp_target_", dir="/tmp")
        os.close(fd)
        # Symlink inside project root pointing at the outside target.
        link_name = "_vfp_symlink_outside_test_link"
        link_path = os.path.join(PROJECT_ROOT, link_name)
        # Tidy up any leftover link from a prior run.
        if os.path.lexists(link_path):
            os.unlink(link_path)
        try:
            try:
                os.symlink(outside_path, link_path)
            except (OSError, NotImplementedError) as e:
                # Some platforms (e.g. Windows without admin rights) don't
                # permit symlinks; treat that as a skip, not a failure.
                self.skipTest(
                    f"{type(e).__name__}: {e}"
                )
            self.assertInvalid(
                link_path,
                "is outside project root",
            )
        finally:
            # Always clean up both the symlink and the /tmp target.
            if os.path.lexists(link_path):
                os.unlink(link_path)
            if os.path.exists(outside_path):
                os.unlink(outside_path)


if __name__ == "__main__":
    # Run with verbose output
    unittest.main(verbosity=2)