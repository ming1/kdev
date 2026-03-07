#!/usr/bin/env drgn
"""
Integration tests for lsof.py against the live kernel.

Run with: sudo drgn fs/tests/test_lsof.py

Tests verify kernel data structure access using known invariants:
  - /proc and /sys are always mounted
  - drgn itself has /proc/kcore open
  - PID 1 (init/systemd) always exists
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from lsof import (
    get_all_mounts,
    build_vfsmount_index,
    get_open_files,
    find_open_file,
)

passed = 0
failed = 0
errors = []


def run_test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  PASS  {name}")
    except AssertionError as e:
        failed += 1
        errors.append((name, e))
        print(f"  FAIL  {name}: {e}")
    except Exception as e:
        failed += 1
        errors.append((name, e))
        print(f"  ERROR {name}: {e}")
        traceback.print_exc()


# ===== get_all_mounts tests =====

def test_mounts_returns_list():
    mounts = get_all_mounts(prog)
    assert isinstance(mounts, list), f"expected list, got {type(mounts)}"
    assert len(mounts) > 0, "expected at least one mount"

def test_mounts_has_proc():
    mounts = get_all_mounts(prog)
    dsts = [m["dst"] for m in mounts]
    assert "/proc" in dsts, f"/proc not found in mounts: {dsts}"

def test_mounts_has_sys():
    mounts = get_all_mounts(prog)
    dsts = [m["dst"] for m in mounts]
    assert "/sys" in dsts, f"/sys not found in mounts: {dsts}"

def test_mounts_has_root():
    mounts = get_all_mounts(prog)
    dsts = [m["dst"] for m in mounts]
    assert "/" in dsts, f"/ not found in mounts: {dsts}"

def test_mounts_sorted():
    mounts = get_all_mounts(prog)
    dsts = [m["dst"] for m in mounts]
    assert dsts == sorted(dsts), "mounts should be sorted by dst path"

def test_mounts_have_required_keys():
    mounts = get_all_mounts(prog)
    for m in mounts:
        for key in ("mnt", "dst", "fstype", "src"):
            assert key in m, f"mount missing key '{key}': {m}"

def test_mounts_proc_fstype():
    mounts = get_all_mounts(prog)
    proc_mounts = [m for m in mounts if m["dst"] == "/proc"]
    assert len(proc_mounts) >= 1, "no /proc mount found"
    assert proc_mounts[0]["fstype"] == "proc", \
        f"expected proc fstype, got {proc_mounts[0]['fstype']}"

def test_mounts_no_nullfs():
    mounts = get_all_mounts(prog)
    fstypes = [m["fstype"] for m in mounts]
    assert "nullfs" not in fstypes, "nullfs should be filtered out"


# ===== build_vfsmount_index tests =====

def test_vfsmount_index_not_empty():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    assert isinstance(index, dict), f"expected dict, got {type(index)}"
    assert len(index) > 0, "index should not be empty"

def test_vfsmount_index_keys_are_ints():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    for key in index:
        assert isinstance(key, int), f"expected int key, got {type(key)}: {key}"

def test_vfsmount_index_values_are_mount_dicts():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    for val in index.values():
        assert "dst" in val, f"index value missing 'dst': {val}"
        assert "fstype" in val, f"index value missing 'fstype': {val}"

def test_vfsmount_index_matches_mounts_count():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    # index should have same number of entries as mounts (one per mount)
    assert len(index) == len(mounts), \
        f"index has {len(index)} entries but {len(mounts)} mounts exist"


# ===== get_open_files tests =====

def test_open_files_returns_list():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    files = get_open_files(prog, index)
    assert isinstance(files, list), f"expected list, got {type(files)}"
    assert len(files) > 0, "expected at least one open file"

def test_open_files_have_required_keys():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    files = get_open_files(prog, index)
    for f in files[:10]:  # check first 10
        for key in ("pid", "uid", "fd", "type", "comm", "path", "mount_dst"):
            assert key in f, f"file entry missing key '{key}': {f}"

def test_open_files_pid1_exists():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    files = get_open_files(prog, index)
    pids = {f["pid"] for f in files}
    assert 1 in pids, "PID 1 (init) should have open files"

def test_open_files_no_duplicate_tgid_fd():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    files = get_open_files(prog, index)
    seen = set()
    for f in files:
        key = (f["pid"], f["fd"])
        assert key not in seen, f"duplicate (tgid, fd) = {key}"
        seen.add(key)

def test_open_files_have_valid_types():
    mounts = get_all_mounts(prog)
    index = build_vfsmount_index(mounts)
    files = get_open_files(prog, index)
    valid_types = {"REG", "DIR", "CHR", "BLK", "FIFO", "SOCK", "LNK", "???"}
    for f in files[:50]:
        assert f["type"] in valid_types, \
            f"unexpected file type '{f['type']}' for {f['path']}"


# ===== find_open_file tests =====

def test_find_kcore():
    """drgn itself has /proc/kcore open."""
    result = find_open_file(prog, "/proc/kcore")
    assert result is not None, "/proc/kcore should be opened (by drgn)"
    file_obj, openers = result
    assert len(openers) >= 1, "should have at least one opener"
    # One of the openers should be drgn
    comms = [comm for _, comm, _, _ in openers]
    assert any("drgn" in c for c in comms), \
        f"drgn should be among openers, got: {comms}"

def test_find_kcore_file_obj():
    """The returned file object should have valid struct file fields."""
    result = find_open_file(prog, "/proc/kcore")
    assert result is not None
    file_obj, _ = result
    addr = file_obj.value_()
    assert addr != 0, "file object address should not be NULL"
    # Should be on procfs
    fstype = file_obj.f_inode.i_sb.s_type.name.string_().decode()
    assert fstype == "proc", f"expected proc, got {fstype}"

def test_find_kcore_opener_has_valid_pid():
    result = find_open_file(prog, "/proc/kcore")
    assert result is not None
    _, openers = result
    for pid, comm, uid, fd in openers:
        assert pid > 0, f"pid should be > 0, got {pid}"
        assert fd >= 0, f"fd should be >= 0, got {fd}"
        assert isinstance(comm, str), f"comm should be str, got {type(comm)}"

def test_find_nonexistent():
    result = find_open_file(prog, "/this/path/does/not/exist/at/all")
    assert result is None, "nonexistent path should return None"

def test_find_dev_null():
    """/dev/null is typically opened by many processes."""
    result = find_open_file(prog, "/dev/null")
    assert result is not None, "/dev/null should be opened by something"
    file_obj, openers = result
    assert len(openers) >= 1


# ===== Run all tests =====

print("=== get_all_mounts ===")
run_test("mounts_returns_list", test_mounts_returns_list)
run_test("mounts_has_proc", test_mounts_has_proc)
run_test("mounts_has_sys", test_mounts_has_sys)
run_test("mounts_has_root", test_mounts_has_root)
run_test("mounts_sorted", test_mounts_sorted)
run_test("mounts_have_required_keys", test_mounts_have_required_keys)
run_test("mounts_proc_fstype", test_mounts_proc_fstype)
run_test("mounts_no_nullfs", test_mounts_no_nullfs)

print("\n=== build_vfsmount_index ===")
run_test("vfsmount_index_not_empty", test_vfsmount_index_not_empty)
run_test("vfsmount_index_keys_are_ints", test_vfsmount_index_keys_are_ints)
run_test("vfsmount_index_values_are_mount_dicts", test_vfsmount_index_values_are_mount_dicts)
run_test("vfsmount_index_matches_mounts_count", test_vfsmount_index_matches_mounts_count)

print("\n=== get_open_files ===")
run_test("open_files_returns_list", test_open_files_returns_list)
run_test("open_files_have_required_keys", test_open_files_have_required_keys)
run_test("open_files_pid1_exists", test_open_files_pid1_exists)
run_test("open_files_no_duplicate_tgid_fd", test_open_files_no_duplicate_tgid_fd)
run_test("open_files_have_valid_types", test_open_files_have_valid_types)

print("\n=== find_open_file ===")
run_test("find_kcore", test_find_kcore)
run_test("find_kcore_file_obj", test_find_kcore_file_obj)
run_test("find_kcore_opener_has_valid_pid", test_find_kcore_opener_has_valid_pid)
run_test("find_nonexistent", test_find_nonexistent)
run_test("find_dev_null", test_find_dev_null)

# ===== Summary =====
print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if errors:
    print("\nFailures:")
    for name, e in errors:
        print(f"  {name}: {e}")
    sys.exit(1)
else:
    print("All tests passed!")
