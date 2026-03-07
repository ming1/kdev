#!/usr/bin/env drgn
"""
drgn-based lsof: list mount points and open files from live kernel structures.

Usage:
    sudo drgn lsof.py [--mount-points] [--mnt PATH] [--file PATH]
                      [--inode PATH] [--dentry PATH]
"""

import os
import sys

# Allow importing common.py from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drgn import FaultError
from drgn.helpers.linux.fs import (
    d_path,
    for_each_file,
    for_each_mount,
    mount_dst,
    mount_fstype,
    mount_src,
)
from drgn.helpers.linux.pid import for_each_task

from common import (
    file_type_str,
    format_dev,
    format_file_flags,
    format_file_mode,
    format_inode_perm,
    format_timestamp,
    make_base_parser,
    print_table,
    safe_d_path,
)


def get_all_mounts(prog):
    """Collect mount info dicts via for_each_mount()."""
    mounts = []
    for mnt in for_each_mount(prog["init_nsproxy"].mnt_ns):
        try:
            info = {
                "mnt": mnt,
                "dst": mount_dst(mnt).decode(errors="replace"),
                "fstype": mount_fstype(mnt).decode(errors="replace"),
                "src": mount_src(mnt).decode(errors="replace"),
            }
            mounts.append(info)
        except FaultError:
            continue
    # Filter out nullfs (container implementation detail that shadows real mounts)
    mounts = [m for m in mounts if m["fstype"] != "nullfs"]
    mounts.sort(key=lambda m: m["dst"])
    return mounts


def build_vfsmount_index(mounts):
    """Map vfsmount pointer values to mount info dicts for O(1) lookup."""
    index = {}
    for info in mounts:
        try:
            vfsmount_addr = info["mnt"].mnt.address_of_().value_()
            index[vfsmount_addr] = info
        except (FaultError, AttributeError):
            continue
    return index


def get_open_files(prog, vfsmount_index):
    """Iterate all tasks/files, dedup by (tgid, fd), resolve mount points."""
    seen = set()
    files = []
    for task in for_each_task(prog):
        try:
            tgid = int(task.tgid)
            pid = int(task.pid)
            comm = task.comm.string_().decode(errors="replace")
            try:
                uid = int(task.cred.uid.val)
            except AttributeError:
                uid = int(task.cred.uid)
        except FaultError:
            continue
        for fd, f in for_each_file(task):
            key = (tgid, fd)
            if key in seen:
                continue
            seen.add(key)
            try:
                try:
                    inode = f.f_inode
                except AttributeError:
                    inode = f.f_path.dentry.d_inode
                mode = int(inode.i_mode)
                ftype = file_type_str(mode)
                path = safe_d_path(f.f_path)
                mnt_addr = f.f_path.mnt.value_()
                mount_info = vfsmount_index.get(mnt_addr)
                files.append({
                    "pid": tgid,
                    "uid": uid,
                    "fd": fd,
                    "type": ftype,
                    "comm": comm,
                    "path": path,
                    "mount_dst": mount_info["dst"] if mount_info else "<unknown>",
                })
            except FaultError:
                continue
    return files


def print_mount_points(mounts):
    """Table output for --mount-points mode."""
    headers = ["PATH", "FSTYPE", "SOURCE"]
    rows = [(m["dst"], m["fstype"], m["src"]) for m in mounts]
    print_table(headers, rows)


def print_files_for_mount(mount_path, fstype, files):
    """Section header + file table for one mount."""
    print(f"\n=== {mount_path} ({fstype}) ===")
    if not files:
        return
    headers = ["PID", "USER", "FD", "TYPE", "COMMAND", "PATH"]
    rows = [(f["pid"], f["uid"], f["fd"], f["type"], f["comm"], f["path"])
            for f in files]
    rows.sort(key=lambda r: (r[0], r[2]))
    print_table(headers, rows)


def find_open_file(prog, path):
    """Scan all tasks for a file matching path via d_path().

    Returns (file_obj, [(pid, comm, uid, fd), ...]) or None.
    """
    file_obj = None
    openers = []
    seen = set()
    for task in for_each_task(prog):
        try:
            tgid = int(task.tgid)
            comm = task.comm.string_().decode(errors="replace")
            try:
                uid = int(task.cred.uid.val)
            except AttributeError:
                uid = int(task.cred.uid)
        except FaultError:
            continue
        for fd, f in for_each_file(task):
            key = (tgid, fd)
            if key in seen:
                continue
            seen.add(key)
            try:
                fpath = d_path(f.f_path).decode(errors="replace")
            except (FaultError, Exception):
                continue
            if fpath == path:
                if file_obj is None:
                    file_obj = f
                openers.append((tgid, comm, uid, fd))
    if file_obj is None:
        return None
    return (file_obj, openers)


