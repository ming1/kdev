"""Reusable utilities for drgn-based filesystem tools."""

import argparse
import stat
import datetime

from drgn import FaultError


def file_type_str(mode):
    """Decode inode i_mode to a file type string."""
    fmt = stat.S_IFMT(mode)
    return {
        stat.S_IFREG: "REG",
        stat.S_IFDIR: "DIR",
        stat.S_IFCHR: "CHR",
        stat.S_IFBLK: "BLK",
        stat.S_IFIFO: "FIFO",
        stat.S_IFSOCK: "SOCK",
        stat.S_IFLNK: "LNK",
    }.get(fmt, "???")


def safe_string(obj):
    """Extract a string from a drgn object, handling faults."""
    try:
        return obj.string_().decode(errors="replace")
    except (FaultError, AttributeError):
        return "<fault>"


def safe_d_path(file_or_path):
    """Wrap drgn d_path() with error handling."""
    from drgn.helpers.linux.fs import d_path
    try:
        return d_path(file_or_path).decode(errors="replace")
    except (FaultError, Exception):
        return "<unknown>"


def print_table(headers, rows):
    """Print auto-width aligned column output."""
    if not rows:
        return
    widths = [len(h) for h in headers]
    str_rows = []
    for row in rows:
        str_row = [str(v) for v in row]
        str_rows.append(str_row)
        for i, v in enumerate(str_row):
            if i < len(widths):
                widths[i] = max(widths[i], len(v))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    for row in str_rows:
        # Pad row to match header count
        while len(row) < len(headers):
            row.append("")
        print(fmt.format(*row))


def make_base_parser(desc):
    """Create argparse parser with common filesystem tool flags."""
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("--mount-points", action="store_true",
                        help="List all mount points")
    parser.add_argument("--mnt", metavar="PATH",
                        help="List open files on a specific mount point")
    parser.add_argument("--show-file", action="store_true",
                        help="Show struct file info")
    parser.add_argument("--show-inode", action="store_true",
                        help="Show struct inode info")
    parser.add_argument("--show-dentry", action="store_true",
                        help="Show struct dentry info")
    parser.add_argument("path", nargs="?", default=None,
                        help="File path (used with --file/--inode/--dentry)")
    return parser


# --- Formatting helpers ---

# FMODE flags from include/linux/fs.h
_FMODE_BITS = [
    (0x1, "READ"),
    (0x2, "WRITE"),
    (0x4, "LSEEK"),
    (0x8, "PREAD"),
    (0x10, "PWRITE"),
    (0x20, "EXEC"),
    (0x800, "CAN_READ"),
    (0x1000, "CAN_WRITE"),
]


def format_file_mode(f_mode):
    """Decode fmode_t bitmask to a human-readable string."""
    val = int(f_mode)
    parts = [name for bit, name in _FMODE_BITS if val & bit]
    return "|".join(parts) if parts else f"0x{val:x}"


# O_* flags from include/uapi/asm-generic/fcntl.h
_O_FLAGS = [
    (0o0, "O_RDONLY"),      # special: only if no WRONLY/RDWR
    (0o1, "O_WRONLY"),
    (0o2, "O_RDWR"),
    (0o100, "O_CREAT"),
    (0o200, "O_EXCL"),
    (0o400, "O_NOCTTY"),
    (0o1000, "O_TRUNC"),
    (0o2000, "O_APPEND"),
    (0o4000, "O_NONBLOCK"),
    (0o10000, "O_DSYNC"),
    (0o20000, "O_FASYNC"),
    (0o40000, "O_DIRECT"),
    (0o100000, "O_LARGEFILE"),
    (0o200000, "O_DIRECTORY"),
    (0o400000, "O_NOFOLLOW"),
    (0o1000000, "O_NOATIME"),
    (0o2000000, "O_CLOEXEC"),
    (0o4000000, "O_PATH"),
]


def format_file_flags(f_flags):
    """Decode O_* flags to a human-readable string."""
    val = int(f_flags)
    accmode = val & 0o3
    parts = []
    if accmode == 0:
        parts.append("O_RDONLY")
    elif accmode == 1:
        parts.append("O_WRONLY")
    elif accmode == 2:
        parts.append("O_RDWR")
    for bit, name in _O_FLAGS:
        if bit <= 2:
            continue  # already handled access mode
        if val & bit:
            parts.append(name)
    return "|".join(parts) if parts else "0"


def format_inode_perm(i_mode):
    """Permission bits to rwxrwxrwx string."""
    val = int(i_mode)
    result = ""
    for shift in (6, 3, 0):
        bits = (val >> shift) & 7
        result += "r" if bits & 4 else "-"
        result += "w" if bits & 2 else "-"
        result += "x" if bits & 1 else "-"
    # setuid/setgid/sticky
    if val & stat.S_ISUID:
        result = result[:2] + ("s" if result[2] == "x" else "S") + result[3:]
    if val & stat.S_ISGID:
        result = result[:5] + ("s" if result[5] == "x" else "S") + result[6:]
    if val & stat.S_ISVTX:
        result = result[:8] + ("t" if result[8] == "x" else "T") + result[9:]
    return result


def format_dev(rdev):
    """Format dev_t as major:minor."""
    val = int(rdev)
    major = (val >> 20) & 0xfff | ((val >> 32) & ~0xfff)
    minor = (val & 0xfffff) | ((val >> 12) & ~0xfffff)
    return f"{major}:{minor}"


def format_timestamp(sec):
    """Format time64_t seconds to human-readable datetime."""
    try:
        val = int(sec)
        if val <= 0:
            return "0"
        dt = datetime.datetime.fromtimestamp(val, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return str(int(sec))
