# kdev

Utilities for Linux kernel development, built on [drgn](https://github.com/osandov/drgn) for live kernel introspection.

## Prerequisites

- Python 3.6+
- [drgn](https://drgn.readthedocs.io/) (the programmable debugger)
- Kernel debug symbols (debuginfo package or debuginfod)

### Installing debug symbols

**Fedora** (debuginfod, recommended):
```bash
export DEBUGINFOD_URLS="https://debuginfod.fedoraproject.org/"
sudo -E drgn  # -E preserves the env var
```

**Fedora** (package):
```bash
sudo dnf install kernel-debuginfo-$(uname -r)
```

**Ubuntu/Debian**:
```bash
sudo apt install linux-image-$(uname -r)-dbgsym
```

## Tools

### fs/lsof.py

A drgn-based `lsof` that inspects live kernel structures to list mount points and open files.

```bash
# List all mount points
sudo drgn fs/lsof.py --mount-points

# List open files on a specific mount
sudo drgn fs/lsof.py --mnt /proc

# List all open files grouped by mount
sudo drgn fs/lsof.py

# Inspect struct file, inode, and dentry for an open file (flags can be combined)
sudo drgn fs/lsof.py --show-file --show-inode --show-dentry /proc/kcore
```

## Testing

```bash
# Unit tests (no root required)
python3 fs/tests/test_common.py

# Integration tests (requires root + debug symbols)
sudo drgn fs/tests/test_lsof.py
```

## Project Structure

```
fs/
  common.py              # Reusable utilities (formatting, table output, arg parsing)
  lsof.py                # drgn-based lsof tool
  tests/
    test_common.py        # Unit tests for common.py (49 tests)
    test_lsof.py          # Integration tests against live kernel (22 tests)
```
