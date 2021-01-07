from .curios import run, tcp_server, spawn, run_in_thread
from .curios import ssl
from .curios import io as cuio
from .curios import socket as cusock
from sys import stderr

__all__ = ["ASProtocol", "ASSock", "get_recomended_tls_settings", "ASProtocolHandler"]

def get_recomended_tls_settings(protocol) -> ssl.SSLContext:
    ssl_ctx = ssl.SSLContext(protocol)
    ssl_ctx.options |= (
        ssl.OP_NO_TICKET| # pylint: disable=maybe-no-member
        ssl.OP_NO_TLSv1|
        ssl.OP_NO_TLSv1_1|
        ssl.OP_NO_RENEGOTIATION # pylint: disable=maybe-no-member
    )
    ssl_ctx.options &= ~ssl.OP_CIPHER_SERVER_PREFERENCE
    ssl_ctx.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384')
    return ssl_ctx

async def __echo_client(client, addr):
    print('Connection from', addr)
    if client.secure:
        try:
            await client.do_handshake()
        except Exception:
            return
    while True:
        data = await client.recv(1000)
        if not data:
            break
        await client.sendall(data)
    print('Connection closed')

class SockStream(cuio.SocketStream):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream_closed = False
    
    async def close(self):
        await super().close()
        self.stream_closed = True

class ASSock():
    def __init__(self, conn: cuio.Socket, addr: tuple):
        self.__conn = conn
        self.__rw = SockStream(conn)
        self.addr = addr
        self.end = False

    def get_tls_info(self) -> cuio.SSLInfo: 
        return self.__conn.get_ssl_info()

    def is_closed(self) -> bool:
        return self.__rw.stream_closed

    def _get_rw(self) -> cuio.SocketStream:
        return self.__rw

    def _get_conn(self) -> cuio.Socket:
        return self.__conn

    def __getattr__(self, key):
        return getattr(self.__rw, key)


class ASProtocol():
    async def serve(self, client, addr):
        self.__session = ASSock(client, addr)
        e = None

        try:
            try:
                await self.connection(self.__session)
            except ConnectionError:
                await self.end_of_file()
                raise

            while not self.__session.is_closed():
                chunk = await self.__session.read(256*1024) 
                if not chunk:
                    await self.end_of_file()
                    break

                await self.data_read(chunk)

        except ConnectionError:
            pass
        except Exception as err:
            e = err
            import traceback;
            print("Error handling the connection:", file=stderr)
            traceback.print_exc()

        if not self.__session.is_closed():
            await self.__session.close()
                
        await self.disconnection(e)
            
    async def connection(self, conn):
        pass

    async def end_of_file(self):
        pass

    async def data_read(self, data):
        pass

    async def disconnection(self, exc):
        pass
    
class __ASEchoProtocol(ASProtocol):
    async def connection(self, conn):
        self.transport = conn
    async def data_read(self, data):
        await self.transport.write(data)
    async def end_of_file(self):
        print("eof")

class __ASRandomProtocol(ASProtocol):
    async def connection(self, conn: ASSock):
        await conn._get_conn().sendfile(open("/dev/urandom", "rb"))
    async def disconnection(self, exc):
        print(exc)

'''
class AIOProtocolBridge(ASProtocol):
    async def connection(self, conn):
        await run_in_thread(self.connection_made, conn)

    def connection_made(self, conn):
        pass

    async def end_of_file(self):
        await run_in_thread(self.eof_received)

    def eof_received(self):
        pass

    async def data_read(self, data):
        await run_in_thread(self.data_received, data)

    def data_received(self, data):
        pass

    async def disconnection(self, exc):
        await run_in_thread(self.connection_lost, exc)

    def connection_lost(self, exc):
        pass

class __EchoServerProtocol(AIOProtocolBridge):
    def connection_made(self, transport):
        peername = transport.addr
        print('Connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        message = data.decode()
        print('Data received: {!r}'.format(message))

        print('Send: {!r}'.format(message))
        self.transport.write(data)

        print('Close the client socket')
        self.transport.close()
'''        

class ASProtocolHandler():
    def __init__(self,proto):
        self.__protocol = proto
    async def serve(self,conn,addr):
        if conn.secure:
            try:
                await conn.do_handshake()
            except Exception:
                return
        await self.__protocol().serve(conn,addr)

if __name__ == '__main__':
    ssl_ctx = get_recomended_tls_settings(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain("aslib/test/selfsigned.pem", "aslib/test/selfsigned_key.pem")
    run(tcp_server ("", 8055, ASProtocolHandler(__ASEchoProtocol).serve, ssl=ssl_ctx))