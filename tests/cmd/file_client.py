import contextlib
from dataclasses import dataclass
import pathlib
import pytest
import shutil
import subprocess
import tempfile
import time
import typing as t

import pycyphal.application as pa
from pycyphal.application.file import FileServer

from tests.subprocess import execute_cli, Subprocess
from tests.transport import TransportFactory
from tests.dsdl import OUTPUT_DIR


@dataclass(frozen=True)
class FileServerConfig:
    root: pathlib.Path
    node_id: str


@dataclass(frozen=True)
class RemoteFilePath:
    path: str
    fs_path: pathlib.Path

    def __post_init__(self) -> None:
        # last time modifying the frozen dataclass
        object.__setattr__(self, "fs_path", self.fs_path / self.path[1:])


FileServerFactory = t.Callable[[int, TransportFactory], contextlib.AbstractContextManager[FileServerConfig]]


@pytest.fixture
def fileserver_factory() -> t.Generator[FileServerFactory, None, None]:

    fileservers = []

    @contextlib.contextmanager
    def _fileserver_factory(
        node_id: int, transport_factory: TransportFactory
    ) -> t.Generator[FileServerConfig, None, None]:
        env = transport_factory(node_id).environment

        with tempfile.TemporaryDirectory() as _wd:
            fileservers.append(Subprocess.cli("fsrv", _wd, environment_variables=env))
            # TODO: parse stdout to know when file server is up
            time.sleep(3)
            yield FileServerConfig(pathlib.Path(_wd), f"{node_id}")

    yield _fileserver_factory

    for fileserver in fileservers:
        fileserver.kill()
        fileserver.wait(3)


@pytest.mark.asyncio
async def _unittest_modify2(transport_factory: TransportFactory, fileserver_factory: FileServerFactory) -> None:
    fs_node_id = 11
    with fileserver_factory(fs_node_id, transport_factory) as fs:
        testfile = RemoteFilePath("/foo/bar", fs.root)
        testfile2 = RemoteFilePath("/baz", fs.root)
        environment_variables = {
            **transport_factory(100).environment,
            "YAKUT_PATH": str(OUTPUT_DIR),
        }

        def fclnt(cmd: str, *args: str) -> None:
            execute_cli("fclnt", cmd, f"{fs_node_id}", *args, environment_variables=environment_variables)

        # file server root should be empty
        shutil.rmtree(testfile.fs_path, ignore_errors=True)

        # removing non-existing file fails
        with pytest.raises(subprocess.CalledProcessError) as e:
            fclnt("remove", testfile.path)

        exc = e.value
        assert exc.returncode == 100
        assert testfile.path in exc.stderr
        assert "NOT_FOUND" in exc.stderr

        # create file via touch
        fclnt("touch", testfile.path)
        assert testfile.fs_path.is_file()

        # move file to new file
        fclnt("move", testfile.path, testfile2.path)
        assert testfile2.fs_path.is_file()
        assert not testfile.fs_path.exists()

        # moved file should not be there anymore
        with pytest.raises(subprocess.CalledProcessError) as e:
            fclnt("remove", testfile.path)

        # copy moved file back to original name
        fclnt("copy", testfile2.path, testfile.path)
        assert testfile.fs_path.is_file()
        assert testfile2.fs_path.is_file()

        # remove both files
        fclnt("remove", testfile.path)
        assert not testfile.fs_path.exists()
        fclnt("remove", testfile2.path)
        assert not testfile2.fs_path.exists()


@pytest.mark.asyncio
async def _unittest_mkdir(transport_factory: TransportFactory, fileserver_factory: FileServerFactory):
    fs_node_id = 11
    environment_variables = {
        **transport_factory(100).environment,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }
    with fileserver_factory(fs_node_id, transport_factory) as fs:
        fc = FileClient(fs_node_id, environment_variables)
        testdir = RemoteFilePath("/path/to/directory", fs.root)

        assert not testdir.fs_path.exists()

        fc("mkdir", testdir.path)

        assert testdir.fs_path.is_dir()

