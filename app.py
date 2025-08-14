# app.py  — bridge-only, compatible with current fastapi_poe
from typing import AsyncIterable
import fastapi_poe as fp

TURNS = 4  # number of back-and-forth messages

async def call_other_bot(bot_name: str, message: str, req: fp.QueryRequest) -> str:
    # Ask another Poe bot and return its full response as a string
    # Uses the Bot Query API helper; works inside server bots.
    # (api_key param not needed here when called from a server bot)
    return await fp.get_final_response(request=req, bot_name=bot_name)

class BridgeBot(fp.PoeBot):
    async def get_response(self, request: fp.QueryRequest) -> AsyncIterable[fp.PartialResponse]:
        user_text = request.query[-1].content.strip()

        # Command format: /bridge botA botB: topic...
        if user_text.lower().startswith("/bridge"):
            try:
                header, topic = user_text.split(":", 1)
                _, bot_a, bot_b = header.strip().split()
                bot_a, bot_b = bot_a.strip(), bot_b.strip()
                topic = topic.strip()
            except Exception:
                yield fp.PartialResponse(text="Usage: /bridge <botA> <botB>: <topic>")
                return

            transcript = []
            speaker = bot_a
            last_msg = topic

            for _ in range(TURNS):
                reply = await call_other_bot(speaker, last_msg, request)
                transcript.append(f"[{speaker}]: {reply}")
                # swap speaker each turn, feed previous reply
                last_msg = reply
                speaker = bot_b if speaker == bot_a else bot_a

            yield fp.PartialResponse(text="\n".join(transcript))
            return

        # Default help text
        yield fp.PartialResponse(text="Use: /bridge <botA> <botB>: <topic>")

app = fp.make_app(BridgeBot())
# Start with: uvicorn app:app --host 0.0.0.0 --port $PORT
