# app.py — Poe bridge that makes two bots talk
from typing import AsyncIterable
import os
import fastapi_poe as fp

TURNS = 4  # how many back-and-forth replies

POE_API_KEY = os.environ.get("POE_API_KEY")
if not POE_API_KEY:
    raise RuntimeError("Missing POE_API_KEY env var (your long key from poe.com/developers).")

async def call_bot(bot_name: str, message: str) -> str:
    chunks = []
    async for event in fp.stream_request(
        bot_name=bot_name,
        message=message,
        api_key=POE_API_KEY,
    ):
        if isinstance(event, fp.TextChunk):
            chunks.append(event.text)
    return "".join(chunks).strip()

class BridgeBot(fp.PoeBot):
    async def get_response(self, request: fp.QueryRequest) -> AsyncIterable[fp.PartialResponse]:
        text = request.query[-1].content.strip()

        # Accept "bridge ..." or "/bridge ..."
        if text.lower().startswith("bridge") or text.lower().startswith("/bridge"):
            try:
                s = text[1:] if text.startswith("/") else text
                header, topic = s.split(":", 1)
                _, a, b = header.strip().split()   # bridge a b
                a, b = a.strip(), b.strip()
                topic = topic.strip()
            except Exception:
                yield fp.PartialResponse(
                    text="Usage: bridge <botA> <botB>: <topic>\nExample: bridge claude-3-5-sonnet gpt-4o: Say hello."
                )
                return

            transcript, speaker, last_msg = [], a, topic
            for _ in range(TURNS):
                reply = await call_bot(speaker, last_msg)
                transcript.append(f"[{speaker}]: {reply}")
                last_msg = reply
                speaker = b if speaker == a else a

            yield fp.PartialResponse(text="\n".join(transcript))
            return

        # Help for normal messages
        yield fp.PartialResponse(
            text="Use: bridge <botA> <botB>: <topic>\nExample: bridge claude-3-5-sonnet gpt-4o: Say hello."
        )

app = fp.make_app(BridgeBot())
# Start on Render with: uvicorn app:app --host 0.0.0.0 --port $PORT

