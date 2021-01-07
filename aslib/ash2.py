import mimetypes
import os
import sys

from .curios import Event, socket, ssl, run, run_in_thread, CancelledError, TaskGroup
from urllib.parse import parse_qs

from multidict import CIMultiDict

import h2.config
import h2.connection
import h2.events

from .assock import *
from .ashttputils import *

from io import BytesIO, IOBase

from werkzeug import routing, exceptions as wkex
from typing import Dict as DictType, Iterable, Coroutine, Generator, Iterable, AsyncIterable, AsyncGenerator, AsyncIterator, Iterator

import wsproto

# The maximum amount of a file we'll send in a single DATA frame.
READ_CHUNK_SIZE = 256*1024

_H2_TASKS = TaskGroup()

class H2Server(ASProtocol):
    def __init__(self):
        config = h2.config.H2Configuration(
            client_side=False, header_encoding='utf-8'
        )
        self.conn = h2.connection.H2Connection(config=config)
        self.flow_control_events: DictType[int, Event] = {}
        self.request_data: DictType[int, _HTTP_REQUEST] = {}
        self.has_length: DictType[int, bool] = {}
        self.write_end: DictType[int, bool] = {}
        self.sock = None

    async def connection(self, conn: ASSock):
        self.sock = conn
        self.hdata.header["ip"] = conn.addr[0]
        self.conn.initiate_connection()
        self.conn.local_settings = h2.settings.Settings(
            client=False,
            initial_values={
                h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 255,
                h2.settings.SettingCodes.MAX_HEADER_LIST_SIZE: 2 ** 16,
                h2.settings.SettingCodes.ENABLE_CONNECT_PROTOCOL: 1,
            }
        )
        await self.sock.write(self.conn.data_to_send())

    async def start_http(self, sid: int, status: int, headers: dict={}):
        outh = []
        for x in headers:
            outh.append((str(x).lower(),str(headers[x]).lower
            ()))
        try:
            self.conn.send_headers(sid, [(":status", str(status))] + _get_headers() + outh)
        except (h2.exceptions.StreamClosedError, h2.exceptions.ProtocolError):
            return
        await self.sock.write(self.conn.data_to_send())

    async def write_data(self, sid: int, data, fin: bool=True):
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif isinstance(data, bytearray):
            data = bytes(data)
        elif not isinstance(data, bytes):
            data = str(data).encode("utf-8")

        while True:
            while self.conn.local_flow_control_window(sid) < 1:
                await self.wait_for_flow_control(sid)

            chunk_size = min(
                self.conn.local_flow_control_window(sid),
                65535,
            )

            hasNextData = len(data[chunk_size:]) >= 1

            try:
                if fin:
                    self.conn.send_data(sid, data[:chunk_size], (not hasNextData))
                    self.write_end[sid] = True
                else:
                    self.conn.send_data(sid, data[:chunk_size])
            except (h2.exceptions.StreamClosedError, h2.exceptions.ProtocolError):
                break

            await self.sock.write(self.conn.data_to_send())

            data = data[chunk_size:]

            if not data:
                break

    async def fin_http(self, sid):
        await self.write_data(sid, b"")
        self.write_end[sid] = True

        await self.sock.write(self.conn.data_to_send())
            
    async def handle_request(self, request_data, stream_id):
        raise NotImplementedError()

    async def error_handler(self, sid, exc):
        print("Error executing request:")
        import traceback
        traceback.print_exc()
        
        await self.start_http(sid, 500, {"Content-Length": 0})
        await self.fin_http(sid)

    async def _handle_request2(self, request_data, stream_id):
        try:
            await self.handle_request(request_data, stream_id)
        except (ConnectionError, h2.exceptions.StreamClosedError, h2.exceptions.ProtocolError):
            pass
        except CancelledError:
            try:
                await self.sock.close()
            except:
                pass
            return
            
        except Exception as e:
            await self.error_handler(stream_id, e)
        
    async def _bail_out(self, sid, code):
        await self.start_http(sid, code, {"Content-Length": 0})
        await self.fin_http(sid)
        try:
            self.conn.close_connection()
            await self.sock.write(self.conn.data_to_send())
            await self.sock.close()
        except:
            pass

    async def data_read(self, data: bytes):
        await self.sock.write(self.conn.data_to_send())
        try:
            event = self.conn.receive_data(data)
            for ev in event:
                if isinstance(ev, h2.events.RequestReceived):
                    self.write_end[ev.stream_id] = False
                    self.request_data[ev.stream_id] = _HTTP_REQUEST(_HTTP_PLACEHOLDER, BytesIO())
                    dr = CIMultiDict(ev.headers)

                    if not dr[":method"].isupper():
                        await self._bail_out(ev.stream_id, 400)
                        return

                    if dr[":method"] not in _KNOWN_METHODS:
                        await self._bail_out(ev.stream_id, 501)
                        return

                    if dr[":method"] == "CONNECT" and ":protocol" not in dr:
                        await self._bail_out(ev.stream_id, 400)
                        return

                    self.request_data[ev.stream_id].header["protocol"] = dr.get(":protocol")

                    self.request_data[ev.stream_id].header["scheme"] = dr[":scheme"]

                    if len(dr[":path"]) > 8192:
                        await self._bail_out(ev.stream_id, 414)
                        return

                    newheaders = {}
                    for x in dr:
                        if not x.startswith(":"):
                            newheaders[x] = dr[x]

                    newheaders["host"] = dr[":authority"]

                    for i in newheaders:
                        if len(i) > 8192 or len(newheaders[i]) > 8192:
                            await self._bail_out(ev.stream_id, 431)
                            return

                    self.request_data[ev.stream_id].header["uri"] = dr[":path"]
                    self.request_data[ev.stream_id].header["method"] = dr[":method"]
                    self.request_data[ev.stream_id].header["path"] = dr[":path"].split("?", 1)[0]
                    if len(dr[":path"].split("?", 1)) > 1:
                        self.request_data[ev.stream_id].header["query"] = CIMultiDict( (k, v if len(v)>1 else v[0] ) 
                            for k, v in parse_qs( dr[":path"].split("?", 1)[1 ]).items() )

                    if "content-length" in newheaders:
                        self.has_length[ev.stream_id] = True
                    else:
                        self.has_length[ev.stream_id] = False
                    self.request_data[ev.stream_id].header["headers"] = newheaders

                elif isinstance(ev, h2.events.DataReceived):
                    try:
                        check = self.request_data[ev.stream_id]
                    except KeyError:
                        self.conn.reset_stream(
                            ev.stream_id, error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR
                        )
                    else:
                        if check.body.tell() > pow(2,32):
                            await self._bail_out(ev.stream_id, 413)
                            return

                        check.body.write(ev.data)

                elif isinstance(ev, h2.events.StreamEnded):
                    await _H2_TASKS.spawn(self._handle_request2(self.request_data[ev.stream_id], ev.stream_id))

                elif isinstance(ev, h2.events.ConnectionTerminated):
                    await self.sock.close()

                elif isinstance(ev, h2.events.StreamReset):
                    if ev.stream_id in self.flow_control_futures:
                        future = self.flow_control_futures.pop(ev.stream_id)
                        future.cancel()

                elif isinstance(ev, h2.events.WindowUpdated):
                    await self.window_updated(ev.stream_id)

                elif isinstance(ev, h2.events.RemoteSettingsChanged):
                    if h2.settings.SettingCodes.INITIAL_WINDOW_SIZE in ev.changed_settings:
                        await self.window_updated(None)

            await self.sock.write(self.conn.data_to_send())
                    
        except h2.exceptions.ProtocolError:
            await self.sock.write(self.conn.data_to_send())
            await self.sock.close()
    
    async def disconnection(self, exc):
        try:
            self.conn.close_connection()
        except:
            pass
    
    async def request_received(self, data, stream_id):
        """
        Handle a request by attempting to serve a suitable file.
        """
        headers = dict(data.headers)
        assert headers[':method'] == 'GET'

        path = headers[':path'].lstrip('/')
        full_path = os.path.join(self.root, path)

        if not os.path.exists(full_path):
            response_headers = (
                (':status', '404'),
                ('content-length', '0'),
                ('server', 'curio-h2'),
            )
            self.conn.send_headers(
                stream_id, response_headers, end_stream=True
            )
            await self.sock.sendall(self.conn.data_to_send())
        else:
            await self.send_file(full_path, stream_id)

    async def wait_for_flow_control(self, stream_id):
        """
        Blocks until the flow control window for a given stream is opened.
        """
        evt = Event()
        self.flow_control_events[stream_id] = evt
        await evt.wait()

    async def window_updated(self, stream_id):
        """
        A window update frame was received. Unblock some number of flow control
        Futures.
        """
        if stream_id and stream_id in self.flow_control_events:
            f = self.flow_control_events.pop(stream_id)
            await f.set()
            
        elif not stream_id:
            for f in self.flow_control_events.values():
                await f.set()

            self.flow_control_futures = {}

