import contextlib
from dataclasses import dataclass
import json
import pathlib
import pytest
import random
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


class FileClient:
    def __init__(self, node_id: int | str, env: dict[str, str]) -> None:
        self._fs_node_id = f"{node_id}"
        self._env = env

    def __call__(self, cmd: str, *args: str, input: str | None = None) -> tuple[int, str, str]:
        return execute_cli("fclnt", cmd, f"{self._fs_node_id}", *args, input=input, environment_variables=self._env)


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


@pytest.mark.asyncio
async def _unittest_cat(transport_factory: TransportFactory, fileserver_factory: FileServerFactory):
    fs_node_id = 11
    environment_variables = {
        **transport_factory(100).environment,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }
    size = random.randint(10, 4096)
    contents = random.randbytes(size).decode("utf-8", errors="ignore")
    with fileserver_factory(fs_node_id, transport_factory) as fs:
        fc = FileClient(fs_node_id, environment_variables)
        testfile = RemoteFilePath("/path/to/file", fs.root)

        #exitcode, *_ = fc("cat", "/file/does/not/exist")
        #assert exitcode != 0

        exitcode, *_ = fc("cat", testfile.path, input=contents)
        assert exitcode == 0


        exitcode, readback, _ = fc("cat", testfile.path)
        assert exitcode == 0

        #assert readback == contents

@pytest.mark.asyncio
async def _unittest_ls(transport_factory: TransportFactory, fileserver_factory: FileServerFactory):
    fs_node_id = 11
    environment_variables = {
        **transport_factory(100).environment,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }

    with fileserver_factory(fs_node_id, transport_factory) as fs:
        fc = FileClient(fs_node_id, environment_variables)

        # read / by default, if no path given
        exitcode, readback, _ = fc("ls")
        assert exitcode == 0
        filelist = json.loads(readback)
        # maybe not a good idea?
        assert isinstance(filelist, list)
        assert len(filelist) == 0

        testfile = RemoteFilePath("/path/to/file", fs.root)
        testfile.fs_path.touch()

        exitcode, readback, _ = fc("ls")
        assert exitcode == 0
        filelist = json.loads(readback)
        # maybe not a good idea?
        assert isinstance(filelist, list)
        assert len(filelist) == 1
        assert testfile.path in filelist

@pytest.mark.asyncio
async def _unittest_tree(transport_factory: TransportFactory, fileserver_factory: FileServerFactory):
    fs_node_id = 11
    environment_variables = {
        **transport_factory(100).environment,
        "YAKUT_PATH": str(OUTPUT_DIR),
    }

    with fileserver_factory(fs_node_id, transport_factory) as fs:
        fc = FileClient(fs_node_id, environment_variables)

        # read / by default, if no path given
        exitcode, readback, _ = fc("tree")
        assert exitcode == 0

# TODO:
# ls
# rcpy