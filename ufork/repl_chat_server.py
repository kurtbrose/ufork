import socket
import select
import code
import traceback
import weakref


MODE_RAW = "raw"  # raw TCP mode
MODE_SSH = "ssh"


class ReplChatServer(object):
    def __init__(self, sock_or_addr=("127.0.0.1", 9898), env=None, mode="raw"):
        if hasattr(sock_or_addr, "accept"):
            self.sock = sock_or_addr
        else:
            self.sock = socket.socket()
            self.sock.bind(sock_or_addr)
            self.sock.listen(128)
        self.connected = []
        self.connected_bufs = weakref.WeakKeyDictionary()
        if env is None:
            env = {}
        env["self"] = self
        env["disconnect"] = self.disconnect
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
                self.connected[-1].sendall("Connected to ReplServer...\r\n>> ")
            else:  # only process commands from one socket at a time
                sock = rd[0]
                inp = sock.recv(4096)
                if inp == "":  # client has closed connection
                    self.connected = [e for e in self.connected if e is not sock]
                    continue
                self._handle_input(sock, inp)
            if len(rd) > 1:
                for s in rd[1:]:
                    pass  # TODO: get data, report rejected commands

    def _handle_input(self, sock, inp):
        self.cur_client = sock
        self.connected_bufs.setdefault(sock, "")
        self.connected_bufs[sock] += inp
        data = self.connected_bufs[sock]
        if data.endswith("\n"):
            self.connected_bufs[sock] = ""
            self._handle_line(sock, data)

    def _handle_line(self, sock, line):
        peer = sock.getpeername()
        outp = repr(peer) + ">> " + line
        cmd = None
        try:
            cmd = code.compile_command(line, repr(peer), 'eval')
            self.sofar = ""
        except SyntaxError as e:
            outp += repr(e)
            self.sofar = ""
        except (OverflowError, ValueError) as e:
            outp += repr(e)
            self.sofar = ""
        if cmd:
            try:
                outp += repr(eval(cmd, self.env))
            except Exception:
                outp += traceback.format_exc().replace('\n', '\r\n')
        else:  
            # incomplete command
            #self.sofar += line
            pass
        if self.sofar:
            outp += '\r\n... '
        else:
            outp += '\r\n>>> '
        for client in self.connected:
            client.sendall(outp)

        print repr(outp)

    def disconnect(self):
        self.cur_client.close()

if __name__ == "__main__":
    rcs = ReplChatServer()
    rcs.run()
