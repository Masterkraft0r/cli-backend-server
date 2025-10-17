#!/usr/bin/env python

import asyncio
import collections.abc as cabc
import inspect
import os
import pathlib as p
import struct
import sys
import typing as t

SyncCommandHandler = t.Callable[[list[str]], int]
AsyncCommandHandler = t.Callable[[list[str]], cabc.Coroutine[t.Any, t.Any, int]]
CommandHandler = SyncCommandHandler | AsyncCommandHandler


class Server:
    def __init__(self, program_name: str, command_handler: CommandHandler, base_path: p.Path | None = None):
        base_path = base_path if base_path else p.Path(f"{os.environ['HOME']}", ".cache", program_name)
        base_path.mkdir(parents=True, exist_ok=True)

        self.program_name: str = program_name
        self.pid_file_path: p.Path = base_path / f"{program_name}.pid"
        self.socket_file_path: p.Path = base_path / f"{program_name}.socket"
        self.writer: asyncio.StreamWriter | None = None
        self.command_handler: CommandHandler = command_handler
        self.server: asyncio.Server | None = None

        # if pid file already exists, check if server is really running, if not just overwrite the file
        if self.pid_file_path.exists() and not self.pid_file_path.is_file():
            raise RuntimeError("PID file path exists but is not a file.")
        elif self.pid_file_path.is_file():
            with self.pid_file_path.open() as f:
                pid = int(f.read().strip(" \n"))

            if pid != 0:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    # process doesn't exist; nothing to do
                    pass
                except PermissionError:
                    raise RuntimeError("Server is already running.")

        with self.pid_file_path.open("w") as f:
            _ = f.write(str(os.getpid()))

    async def serve(self) -> None:
        print("Starting server...")
        loop = asyncio.get_event_loop()
        self.server = await asyncio.start_unix_server(self._handle_connection, self.socket_file_path)
        loop.add_signal_handler(2, self._handle_sigint)

        async with self.server:
            try:
                await self.server.serve_forever()
            except asyncio.exceptions.CancelledError:
                pass

        print("Clean up...")
        os.remove(self.pid_file_path)

    async def _close_server(self):
        print("Closing server...")
        if self.server is None:
            return

        self.server.close()
        await self.server.wait_closed()

    async def _close_connection(self):
        if self.writer is None:
            return

        self.writer.close()
        await self.writer.wait_closed()
        self.writer = None

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writer = writer

        quit = False
        status = 0
        try:
            args = (await reader.readuntil()).decode().rstrip(" \n\0").split("\0")
            if args == ["quit"]:
                quit = True
            else:
                try:
                    # save references to real stdout and stderr
                    old_stdout = sys.stdout
                    old_stderr = sys.stderr

                    # redirect stdout and stderr temporarily
                    # TODO: prefix messages for stdout and stderr so client can differentiate between the two
                    sys.stdout = self.writer
                    sys.stderr = self.writer

                    # run command handler
                    result = self.command_handler(args)
                    if inspect.isawaitable(result):
                        status = await result
                    else:
                        status = result

                    # restore stdout and stderr
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                except Exception as err:
                    self.writer.write(("Error: " + str(err)[1:-1].rstrip(" \n\0")).encode())
                    status = 1

        except:
            pass

        self.writer.write(struct.pack("<bc", status, "\0"))
        await self.writer.drain()

        await self._close_connection()

        if quit:
            await self._close_server()

    async def _handle_sigint(self):
        await self._close_connection()
        await self._close_server()
