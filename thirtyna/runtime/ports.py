"""Private Port Agent. A bound socket is the lease, transferred via SCM_RIGHTS."""
import errno
import json
import os
import socket


def serve(channel):
    with channel:
        while message := channel.recv(256):
            preferred = int(message)
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                collision = None
                try:
                    listener.bind(("127.0.0.1", preferred))
                except OSError as exc:
                    if exc.errno != errno.EADDRINUSE or not preferred:
                        raise
                    collision = preferred
                    listener.bind(("127.0.0.1", 0))
                listener.listen()
                info = dict(pid=os.getpid(), port=listener.getsockname()[1],
                            collision=collision)
                socket.send_fds(channel, [json.dumps(info).encode()], [listener.fileno()])
