"""Bound streamed bodies as well as declared Content-Length before multipart parsing."""
from starlette.responses import JSONResponse
from starlette.requests import ClientDisconnect

class BodyLimit:
    def __init__(self, app, maximum=3*1024*1024): self.app=app; self.maximum=maximum
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]))
        try: declared=int(headers.get(b'content-length',b'0'))
        except ValueError:
            return await JSONResponse({'detail':'Invalid content length'},status_code=400)(scope,receive,send)
        if declared<0 or declared>self.maximum:
            return await JSONResponse({'detail':'Request too large'},status_code=413)(scope,receive,send)
        # Buffer a bounded body so overflow produces a clean error before endpoint execution.
        chunks=[]; size=0
        if scope['method'] not in {'GET','HEAD','OPTIONS'}:
            while True:
                part=await receive()
                if part['type']=='http.disconnect': return
                size+=len(part.get('body',b''))
                if size>self.maximum:
                    return await JSONResponse({'detail':'Request too large'},status_code=413)(scope,receive,send)
                chunks.append(part)
                if not part.get('more_body',False): break
        async def limited_receive():
            if chunks: return chunks.pop(0)
            return await receive()
        await self.app(scope,limited_receive,send)
