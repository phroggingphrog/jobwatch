from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


class PathEscapeError(OSError):
    def __init__(self, is_symlink: bool) -> None:
        super().__init__()
        self.is_symlink = is_symlink


def read_profile_source(root: Path, name: str, maximum_bytes: int) -> tuple[str, bytes]:
    """Read a primary source, recognizing only cv.md -> master_resume.md.

    The conventional relative alias is identified, never followed. Its canonical
    target is opened separately through the same no-symlink regular-file reader.
    """
    path = Path(root) / name
    try:
        return name, read_regular_file(path, maximum_bytes)
    except PathEscapeError as exc:
        if name != "cv.md" or not exc.is_symlink:
            raise
        try:
            canonical_alias = os.readlink(path) == "master_resume.md"
        except OSError:
            canonical_alias = False
        if not canonical_alias:
            raise
        return "master_resume.md", read_regular_file(Path(root) / "master_resume.md", maximum_bytes)


def read_regular_file(path: Path, maximum_bytes: int) -> bytes:
    """Read one bounded regular file without following any path symlink."""
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, flag) for flag in required):
        raise OSError

    absolute = Path(os.path.abspath(os.fspath(path)))
    components = absolute.parts[1:]
    if not components:
        raise ValueError
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    parent_fd = os.open(os.path.sep, directory_flags)
    try:
        for component in components[:-1]:
            try:
                child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    is_symlink = exc.errno == errno.ELOOP
                    if not is_symlink:
                        try:
                            is_symlink = stat.S_ISLNK(os.stat(component, dir_fd=parent_fd, follow_symlinks=False).st_mode)
                        except OSError:
                            pass
                    raise PathEscapeError(is_symlink) from None
                raise
            os.close(parent_fd)
            parent_fd = child_fd
        try:
            fd = os.open(components[-1], file_flags, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise PathEscapeError(exc.errno == errno.ELOOP) from None
            raise
    finally:
        os.close(parent_fd)

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum_bytes:
            raise ValueError
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum_bytes:
            raise ValueError
        raw.decode("utf-8", "strict")
        return raw
    finally:
        os.close(fd)
