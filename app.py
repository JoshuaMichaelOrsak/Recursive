# app.py — Minimal streaming bridge (no external memory)
from typing import AsyncIterable, List
import os, logging, traceback
import fastapi_poe as fp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

DEFAULT_TURNS = 4
MAX_TURNS = 40

POE_API_KEY = os.environ.get("POE_API_KEY")
if not POE_API_KEY:
    raise RuntimeError("Missing POE_API_KEY (get it from https://poe.com/api_key).")

class BridgeBot(fp.PoeBot):
    async def get_response(self, request: fp.QueryRequest) -> AsyncIterable[fp.PartialResponse]:
        text = (request.query[-1].content or "").strip()

        # quick health check
        if text.lower() == "ping":
            yield fp.PartialResponse(text="pong")
            return

        # Command: bridge <botA> <botB> [turns]: <topic>
        if text.lower().startswith("bridge") or text.lower().startswith("/bridge"):
            try:
                s = text[1:] if text.startswith("/") else text
                header, topic = s.split(":", 1)
                parts = header.strip().split()

                if len(parts) not in (3, 4):
                    raise ValueError("Usage: bridge <botA> <botB> [turns]: <topic>")

                _, bot_a, bot_b = parts[:3]
                bot_a, bot_b = bot_a.strip(), bot_b.strip()
                turns = DEFAULT_TURNS if len(parts) == 3 else int(parts[3])
                if turns <= 0 or turns > MAX_TURNS:
                    raise ValueError(f"turns must be 1..{MAX_TURNS}")

                topic = topic.strip()
                if not topic:
                    raise ValueError("Missing topic after ':'")

                speaker = bot_a
                last_msg = topic

                for _ in range(turns):
                    # header for this speaker
                    yield fp.PartialResponse(text=f"\n[{speaker}]: ")

                    # build the messages list just for this turn (no external memory)
                    msgs: List[fp.ProtocolMessage] = [fp.ProtocolMessage(role="user", content=last_msg)]
                    # stream tokens to the user and also collect them to pass to the next speaker
                    parts_accum: List[str] = []

                    try:
                        async for event in fp.get_bot_response(
                            messages=msgs,
                            bot_name=speaker,
                            api_key=POE_API_KEY,
                        ):
                            if hasattr(event, "text") and isinstance(getattr(event, "text"), str):
                                token = event.text
                                parts_accum.append(token)
                                yield fp.PartialResponse(text=token)
                    except Exception as e:
                        log.error("Error calling '%s': %s\n%s", speaker, e, traceback.format_exc())
                        yield fp.PartialResponse(text=f"\n[system]: Bridge error: {e}\n")
                        return

                    # end this speaker turn
                    yield fp.PartialResponse(text="\n")

                    # swap speaker/prepare next prompt
                    last_msg = "".join(parts_accum).strip()
                    speaker = bot_b if speaker == bot_a else bot_a

                return

            except Exception as e:
                yield fp.PartialResponse(
                    text=f"Bridge error: {e}\n"
                         "Usage: bridge <botA> <botB> [turns]: <topic>\n"
                         "Example: bridge claude-3-5-sonnet gpt-4o 6: Say hello."
                )
                return

        # Help text if not using the command
        yield fp.PartialResponse(
            text="Use: bridge <botA> <botB> [turns]: <topic>\n"
                 "Examples:\n"
                 "• bridge claude-3-5-sonnet gpt-4o: Say hello.\n"
                 "• bridge claude-3-5-sonnet gpt-4o 8: Brainstorm 3 ideas."
        )

app = fp.make_app(BridgeBot())
# Start on Render: uvicorn app:app --host 0.0.0.0 --port $PORT
