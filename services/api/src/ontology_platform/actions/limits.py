"""Bound raw action bodies before FastAPI JSON parsing."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ActionPayloadLimit:
    def __init__(
        self,
        app: ASGIApp,
        *,
        paths: tuple[str, ...] = ("/actions/",),
        methods: tuple[str, ...] = ("POST",),
        code: str = "action_payload_too_large",
        message: str = "Action payload exceeds 64 KiB",
        max_bytes: int = 65536,
    ):
        self.app = app
        self.paths, self.code, self.message = paths, code, message
        self.methods = methods
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in self.methods
            or not any(path in scope.get("path", "") for path in self.paths)
        ):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": self.code,
                            "message": self.message,
                        }
                    },
                )(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        consumed = False

        async def replay() -> Message:
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay, send)
