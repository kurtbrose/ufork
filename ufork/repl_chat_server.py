import select
import code
import traceback
import weakref


class ReplChatServer(object):
    def __init__(self, sock, env):
        self.sock = sock
        self.connected = []
        self.connected_bufs = weakref.WeakKeyDictionary()
        env["self"] = self
        self.env = env
        self.console = code.InteractiveInterpreter(env)
        self.sofar = ""

    def run(self):
        while 1:
            rd, _, _ = select.select([self.sock]+self.connected, [], [], 1)
            if not rd:  # timeout
                continue
            if rd[0] is self.sock:
                self.connected.append(self.sock.accept()[0])
                self.connected[-1].sendall("Connected to ReplServer...\n\r>> ")
            else:  # only process commands from one socket at a time
                sock = rd[0]
                inp = sock.recv(4096)
                self.connected_bufs.setdefault(sock, "")
                self.connected_bufs[sock] += inp
                data = self.connected_bufs[sock]
                if data.endswith("\n"):
                    peer = sock.getpeername()
                    outp = repr(peer) + ">> " + data  # cut off trailing \n
                    cmd = None
                    try:
                        cmd = code.compile_command(inp, repr(peer), 'eval')
                        self.sofar = ""
                    except SyntaxError as e:
                        pass
                    except (OverflowError, ValueError) as e:
                        pass
                    if cmd:
                        try:
                            outp += repr(eval(cmd, self.env))
                        except Exception:
                            outp += traceback.format_exc().replace('\n', '\n\r')
                    else:  # incomplete command
                        self.sofar += inp
                    if self.sofar:
                        outp += '\n\r... '
                    else:
                        outp += '\n\r>>> '
                    for client in self.connected:
                        client.sendall(outp)
                    print outp+"\n"
            if len(rd) > 1:
                for s in rd[1:]:
                    pass  # TODO: get data, report rejected commands
