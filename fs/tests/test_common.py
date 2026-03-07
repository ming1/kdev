"""Unit tests for common.py pure utility functions.

Run with: python3 fs/tests/test_common.py
No root or drgn required.
"""

import io
import stat
import sys
import os
import unittest

# Mock drgn.FaultError since common.py imports it at module level
import types
drgn_mock = types.ModuleType("drgn")
drgn_mock.FaultError = type("FaultError", (Exception,), {})
sys.modules.setdefault("drgn", drgn_mock)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common import (
    file_type_str,
    format_dev,
    format_file_flags,
    format_file_mode,
    format_inode_perm,
    format_timestamp,
    print_table,
)


class TestFileTypeStr(unittest.TestCase):
    def test_regular(self):
        self.assertEqual(file_type_str(stat.S_IFREG | 0o644), "REG")

    def test_directory(self):
        self.assertEqual(file_type_str(stat.S_IFDIR | 0o755), "DIR")

    def test_char_device(self):
        self.assertEqual(file_type_str(stat.S_IFCHR | 0o666), "CHR")

    def test_block_device(self):
        self.assertEqual(file_type_str(stat.S_IFBLK | 0o660), "BLK")

    def test_fifo(self):
        self.assertEqual(file_type_str(stat.S_IFIFO | 0o644), "FIFO")

    def test_socket(self):
        self.assertEqual(file_type_str(stat.S_IFSOCK | 0o755), "SOCK")

    def test_symlink(self):
        self.assertEqual(file_type_str(stat.S_IFLNK | 0o777), "LNK")

    def test_unknown(self):
        self.assertEqual(file_type_str(0), "???")


class TestFormatFileMode(unittest.TestCase):
    def test_read_only(self):
        self.assertEqual(format_file_mode(0x1), "READ")

    def test_write_only(self):
        self.assertEqual(format_file_mode(0x2), "WRITE")

    def test_read_write(self):
        result = format_file_mode(0x3)
        self.assertIn("READ", result)
        self.assertIn("WRITE", result)

    def test_read_with_lseek(self):
        result = format_file_mode(0x5)
        self.assertIn("READ", result)
        self.assertIn("LSEEK", result)

    def test_no_bits(self):
        self.assertEqual(format_file_mode(0x0), "0x0")

    def test_multiple_bits(self):
        self.assertEqual(format_file_mode(0x1 | 0x2 | 0x4 | 0x8),
                         "READ|WRITE|LSEEK|PREAD")


class TestFormatFileFlags(unittest.TestCase):
    def test_rdonly(self):
        self.assertEqual(format_file_flags(0o0), "O_RDONLY")

    def test_wronly(self):
        self.assertEqual(format_file_flags(0o1), "O_WRONLY")

    def test_rdwr(self):
        self.assertEqual(format_file_flags(0o2), "O_RDWR")

    def test_rdwr_append(self):
        result = format_file_flags(0o2 | 0o2000)
        self.assertIn("O_RDWR", result)
        self.assertIn("O_APPEND", result)

    def test_wronly_creat_trunc(self):
        result = format_file_flags(0o1 | 0o100 | 0o1000)
        self.assertIn("O_WRONLY", result)
        self.assertIn("O_CREAT", result)
        self.assertIn("O_TRUNC", result)

    def test_rdonly_largefile(self):
        result = format_file_flags(0o100000)
        self.assertIn("O_RDONLY", result)
        self.assertIn("O_LARGEFILE", result)

    def test_cloexec(self):
        self.assertIn("O_CLOEXEC", format_file_flags(0o2000000))

    def test_nonblock(self):
        self.assertIn("O_NONBLOCK", format_file_flags(0o4000))