def print_file_info(path, file_obj, openers):
    """Display struct file details for --file."""
    try:
        addr = file_obj.value_()
        try:
            f_mode = file_obj.f_mode
        except AttributeError:
            f_mode = None
        f_flags = file_obj.f_flags
        f_pos = int(file_obj.f_pos)
        # Reference count: f_ref (>=6.12), f_count (older)
        try:
            f_count = int(file_obj.f_ref.refcnt.counter)
        except AttributeError:
            try:
                f_count = int(file_obj.f_count.counter)
            except AttributeError:
                f_count = -1
        try:
            inode = file_obj.f_inode
        except AttributeError:
            inode = file_obj.f_path.dentry.d_inode
        ino = int(inode.i_ino)
        inode_addr = inode.value_()
        try:
            fstype = file_obj.f_inode.i_sb.s_type.name.string_().decode(
                errors="replace")
        except FaultError:
            fstype = "<unknown>"
        from drgn.helpers.linux.fs import mount_dst as _mount_dst
        from drgn import container_of
        try:
            mnt_struct = container_of(file_obj.f_path.mnt, "struct mount",
                                      "mnt")
            mount_path = _mount_dst(mnt_struct).decode(errors="replace")
        except (FaultError, Exception):
            mount_path = "<unknown>"
    except FaultError as e:
        print(f"Error reading file struct: {e}", file=sys.stderr)
        return

    print(f"File: {path}")
    print(f"  address:    0x{addr:x}")
    print(f"  mode:       {format_file_mode(f_mode) if f_mode is not None else 'N/A'}")
    print(f"  flags:      {format_file_flags(f_flags)}")
    print(f"  pos:        {f_pos}")
    print(f"  ref:        {f_count}")
    print(f"  inode:      0x{inode_addr:x} (ino {ino})")
    print(f"  mount:      {mount_path} ({fstype})")
    print(f"  opened by:")
    for pid, comm, uid, fd in openers:
        print(f"    PID {pid}  {comm}  (fd {fd})")


def print_inode_info(path, file_obj):
    """Display struct inode details for --inode."""
    try:
        try:
            inode = file_obj.f_inode
        except AttributeError:
            inode = file_obj.f_path.dentry.d_inode
        addr = inode.value_()
        ino = int(inode.i_ino)
        mode = int(inode.i_mode)
        try:
            uid = int(inode.i_uid.val)
        except AttributeError:
            uid = int(inode.i_uid)
        try:
            gid = int(inode.i_gid.val)
        except AttributeError:
            gid = int(inode.i_gid)
        size = int(inode.i_size)
        nlink = int(inode.i_nlink)
        blocks = int(inode.i_blocks)
        rdev = int(inode.i_rdev)
        sb_addr = inode.i_sb.value_()
        try:
            fstype = inode.i_sb.s_type.name.string_().decode(errors="replace")
        except FaultError:
            fstype = "<unknown>"
        # Timestamps - try i_atime_sec (new), __i_atime.tv_sec, i_atime.tv_sec
        def get_ts(name):
            # New layout: i_atime_sec, i_mtime_sec, i_ctime_sec
            try:
                return int(getattr(inode, f"i_{name}_sec"))
            except (AttributeError, FaultError):
                pass
            # Old layout: __i_atime.tv_sec or i_atime.tv_sec
            for prefix in ("__i_", "i_"):
                try:
                    ts = getattr(inode, prefix + name)
                    return int(ts.tv_sec)
                except (AttributeError, FaultError):
                    continue
            return 0
        atime = get_ts("atime")
        mtime = get_ts("mtime")
        ctime = get_ts("ctime")
    except FaultError as e:
        print(f"Error reading inode: {e}", file=sys.stderr)
        return

    print(f"Inode for: {path}")
    print(f"  address:    0x{addr:x}")
    print(f"  ino:        {ino}")
    print(f"  type:       {file_type_str(mode)}")
    print(f"  mode:       {mode & 0o7777:04o} ({format_inode_perm(mode)})")
    print(f"  uid:        {uid}")
    print(f"  gid:        {gid}")
    print(f"  size:       {size}")
    print(f"  nlink:      {nlink}")
    print(f"  blocks:     {blocks}")
    print(f"  rdev:       {format_dev(rdev)}")
    print(f"  sb:         0x{sb_addr:x} ({fstype})")
    print(f"  atime:      {format_timestamp(atime)}")
    print(f"  mtime:      {format_timestamp(mtime)}")
    print(f"  ctime:      {format_timestamp(ctime)}")


