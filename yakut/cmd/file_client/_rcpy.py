import contextlib
import pathlib

import click

from pycyphal.application.file import FileClient2, RemoteFileNotFoundError

import yakut

class CyphalFile:
    def __init__(self, fc: FileClient2, path: str, mode: str):
        self._fc  = fc
        self._path = path
        self._offset = 0
        self._mode = mode
        self.chunksize = self._fc.data_transfer_capacity

    async def __aenter__(self):
        try:
            _ = await self._fc.get_info(self._path)
        except RemoteFileNotFoundError:
            if "w" in self._mode:
                await self._fc.touch(self._path)

    async def __aexit__(self):
        await self._fc.write(self._path, b"", self._offset, truncate=False)

    async def write(self, data: bytes):
        await self._fc.write(self._path, data, self._offset, truncate=False)
        self._offset += len(data)

    async def read(self, size: int) -> bytes:
        data = await self._fc.read(self._path, self._offset, size)
        self._offset = len(data)
        return data


@contextlib.asynccontextmanager
async def parse_uri(uri: str, mode: str):
    if uri.startswith("cf://"):
        ctx = click.get_current_context()
        purser = ctx.find_object(yakut.Purser)
        node_id, path = uri.removeprefix("cf://").split("/", maxsplit=1)
        path = path if path.startswith("/") else f"/{path}"
        node_id = int(node_id, 0)
        print(f"node-id: {node_id}")
        with purser.get_node("file client", allow_anonymous=False) as node:
            fc = FileClient2(node, node_id)
            yield CyphalFile(fc, path, mode)

    else:
        yield pathlib.Path(uri).open(mode)


async def rcopy(src: str, dst: str) -> None:
    async with parse_uri(src, "rb") as src_fp, parse_uri(dst, "wb+") as dst_fp:
        src_cs = getattr(src_fp, "chunksize", 65535)
        dst_cs = getattr(dst_fp, "chunksize", 65535)
        chunksize = min(src_cs, dst_cs)
        while chunk := await src_fp.read(chunksize):
            await dst_fp.write(chunk)