class _H2Handler(H2Server):
    def __init__(self, handler):
        super().__init__()
        self.handler = handler
    async def handle_request(self, request_data: _HTTP_REQUEST, stream_id: int):
        resp = await self.handler(request_data, stream_id, self)

        if isinstance(resp, tuple):
            headers = {}
            status = resp[0]
            hasLength = False
            data = resp[1]
            if isinstance(data, Coroutine):
                data = await data
            if len(resp) >= 3:
                headers = resp[2]
                if "content-length" in headers:
                    hasLength = True
            if (isinstance(data, bytes) or isinstance(data,bytearray) or isinstance(data,str)) and not hasLength:
                hasLength = True
                headers["Content-Length"] = len(data)
                
            await self.start_http(stream_id, status, headers)

            if request_data.header["method"] != "HEAD":
                if isinstance(data, bytes) or isinstance(data,bytearray) or isinstance(data,str):
                    await self.write_data(stream_id, data)
                elif isinstance(data, IOBase):
                    with data:
                        nextData = None
                        while True:
                            chunk = await run_in_thread(data.read, 8192)
                            if not chunk:
                                if not nextData:
                                    nextData = b""
                                await self.write_data(stream_id, nextData)
                                break
                            if nextData:
                               await self.write_data(stream_id, nextData, False)
                            nextData = chunk
                elif isinstance(data, Iterable) or isinstance(data, Generator) or isinstance(data, Iterator):
                    nextData = None
                    for chunk in data:
                        if nextData:
                            await self.write_data(stream_id, nextData, False)
                        nextData = chunk
                    if not nextData:
                        await self.write_data(stream_id, b"")
                    else:
                        await self.write_data(stream_id, nextData)

                elif isinstance(data, AsyncIterable) or isinstance(data, AsyncGenerator) or isinstance(data, AsyncIterator):
                    nextData = None
                    async for chunk in data:
                        if nextData:
                            await self.write_data(stream_id, nextData, False)
                        nextData = chunk
                    if not nextData:
                        await self.write_data(stream_id, b"")
                    else:
                        await self.write_data(stream_id, nextData)
                    
        else:
            raise Exception("Unknown response type")

