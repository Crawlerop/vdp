from .assock import ASProtocol, ASSock, get_recomended_tls_settings, ASProtocolHandler
from .ash1 import http_router as hrouter, RoutesHandler
from .ash2 import http_router as h2router, H2RoutesHandler
from .curios import ssl
from werkzeug import routing

class Routing():
    def __init__(self):
        self.routes = routing.Map()

    def add_route(self, route, method=["GET"], ws=False):
        def decorator(f):
            self.routes.add(routing.Rule(route, endpoint=f, methods=method, websocket=ws))
            return f
        return decorator

    def bind_route(self, route, event, method=["GET"], ws=False):
        self.routes.add(routing.Rule(route, endpoint=event, methods=method, websocket=ws))

class HTTP12RoutesHandler(ASProtocol):
    def __init__(self, route: Routing):
        self.routes = route
        self._wrapProto = None
        self.conn = None
        self.started = False

    async def connection(self, conn: ASSock):
        self.conn = conn
        if self.conn._underlying_socket.secure:
            info = self.conn.get_tls_info()
            if info.alpn == "h2" or info.npn == "h2":
                route = H2RoutesHandler()
                route.routes = self.routes.routes

                self._wrapProto = h2router(route)()
            else:
                route = RoutesHandler()
                route.routes = self.routes.routes

                self._wrapProto = hrouter(route)()

            self.started = True
            await self._wrapProto.connection(conn)
            

    async def data_read(self, data: bytes):
        if not self.started:
            if data.startswith(b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'):
                route = H2RoutesHandler()
                route.routes = self.routes.routes

                self._wrapProto = h2router(route)()
            else:
                route = RoutesHandler()
                route.routes = self.routes.routes

                self._wrapProto = hrouter(route)()
            self.started = True
            await self._wrapProto.connection(self.conn)
        await self._wrapProto.data_read(data)

    async def disconnection(self, exc):
        pass
            
def http_router(s: Routing): 
    return lambda: HTTP12RoutesHandler(s)

if __name__ == "__main__":
    from .curios import run, tcp_server
    ssl_ctx = get_recomended_tls_settings(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.set_alpn_protocols(["h2", "http/1.1"])
    ssl_ctx.load_cert_chain("aslib/test/selfsigned.pem", "aslib/test/selfsigned_key.pem")
    #run(tcp_server ("", 8855, ASProtocolHandler(_H2Test).serve, ssl=ssl_ctx))

    routeDef = Routing()
    @routeDef.add_route("/")
    async def hello(request):
        return 200, "Hello!\n"

    run(tcp_server ("", 8855, ASProtocolHandler(http_router(routeDef)).serve, ssl=ssl_ctx))