# app.py — Poe bridge (correct positional arg order) + diagnostics
from typing import AsyncIterable
import os, traceback, logging
import fastapi_poe as fp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

TURNS = 4  # number of back-and-forth turns

# Long developer key from https://poe.com/developers
POE_API_KEY = os.environ.get("POE_API_KEY")
if not POE_API_KEY:
    raise RuntimeError("Missing POE_API_KEY env var (your long key from poe.com/developers).")

async def call_bot(bot_name: str, message: str) -> str:
    """Send `message` to `bot_name` and return the full text reply."""
    chunks = []
    try:
        # IMPORTANT: positional order must be (query, bot_name, api_key)
        async for event in fp.stream_request(message, bot_name, POE_API_KEY):
            if hasattr(event, "text") and isinstance(getattr(event, "text"), str):
                chunks.append(event.text)
    except Exception as e:
        log.error("Error calling bot '%s': %s\n%s", bot_name, e, traceback.format_exc())
        raise
    return "".join(chunks).strip()

class BridgeBot(fp.PoeBot):
    async def get_response(self, request: fp.QueryRequest) -> AsyncIterable[fp.PartialResponse]:
        text = (request.query[-1].content or "").strip()

        # quick health check
        if text.lower() == "ping":
            yield fp.PartialResponse(text="pong")
            return

        # Accept "bridge ..." or "/bridge ..."
        if text.lower().startswith("bridge") or text.lower().startswith("/bridge"):
            try:
                s = text[1:] if text.startswith("/") else text
                header, topic = s.split(":", 1)
                parts = header.strip().split()
                if len(parts) != 3:
                    raise ValueError("Usage: bridge <botA> <botB>: <topic>")
                _, a, b = parts
                a, b = a.strip(), b.strip()
                topic = topic.strip()

                transcript, speaker, last_msg = [], a, topic
                for _ in range(TURNS):
                    reply = await call_bot(speaker, last_msg)
                    transcript.append(f"[{speaker}]: {reply}")
                    last_msg = reply
                    speaker = b if speaker == a else a

                yield fp.PartialResponse(text="\n".join(transcript))
                return

            except Exception as e:
                log.error("Bridge failed: %s\n%s", e, traceback.format_exc())
                yield fp.PartialResponse(
                    text=f"Bridge error: {e}\n"
                         "Tips: use exact poe.com/<handle> slugs (lowercase) and ensure POE_API_KEY is set."
                )
                return

        # help text
        yield fp.PartialResponse(
            text="Use: bridge <botA> <botB>: <topic>\n"
                 "Example: bridge claude-3-5-sonnet gpt-4o: Say hello."
        )

app = fp.make_app(BridgeBot())
# Start on Render: uvicorn app:app --host 0.0.0.0 --port $PORT