class WSHandler():
    def __init__(self, sid: int, conn: H2Server, request: _HTTP_REQUEST):
        self.conn = wsproto.Connection(wsproto.ConnectionType.SERVER, [wsproto.extensions.PerMessageDeflate()])
        self.__ctx = conn
        self.__sid = sid
        self.request = request
        self._accepted = False
        self.closed = False

    async def accept(self, protocols=[], default_protocol=None):

        if protocols and default_protocol and default_protocol not in protocols:
            raise Exception("Default protocol must be in protocols")

        if "sec-websocket-protocol" in self.__ctx.request_data[self.__sid].header["headers"]:
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

        protocolSwitch = {}

        if "sec-websocket-key" in self.__ctx.request_data[self.__sid].header["headers"]:
            protocolSwitch["Sec-Websocket-Accept"] = wsproto.utilities.generate_accept_token(self.__ctx.hdata.header["headers"]["sec-websocket-key"].encode("ascii")).decode("utf-8")

        if selProto:
            protocolSwitch["Sec-Websocket-Protocol"] = selProto

        await self.__ctx.start_http(self.__sid,200,protocolSwitch)
        self._accepted = True
        return protocol
    
    async def read(self):
        if not self._accepted:
            await self.accept()
        resData = None
        while resData == None:
            s = await self.__ctx.sock.read(256*1024)
            if not s:
                raise CancelledError()
            
            for e in self.__ctx.conn.receive_data(s):
                if self.__sid == e.stream_id:
                    if isinstance(e, h2.events.DataReceived):

                        self.conn.receive_data(e.data)
                        for we in self.conn.events():
                            if isinstance(we, wsproto.events.BytesMessage):
                                if resData == None:
                                    resData = bytearray(we.data)
                                else:
                                    resData += we.data
                            elif isinstance(we, wsproto.events.TextMessage):
                                if resData == None:
                                    resData = we.data
                                else:
                                    resData += we.data      
                            elif isinstance(we, wsproto.events.Ping):
                                await self.__ctx.write_data(e.stream_id, self.conn.send(we.response()))
                            elif isinstance(we, wsproto.events.CloseConnection):
                                await self.__ctx.write_data(e.stream_id, self.conn.send(we.response()))
                                raise CancelledError()

                    elif isinstance(e, h2.events.StreamEnded):
                        raise CancelledError()

                    elif isinstance(e, h2.events.ConnectionTerminated):
                        raise CancelledError()

                    elif isinstance(e, h2.events.StreamReset):
                        if e.stream_id in self.__ctx.flow_control_futures:
                            future = self.__ctx.flow_control_futures.pop(e.stream_id)
                            future.cancel()

                    elif isinstance(e, h2.events.WindowUpdated):
                        await self.__ctx.window_updated(e.stream_id)

                    elif isinstance(e, h2.events.RemoteSettingsChanged):
                        if h2.settings.SettingCodes.INITIAL_WINDOW_SIZE in e.changed_settings:
                            await self.__ctx.window_updated(None)

        return resData

    async def write(self, data):
        if not self._accepted:
            await self.accept()
        await self.__ctx.write_data(self.__sid, self.conn.send(wsproto.events.Message(data)), False)

    async def close(self, code=wsproto.connection.CloseReason.NORMAL_CLOSURE, reason=None):
        if not self._accepted:
            raise Exception("Websocket connection was closed before accepting")

        await self.__ctx.write_data(self.__sid, self.conn.send(wsproto.events.CloseConnection(code, reason)))
        self.closed = True
        raise CancelledError()

