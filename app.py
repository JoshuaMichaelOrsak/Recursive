# app.py — Bridge with dynamic turns and "auto until [CHECK]" stop signal
from typing import AsyncIterable
import os, logging, traceback
import fastapi_poe as fp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

DEFAULT_TURNS = 4
MAX_TURNS = 60                 # safety cap so it can’t run forever
STOP_TOKEN = "[CHECK]"         # token a bot should emit to check with the human

POE_API_KEY = os.environ.get("POE_API_KEY")
if not POE_API_KEY:
    raise RuntimeError("Missing POE_API_KEY env var (long key from poe.com/api_key).")

async def call_bot(bot_name: str, message: str) -> str:
    """Send message to bot_name via Poe and return full text reply."""
    chunks: list[str] = []
    try:
        user_msg = fp.ProtocolMessage(role="user", content=message)
        async for event in fp.get_bot_response(messages=[user_msg],
                                               bot_name=bot_name,
                                               api_key=POE_API_KEY):
            if hasattr(event, "text") and isinstance(getattr(event, "text"), str):
                chunks.append(event.text)
    except Exception as e:
        log.error("Error calling '%s': %s\n%s", bot_name, e, traceback.format_exc())
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

                # bridge <A> <B> [turns|auto]
                if len(parts) not in (3, 4):
                    raise ValueError("Usage: bridge <botA> <botB> [turns|auto]: <topic>")

                _, bot_a, bot_b = parts[:3]
                bot_a, bot_b = bot_a.strip(), bot_b.strip()
                mode = parts[3].strip().lower() if len(parts) == 4 else None

                auto = (mode == "auto")
                turns = DEFAULT_TURNS if mode is None else (None if auto else int(mode))
                if turns is not None and (turns <= 0 or turns > MAX_TURNS):
                    raise ValueError(f"turns must be 1..{MAX_TURNS}")

                topic = topic.strip()

                transcript = []
                speaker = bot_a
                last_msg = topic

                # add guidance every turn so either bot can stop with STOP_TOKEN
                guidance = f"\n\n(If you want to check with the human, include {STOP_TOKEN} on its own line and stop.)"

                count = 0
                while True:
                    reply = await call_bot(speaker, last_msg + guidance)
                    transcript.append(f"[{speaker}]: {reply}")

                    # stop conditions
                    if auto and STOP_TOKEN.lower() in reply.lower():
                        transcript.append(f"[system]: Stop token {STOP_TOKEN} detected. Halting.")
                        break

                    count += 1
                    if not auto and count >= turns:
                        break
                    if count >= MAX_TURNS:
                        transcript.append(f"[system]: Reached safety cap of {MAX_TURNS} turns. Halting.")
                        break

                    # alternate
                    last_msg = reply
                    speaker = bot_b if speaker == bot_a else bot_a

                yield fp.PartialResponse(text="\n".join(transcript))
                return

            except Exception as e:
                yield fp.PartialResponse(
                    text=f"Bridge error: {e}\n"
                         "Use: bridge <botA> <botB> [turns|auto]: <topic>\n"
                         f"In auto mode, a bot can stop by emitting {STOP_TOKEN}."
                )
                return

        # help text for normal messages
        yield fp.PartialResponse(
            text="Use: bridge <botA> <botB> [turns|auto]: <topic>\n"
                 "Examples:\n"
                 "• bridge claude-3-5-sonnet gpt-4o: Say hello.\n"
                 "• bridge claude-3-5-sonnet gpt-4o 12: Brainstorm.\n"
                 f"• bridge claude-3-5-sonnet gpt-4o auto: Debate (stop with {STOP_TOKEN})."
        )

app = fp.make_app(BridgeBot())
# Start on Render: uvicorn app:app --host 0.0.0.0 --port $PORT
