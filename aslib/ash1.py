from .assock import *
import h11
from multidict import CIMultiDict
from io import BytesIO
from .ashttp_codes import HTTPStatus
from urllib.parse import parse_qs
from werkzeug import routing, exceptions as wkex
from typing import Iterable, Coroutine, Generator, Iterable, AsyncIterable, AsyncGenerator, AsyncIterator, Iterator
from io import IOBase
from .curios import run_in_thread, CancelledError
from .ashttputils import *
import wsproto

class HTTPServer(ASProtocol):
    def __init__(self):
        self.conn = None
        self.hconn = h11.Connection(h11.SERVER)
        self.hdata = _HTTP_REQUEST(_HTTP_PLACEHOLDER, BytesIO())
        self.__vers = ""

    async def connection(self, conn: ASSock):
        self.conn = conn
        self.hdata.header["ip"] = conn.addr[0]

    async def start_http(self, status: int, headers: dict={}, reason=None):
        outh = []
        for x in headers:
            outh.append((str(x),str(headers[x])))
        await self.conn.write(self.hconn.send(h11.Response(status_code=status, headers=_get_headers()+outh, reason=reason if reason != None else HTTPStatus(status).phrase)).replace(b"HTTP/1.1 ",f"HTTP/{self.__vers} ".encode("ascii"), 1))

    async def send_informational(self, status: int, headers: dict={}):
        outh = []
        for x in headers:
            outh.append((str(x),str(headers[x])))
        await self.conn.write(self.hconn.send(h11.InformationalResponse(status_code=status, headers=_get_headers()+outh, reason=HTTPStatus(status).phrase)))

    async def write_data(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif isinstance(data, bytearray):
            data = bytes(data)
        elif not isinstance(data, bytes):
            data = str(data).encode("utf-8")

        await self.conn.write(self.hconn.send(h11.Data(data=data)))
    
    async def fin_http(self):
        await self.conn.write(self.hconn.send(h11.EndOfMessage()))

    async def error_handler(self, exc):
        if self.hconn.our_state in {h11.IDLE, h11.SEND_RESPONSE}:
            try:
                if isinstance(exc, h11.ProtocolError):
                    await self.start_http(exc.error_status_hint, {"Content-Length": 0})
                else:
                    print("Error executing request:")
                    import traceback
                    traceback.print_exc()
                    await self.start_http(500, {"Content-Length": 0})

                await self.fin_http()
            except Exception as e:
                pass
        else:
            pass
            #print("Unexpected state:",self.hconn.our_state)

    async def handle_request(self):
        raise NotImplementedError()

    async def data_read(self, data):
        if self.hconn.they_are_waiting_for_100_continue:
            await self.send_informational(100)
        self.hconn.receive_data(data)
        while True:
            try:
                event = self.hconn.next_event()
                if isinstance(event, h11.NEED_DATA):
                    return
                elif isinstance(event, h11.Request):
                    if event.http_version.decode("utf-8") not in ["1.0", "1.1"]:
                        raise h11.RemoteProtocolError("Unknown HTTP version", 505)

                    self.__vers = event.http_version.decode("utf-8")

                    if not event.method.decode("utf-8").isupper():
                        raise h11.RemoteProtocolError("HTTP method must be uppercase")

                    if event.method.decode("utf-8") not in  _KNOWN_METHODS:
                        raise h11.RemoteProtocolError("Bad method", 501)

                    self.hdata.header["method"] = event.method.decode("utf-8")

                    if len(event.target) > 8192:
                        raise h11.RemoteProtocolError("URL too long", 414)

                    self.hdata.header["path"] = event.target.decode("utf-8").split("?", 1)[0]

                    if len(event.target.decode("utf-8").split("?", 1)) > 1:
                        self.hdata.header["query"] = CIMultiDict( (k, v if len(v)>1 else v[0] ) 
                            for k, v in parse_qs(event.target.decode("utf-8").split("?", 1)[1]).items() )

                    for x,y in event.headers:
                        if len(x) > 8192 or len(y) > 8192:
                            raise h11.RemoteProtocolError("Header too long", 431)

                    self.hdata.header["headers"] = CIMultiDict((x.decode("utf-8"), y.decode("utf-8")) for x,y in event.headers)
                    
                    if "content-length" not in self.hdata.header["headers"] and self.hdata.header["method"] in ["POST", "PUT"]:
                        raise h11.RemoteProtocolError("No content length set", 411)
                elif isinstance(event, h11.Data):
                    if self.hdata.body.tell() > pow(2,32):
                        raise h11.RemoteProtocolError("Data too large", 413)
                    
                    self.hdata.body.write(event.data)

                elif isinstance(event, h11.EndOfMessage):
                    await self.handle_request()
                    break

                elif isinstance(event, h11.ConnectionClosed):
                    raise CancelledError()

            except CancelledError:
                try:
                    await self.sock.close()
                except:
                    pass
                return

            except Exception as e:
                await self.error_handler(e)
                break

        if isinstance(self.hconn.our_state, h11.MUST_CLOSE):
            await self.conn.close()
            return
        else:
            try:
                self.hconn.start_next_cycle()
            except h11.ProtocolError:
                #print("unexpected http state:",self.hconn.our_state)
                await self.conn.close()
                return

    async def disconnection(self, exc):
        self.hconn.receive_data(b"")
        
class __HTTPHello(HTTPServer):
    async def handle_request(self):
        await self.start_http(200)
        await self.write_data("Hello!\n")
        await self.fin_http()

class _HTTPHandler(HTTPServer):
    def __init__(self, handler):
        super().__init__()
        self.handler = handler
    async def handle_request(self):
        resp = await self.handler(self)

        if isinstance(resp, tuple):
            headers = {}
            status = resp[0]
            hasLength = False
            data = resp[1]
            if isinstance(data, Coroutine):
                data = await data
            if len(resp) >= 3:
                headers = CIMultiDict(resp[2])
                if "content-length" in headers:
                    hasLength = True
            if (isinstance(data, bytes) or isinstance(data,bytearray) or isinstance(data,str)) and not hasLength:
                hasLength = True
                headers["Content-Length"] = len(data)
                
            await self.start_http(status, headers)

            if self.hdata.header["method"] != "HEAD":
                if isinstance(data, bytes) or isinstance(data,bytearray) or isinstance(data,str):
                    await self.write_data(data)
                elif isinstance(data, IOBase):
                    with data:
                        while True:
                            chunk = await run_in_thread(data.read, 8192)
                            if not chunk:
                                break
                            await self.write_data(chunk)
                elif isinstance(data, Iterable) or isinstance(data, Generator) or isinstance(data, Iterator):
                    for chunk in data:
                        await self.write_data(chunk)
                elif isinstance(data, AsyncIterable) or isinstance(data, AsyncGenerator) or isinstance(data, AsyncIterator):
                    async for chunk in data:
                        await self.write_data(chunk)
                    
            await self.fin_http()
        elif isinstance(resp, None):
            return
        else:
            raise Exception("Unknown response type")



class WSHandler():
    def __init__(self, conn: HTTPServer, request: _HTTP_REQUEST):
        self.conn = wsproto.Connection(wsproto.ConnectionType.SERVER, [wsproto.extensions.PerMessageDeflate()])
        self.__ctx = conn
        self.request = request
        self._accepted = False
        self.closed = False

    async def accept(self, protocols=[], default_protocol=None):
        if protocols and default_protocol and default_protocol not in protocols:
            raise Exception("Default protocol must be in protocols")

        if "sec-websocket-protocol" in self.__ctx.hdata.header["headers"]:
            protocol = self.__ctx.hdata.header["headers"]["sec-websocket-protocol"]
        else:
            if protocols and default_protocol:
                protocol = default_protocol
            else:
                protocol = None

        selProto = None

        if protocols:
            for proto in protocol.split(", "):
                if proto in protocols:
                    selProto = proto
                    break

        if protocols and selProto == None:
            raise wkex.BadRequest("Unknown WebSocket Protocol")

        protocolSwitch = {"Connection": "Upgrade","Upgrade":"websocket"}

        if "sec-websocket-key" in self.__ctx.hdata.header["headers"]:
            protocolSwitch["Sec-Websocket-Accept"] = wsproto.utilities.generate_accept_token(self.__ctx.hdata.header["headers"]["sec-websocket-key"].encode("ascii")).decode("utf-8")

        if selProto:
            protocolSwitch["Sec-Websocket-Protocol"] = selProto

        await self.__ctx.send_informational(101, protocolSwitch)
        self._accepted = True
        return protocol
    
    async def read(self):
        if not self._accepted:
            await self.accept()
        resData = None
        while resData == None:
            s = await self.__ctx.conn.read(256*1024)
            if not s:
                raise CancelledError()
            self.conn.receive_data(s)
            for e in self.conn.events():
                if isinstance(e, wsproto.events.BytesMessage):
                    if resData == None:
                        resData = bytearray(e.data)
                    else:
                        resData += e.data
                elif isinstance(e, wsproto.events.TextMessage):
                    if resData == None:
                        resData = e.data
                    else:
                        resData += e.data      
                elif isinstance(e, wsproto.events.Ping):
                    await self.__ctx.conn.write(self.conn.send(e.response()))
                elif isinstance(e, wsproto.events.CloseConnection):
                    await self.__ctx.conn.write(self.conn.send(e.response()))
                    raise CancelledError()

        return resData

    async def write(self, data):
        if not self._accepted:
            await self.accept()
        await self.__ctx.conn.write(self.conn.send(wsproto.events.Message(data)))

    async def close(self, code=wsproto.connection.CloseReason.NORMAL_CLOSURE, reason=None):
        if not self._accepted:
            raise Exception("Websocket connection was closed before accepting")

        await self.__ctx.conn.write(self.conn.send(wsproto.events.CloseConnection(code, reason)))
        self.closed = True
        raise CancelledError()

    

class RoutesHandler():
    def __init__(self):
        self.routes = routing.Map()

    def add_route(self, route, method=["GET"], ws=False):
        def decorator(f):
            self.routes.add(routing.Rule(route, endpoint=f, methods=method, websocket=ws))
            return f
        return decorator

    async def serve(self, ctx: HTTPServer):
        scheme = "http"
        isWs = False
        if ctx.conn._underlying_socket.secure:
            scheme = "https"

        ctx.hdata.header["scheme"] = scheme
        
        if (
            ctx.hdata.header["headers"].get("connection") == "Upgrade"
            and ctx.hdata.header["headers"].get("upgrade") == "websocket" 
            and ctx.hdata.header["headers"].get("sec-websocket-version") == "13" 
        ):
            scheme = "ws"
            ctx.hdata.header["protocol"] = "websocket"
            isWs = True
            if ctx.conn._underlying_socket.secure:
                scheme = "wss"

        rt: routing.MapAdapter = self.routes.bind(ctx.hdata.header["headers"]["host"], url_scheme=scheme)
        try:
            handler = rt.match(ctx.hdata.header["path"], method=ctx.hdata.header["method"])
        except routing.RequestRedirect as e:
            return 301, "", {"Location": e.new_url}
        except routing.WebsocketMismatch:
            return 426 if not isWs else 400, ""
        except routing.HTTPException as e:
            return e.code, ""
        
        try:
            hdt = _HTTP_REQUEST(AttrDict(ctx.hdata.header), ctx.hdata.body)
            if hdt.header.query:
                hdt.header.query = AttrDict(hdt.header.query)
            hdt.header.headers = AttrDict(hdt.header.headers)

            if isWs:
                wsCtx = WSHandler(ctx, hdt)
                s = await handler[0](wsCtx, **handler[1])
                if wsCtx._accepted and not wsCtx.closed:
                    wsCtx.close()
                return s

            else:
                return await handler[0](hdt, **handler[1])
        except routing.HTTPException as e:
            return e.code, ""

def http_router(s: RoutesHandler) -> ASProtocol: 
    return lambda: _HTTPHandler(s.serve)
 

if __name__ == "__main__":
    route = RoutesHandler()

    @route.add_route("/")
    async def hello(request):
        return 200, "Hello!\n"

    @route.add_route("/error")
    async def error(request):
        raise Exception("error")

    @route.add_route("/ip")
    async def ip(request):
        return 200, request.header.ip+"\n"

    @route.add_route("/echo", ws=True)
    async def ws(ws):
        while True:
            await ws.write(await ws.read())

    from .curios import run, tcp_server
    run(tcp_server ("", 8855, ASProtocolHandler(http_router(route)).serve))