def print_dentry_info(path, file_obj):
    """Display struct dentry details for --dentry."""
    try:
        dentry = file_obj.f_path.dentry
        addr = dentry.value_()
        name = dentry.d_name.name.string_().decode(errors="replace")
        parent = dentry.d_parent
        parent_addr = parent.value_()
        parent_name = parent.d_name.name.string_().decode(errors="replace")
        inode_addr = dentry.d_inode.value_()
        d_flags = int(dentry.d_flags)
        # d_lockref.count (>=3.12), d_count (older)
        try:
            refcount = int(dentry.d_lockref.count)
        except AttributeError:
            try:
                refcount = int(dentry.d_count.counter)
            except AttributeError:
                refcount = -1
        sb_addr = dentry.d_sb.value_()
        try:
            fstype = dentry.d_sb.s_type.name.string_().decode(errors="replace")
        except FaultError:
            fstype = "<unknown>"
    except FaultError as e:
        print(f"Error reading dentry: {e}", file=sys.stderr)
        return

    print(f"Dentry for: {path}")
    print(f"  address:    0x{addr:x}")
    print(f"  name:       {name}")
    print(f"  parent:     0x{parent_addr:x} ({parent_name})")
    print(f"  inode:      0x{inode_addr:x}")
    print(f"  d_flags:    0x{d_flags:08x}")
    print(f"  refcount:   {refcount}")
    print(f"  sb:         0x{sb_addr:x} ({fstype})")


def main():
    parser = make_base_parser("drgn-based lsof: list mount points and open files")
    args = parser.parse_args()

    mounts = get_all_mounts(prog)

    if args.mount_points:
        print_mount_points(mounts)
        return

    # --show-file, --show-inode, --show-dentry modes (can be combined)
    if args.show_file or args.show_inode or args.show_dentry:
        if not args.path:
            print("Error: --show-file/--show-inode/--show-dentry require a file path",
                  file=sys.stderr)
            sys.exit(1)
        result = find_open_file(prog, args.path)
        if result is None:
            print(f"Error: file '{args.path}' isn't opened",
                  file=sys.stderr)
            sys.exit(1)
        file_obj, openers = result
        first = True
        if args.show_file:
            if not first:
                print()
            first = False
            print_file_info(args.path, file_obj, openers)
        if args.show_inode:
            if not first:
                print()
            first = False
            print_inode_info(args.path, file_obj)
        if args.show_dentry:
            if not first:
                print()
            first = False
            print_dentry_info(args.path, file_obj)
        return

    # Build mount index for vfsmount pointer matching
    vfsmount_index = build_vfsmount_index(mounts)

    if args.mnt:
        # Validate that --mnt is an exact mount root
        valid_dsts = {m["dst"] for m in mounts}
        if args.mnt not in valid_dsts:
            print(f"Error: '{args.mnt}' is not a mount point.",
                  file=sys.stderr)
            print("Valid mount points:", file=sys.stderr)
            for m in mounts:
                print(f"  {m['dst']}", file=sys.stderr)
            sys.exit(1)

    all_files = get_open_files(prog, vfsmount_index)

    if args.mnt:
        target = next(m for m in mounts if m["dst"] == args.mnt)
        filtered = [f for f in all_files if f["mount_dst"] == args.mnt]
        print(f"Open files on {args.mnt} ({target['fstype']})")
        headers = ["PID", "USER", "FD", "TYPE", "COMMAND", "PATH"]
        rows = [(f["pid"], f["uid"], f["fd"], f["type"], f["comm"], f["path"])
                for f in filtered]
        rows.sort(key=lambda r: (r[0], r[2]))
        print_table(headers, rows)
        return

    # No arguments: all open files grouped by mount
    by_mount = {}
    for f in all_files:
        by_mount.setdefault(f["mount_dst"], []).append(f)

    for m in mounts:
        files = by_mount.get(m["dst"], [])
        if not files:
            continue
        print_files_for_mount(m["dst"], m["fstype"], files)


if __name__ == "__main__":
    main()
