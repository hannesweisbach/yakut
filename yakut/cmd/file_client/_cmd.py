import contextlib
import functools
import pathlib
import typing as t
import sys

import click

import pycyphal
import pycyphal.application
import pycyphal.application.file
from pycyphal.application.file import FileClient2

import yakut

from yakut.main import AliasedGroup
from yakut.ui import show_error
from yakut.util import EXIT_CODE_UNSUCCESSFUL

from . import _ls
from . import _rcpy


def pass_file_client(f):
    print(f"_file_client: f={f}")

    @functools.wraps(f)
    async def impl(*args, **kwargs) -> t.Awaitable[t.Any]:
        ctx = click.get_current_context()
        print(f"params: {ctx.params}")
        purser = ctx.find_object(yakut.Purser)
        node_id = kwargs.pop("node_id")
        print(f"node-id: {node_id}")
        with purser.get_node("file client", allow_anonymous=False) as node:
            try:
                fc = pycyphal.application.file.FileClient2(node, node_id)
                ret = await f(fc, *args, **kwargs)
                return 0 if ret is None else ret
            except pycyphal.application.file.FileTimeoutError:
                show_error(f"File server not reachable at node {node_id}")
            except pycyphal.application.file.RemoteFileError as e:
                show_error(f"{e}")
        return EXIT_CODE_UNSUCCESSFUL

    impl = click.argument("NODE-ID", type=int)(impl)
    return impl


@yakut.subcommand(cls=AliasedGroup, aliases=("fclnt", "fc"))
@click.pass_context
def file_client(ctx: click.Context) -> None:
    """Interact with a Cyphal file server as Cyphal file client.

    MODIFY request:

    The touch-semantics of the MODIFY request are described in Section 6.2.3 of
    the Cyphal specification.

    The remove-semantics of the MODIFY request are described in Section 6.2.3 of
    the Cyphal specification.

    The move/copy-semantics of the MODIFY request are described in Section 6.2.3
    of the Cyphal specifcation.

    See Cyphal specification 5.3.7 and 6.2."""
    try:
        import pycyphal
        from pycyphal.application.file import FileClient2
    except ImportError as ex:
        from yakut.cmd.compile import make_usage_suggestion

        raise click.ClickException(make_usage_suggestion(ex.name))


@file_client.command()
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@click.argument("PATH", type=str)
async def touch(fc: FileClient2, path: str) -> None:
    """
    Create the file PATH at the Cyphal file server NODE-ID.

    \b
    The command performs an access to the Cyphal file server at NODE-ID with a
    MODIFY request with touch semantics.

    If the destination already exists, the server updates the target's
    modifaction time. If the destination does not exist, it is creating,
    including intermediate non-existing directories.
    """
    await fc.touch(path)


@file_client.command(aliases="rm")
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@click.option("--force/--no-force", default=False, help="Ignore non-existent file system entries.")
@click.argument("PATH", type=str)
async def remove(fc: FileClient2, path: str, force: bool) -> None:
    """
    Remove the file system entry PATH at Cyphal file server NODE-ID

    \b
    The command performs an access to the Cyphal file server at NODE-ID with a
    MODIFY request with remove semantics.

    If PATH exists, PATH is removed. Unless the --force option is given, the
    command fails if the destination does not exist.
    """
    with contextlib.suppress(pycyphal.application.file.RemoteFileNotFoundError) if force else contextlib.nullcontext():
        await fc.remove(path)


@file_client.command(aliases="mv")
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@click.option("--force/--no-force", default=False, help="Overwrite destination, if it exists.")
@click.argument("SRC", type=str)
@click.argument("DST", type=str)
async def move(fc: FileClient2, src: str, dst: str, force: bool) -> None:
    """
    Move SRC to DST on Cyphal file server NODE-ID.

    \b
    The command performs an access to the Cyphal file server at NODE-ID with a
    MODIFY request with move semantics.

    If DST exists and the --force option is not given, the command fails.
    """
    await fc.move(src, dst, force)


@file_client.command(aliases="cp")
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@click.option("--force/--no-force", default=False, help="Overwrite destination, if it exists.")
@click.argument("SRC", type=str)
@click.argument("DST", type=str)
async def copy(fc: FileClient2, src: str, dst: str, force: bool) -> None:
    """
    Copy SRC to DST on Cyphal file server NODE-ID.

    \b
    The command performs an access to the Cyphal file server at NODE-ID with a
    MODIFY request with copy semantics.

    If DST exists and the --force option is not given, the command fails.
    """
    await fc.copy(src, dst, force)


