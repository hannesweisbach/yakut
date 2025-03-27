from dataclasses import dataclass, field
import math
import pathlib
import sys
import typing as t

from pycyphal.application.file import FileClient2

import yakut
from yakut.param.formatter import FormatterHints

@dataclass(frozen=True)
class FSEntry:
    path: pathlib.Path
    size: int
    mtime: int
    type: str
    access: str

    children: list[t.Self] = field(default_factory=list)

    @staticmethod
    def make(name: pathlib.Path, info: "uavcan.file.GetInfo_0_2.Response", children=list[t.Self]) -> t.Self:
        type_ = ("d", "f", "ld", "lf")
        type_idx = info.is_file_not_directory + info.is_link * 2
        access = ("", "r", "w", "rw")
        access_idx = info.is_readable + info.is_writeable * 2
        return FSEntry(
            name, info.size, info.unix_timestamp_of_last_modification, type_[type_idx], access[access_idx], children
        )

    def long_format(self, size_digits: int) -> str:
        return f"{self.type:>2s} {self.access:>2s} {len(self.children)} {self.size:{size_digits}d} {self.path.name}"


async def _fs_iterate(fc: FileClient2, path: pathlib.Path, depth: int) -> FSEntry:
    if depth == 0:
        children = []
    else:
        children = list([await _fs_iterate(fc, path / child, depth - 1) async for child in fc.list(str(path))])
    info = await fc.get_info(str(path))
    fse = FSEntry.make(path, info, children)

    return fse

async def do_ls(purser: yakut.Purser, fc: FileClient2, path: str, long: bool) -> None:
    fse = await _fs_iterate(fc, pathlib.Path(path), 2)

    if not long:
        names = [c.path.name for c in fse.children]
        formatter = purser.make_formatter(FormatterHints(single_document=True))
        sys.stdout.write(formatter(names))
        sys.stdout.flush()
    else:
        size_digits = math.ceil(math.log(max([fse.size for fse in fse.children]), 10))
        for c in fse.children:
            print(c.long_format(size_digits))

async def do_tree(purser: yakut.Purser, fc, path: str, long: bool) -> None:
    # TODO: use formatter?
    def pfse(fses: list[FSEntry], prefix: str = ""):
        for c in fses[:-1]:
            print(f"{prefix}├── {c.path.name}")
            indent = "   " if "f" in c.type else "│   "
            pfse(c.children, prefix + indent)
        for c in fses[-1:]:
            print(f"{prefix}└── {c.path.name}")
            indent = "   " if "f" in c.type else "    "
            pfse(c.children, prefix + indent)

    root = await _fs_iterate(fc, pathlib.Path(path), -1)
    print(root.path)
    pfse(root.children)