class TestFormatInodePerm(unittest.TestCase):
    def test_644(self):
        self.assertEqual(format_inode_perm(0o644), "rw-r--r--")

    def test_755(self):
        self.assertEqual(format_inode_perm(0o755), "rwxr-xr-x")

    def test_777(self):
        self.assertEqual(format_inode_perm(0o777), "rwxrwxrwx")

    def test_000(self):
        self.assertEqual(format_inode_perm(0o000), "---------")

    def test_400(self):
        self.assertEqual(format_inode_perm(0o400), "r--------")

    def test_setuid(self):
        self.assertEqual(format_inode_perm(stat.S_ISUID | 0o755), "rwsr-xr-x")

    def test_setuid_no_exec(self):
        self.assertEqual(format_inode_perm(stat.S_ISUID | 0o644), "rwSr--r--")

    def test_setgid(self):
        self.assertEqual(format_inode_perm(stat.S_ISGID | 0o755), "rwxr-sr-x")

    def test_setgid_no_exec(self):
        self.assertEqual(format_inode_perm(stat.S_ISGID | 0o644), "rw-r-Sr--")

    def test_sticky(self):
        self.assertEqual(format_inode_perm(stat.S_ISVTX | 0o755), "rwxr-xr-t")

    def test_sticky_no_exec(self):
        self.assertEqual(format_inode_perm(stat.S_ISVTX | 0o744), "rwxr--r-T")

    def test_full_mode_with_type_bits(self):
        self.assertEqual(format_inode_perm(stat.S_IFREG | 0o644), "rw-r--r--")


class TestFormatDev(unittest.TestCase):
    def test_null_device(self):
        # /dev/null is 1:3, encoded as MKDEV(1,3)
        self.assertEqual(format_dev((1 << 20) | 3), "1:3")

    def test_zero_device(self):
        self.assertEqual(format_dev(0), "0:0")

    def test_sda(self):
        self.assertEqual(format_dev((8 << 20) | 0), "8:0")

    def test_sda1(self):
        self.assertEqual(format_dev((8 << 20) | 1), "8:1")

    def test_loop0(self):
        self.assertEqual(format_dev((7 << 20) | 0), "7:0")


class TestFormatTimestamp(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(format_timestamp(0), "0")

    def test_negative(self):
        self.assertEqual(format_timestamp(-1), "0")

    def test_epoch(self):
        self.assertEqual(format_timestamp(1), "1970-01-01 00:00:01")

    def test_known_date(self):
        # format_timestamp uses UTC
        result = format_timestamp(1772870400)
        self.assertTrue(result.startswith("2026-03-07"))

    def test_recent_date(self):
        self.assertTrue(format_timestamp(1709827200).startswith("2024-03-07"))


class TestPrintTable(unittest.TestCase):
    def _capture(self, fn):
        """Capture stdout from fn()."""
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            fn()
            return sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def test_basic_table(self):
        output = self._capture(
            lambda: print_table(["NAME", "VALUE"],
                                [("foo", "1"), ("bar", "22")]))
        lines = output.strip().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertIn("NAME", lines[0])
        self.assertIn("VALUE", lines[0])
        self.assertIn("foo", lines[1])
        self.assertIn("bar", lines[2])

    def test_empty_rows(self):
        output = self._capture(lambda: print_table(["A", "B"], []))
        self.assertEqual(output, "")

    def test_column_width_adapts(self):
        output = self._capture(
            lambda: print_table(["X"],
                                [("short",), ("a much longer value",)]))
        lines = output.strip().split("\n")
        # The longest value row should fill the column width
        self.assertGreaterEqual(len(lines[2].rstrip()),
                                len("a much longer value"))

    def test_numeric_values(self):
        output = self._capture(
            lambda: print_table(["PID", "FD"], [(123, 4), (5678, 10)]))
        self.assertIn("123", output)
        self.assertIn("5678", output)

    def test_short_row_padded(self):
        output = self._capture(
            lambda: print_table(["A", "B", "C"], [("x",)]))
        self.assertIn("x", output)


if __name__ == "__main__":
    unittest.main()