@file_client.command()
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@click.argument("PATH", type=str)
async def mkdir(fc: FileClient2, path: str) -> None:
    """
    Create directory PATH on Cyphal file server at NODE-ID, including
    intermediary directories.
    \b

    This command is similar to the touch command, but creates a target
    directory, instead of a file. The command does so by creating a temporary
    file PATH/.mkdir and subsequently removing the file PATH/.mkdir, leaving the
    directory PATH on the Cyphal file server.

    Since the command performs two indepentend requests to the target Cyphal
    file server, failure in between commands will cause the temproray
    .mkdir-file to remain on the Cyphal file server.

    If the target directory already exists, the directory is not modified and no
    error is shown. If the target exists but is a file, the command fails.
    """
    with contextlib.suppress(pycyphal.application.file.RemoteFileNotFoundError):
        info = await fc.get_info(path)
        if info.is_file_not_directory:
            return EXIT_CODE_UNSUCCESSFUL + 1
        else:
            return 0
    tmpfile = path + "/.mkdir"
    await fc.touch(tmpfile)
    await fc.remove(tmpfile)


@file_client.command
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@click.argument("PATH", type=str)
async def cat(fc: pycyphal.application.file.FileClient2, path: str) -> None:
    """
    Write stdin to PATH on Cyphal file server at NODE-ID or write PATH on Cyphal
    file server at NODE-ID to stdout.
    \b

    This command is inspired by the commandline tool "cat", but does not quite
    work like it.

    If stdin is a tty, the cat command writes the contents of the file at PATH
    on the Cyphal file server at NODE-ID to stdout. Unless PATH exists and PATH
    is a file, the command fails.

    If stdin is not a tty (i.e. a pipe), the cat command writes input from stdin
    to PATH on the Cyphal file server at NODE-ID. If PATH exists and is a file,
    PATH is overwritten with the new data. If PATH is a directory, the command
    fails. After stdin is exhausted, PATH is truncated to its new length.

    Writing to stdout has precedence over piped-in data.
    """
    if sys.stdin.isatty():
        data = await fc.read(path)
        print(data.decode("utf-8"), end="")
    else:
        await fc.touch(path)
        offset = (await fc.get_info(path)).size
        while chunk := sys.stdin.buffer.read(fc.data_transfer_capacity):
            await fc.write(path, chunk, offset=offset, truncate=False)
            offset += fc.data_transfer_capacity
        await fc.write(path, b"", offset=offset, truncate=False)


@file_client.command()
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@yakut.pass_purser
@click.argument("PATH", default="/")
@click.option("--long", "-l", is_flag=True, default=False, flag_value=True)
async def ls(purser: yakut.Purser, fc: FileClient2, path: str, long: bool) -> None:
    """
    List directory contents or file name.
    \b

    The ls command lists the contents of PATH, if PATH is a directory.

    The long option also prints file type, access controls and file size.
    If the long options is not given, the output is formatted according to the global --format option.

    If PATH is not given, it defaults to /.
    """
    await _ls.do_ls(purser, fc, path, long)


@file_client.command()
@yakut.asynchronous(interrupted_ok=True)
@pass_file_client
@yakut.pass_purser
@click.argument("PATH", default="/")
@click.option("--long", "-l", is_flag=True, default=False, flag_value=True)
async def tree(*args, **kwargs) -> None:
    """
    List contents of directories in a tree-like format.
    \b
    
    The tree command is inspired by the tree command line utility, recursively
    listing directory contents of the Cyphal file server at NODE-ID, starting
    from directory PATH. If not specified, PATH defaults to /.
    """
    await _ls.do_tree(*args, **kwargs)


@file_client.command(aliases=("rcopy","rcp"))
@click.argument("SRC", type=str)
@click.argument("DST", type=str)
@yakut.asynchronous(interrupted_ok=True)
async def remote_copy(src: str, dst: str) -> None:
    """
    Copy a file to/from a Cyphal file server.
    \b

    This command is akin to the scp command and copies a file from SRC to DST.

    The remote-copy command uses the URI scheme cf:// (cyphal file) to specify
    both Cyphal node id of a Cyphal file server and its path. 

    SRC and DST are interpreted as local file path, unless they start with
    cf://. SRC and DST can be an arbitrary combination of local path names and
    cf:// URI schemes. Thus, files can be copied on the local file system as
    well as between two Cyphal nodes with file server services.
    """
    await _rcpy.rcopy(src, dst)