class H2RoutesHandler():
    def __init__(self):
        self.routes = routing.Map()

    def add_route(self, route, method=["GET"], ws=False):
        def decorator(f):
            self.routes.add(routing.Rule(route, endpoint=f, methods=method))
            return f
        return decorator

    async def serve(self, request_data: _HTTP_REQUEST, stream_id: int, ctx: H2Server):
        isWs = False

        if (
            request_data.header["protocol"] == "websocket"
            and request_data.header["headers"].get("sec-websocket-version") == "13"
        ):
            isWs = True
            scheme = "wss" if request_data.header["scheme"] == "https" else "ws"
        else:
            scheme = request_data.header["scheme"]

        rt = self.routes.bind(request_data.header["headers"]["host"], url_scheme=scheme)
        try:
            handler = rt.match(request_data.header["path"])
        except routing.RequestRedirect as e:
            return 301, "", {"Location": e.new_url}
        except routing.HTTPException as e:
            return e.code, ""

        try:
            hdt = _HTTP_REQUEST(AttrDict(request_data.header), request_data.body)
            if hdt.header.query:
                hdt.header.query = AttrDict(hdt.header.query)
            hdt.header.headers = AttrDict(hdt.header.headers)

            if isWs:
                wsCtx = WSHandler(stream_id, ctx, hdt)
                s = await handler[0](wsCtx, **handler[1])
                if wsCtx._accepted and not wsCtx.closed:
                    wsCtx.close()
                return s

            else:
                return await handler[0](hdt, **handler[1])
        except routing.HTTPException as e:
            return e.code, ""
        
def http_router(s: H2RoutesHandler) -> ASProtocol:
    return lambda: _H2Handler(s.serve)        

class _H2Test(H2Server):
    async def handle_request(self, req, sid):
        await self.start_http(sid, 200)
        await self.write_data(sid, "Hello!\nRequest Headers:\n", False)
        await self.write_data(sid, req.header, False)
        if len(req.body.getvalue()) >= 1:
            await self.write_data(sid, "\nRequest Body:\n", False)
            await self.write_data(sid, req.body.getvalue().hex()+"\n")
        else:
            await self.write_data(sid, "\n")


if __name__ == "__main__":
    from .curios import run, tcp_server
    ssl_ctx = get_recomended_tls_settings(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.set_alpn_protocols(["h2"])
    ssl_ctx.load_cert_chain("aslib/test/selfsigned.pem", "aslib/test/selfsigned_key.pem")
    #run(tcp_server ("", 8855, ASProtocolHandler(_H2Test).serve, ssl=ssl_ctx))

    routeDef = H2RoutesHandler()
    @routeDef.add_route("/")
    async def hello(request):
        return 200, "Hello!\n"

    run(tcp_server ("", 8855, ASProtocolHandler(http_router(routeDef)).serve, ssl=ssl_ctx))