# app.py — Streaming bridge with light in-chat memory (no external instances)
from typing import AsyncIterable, List, Dict, Tuple
import os, logging, traceback
import fastapi_poe as fp

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

DEFAULT_TURNS = 4
MAX_TURNS = 40

POE_API_KEY = os.environ.get("POE_API_KEY")  # long key from https://poe.com/api_key
if not POE_API_KEY:
    raise RuntimeError("Missing POE_API_KEY")

# --- Minimal in-chat memory -----------------------------------------------
# Keyed by (conversation_id, bot_name) so it persists only within *this* Poe chat.
SESS: Dict[Tuple[str, str], List[fp.ProtocolMessage]] = {}
MAX_HISTORY = 20  # keep last N protocol messages per bot per chat

def _load(conv_id: str, bot: str) -> List[fp.ProtocolMessage]:
    return SESS.get((conv_id, bot), []).copy()

def _save(conv_id: str, bot: str, user_text: str, bot_text: str):
    msgs = SESS.get((conv_id, bot), [])
    msgs += [
        fp.ProtocolMessage(role="user", content=user_text),
        fp.ProtocolMessage(role="bot",  content=bot_text),
    ]
    if len(msgs) > MAX_HISTORY:
        msgs = msgs[-MAX_HISTORY:]
    SESS[(conv_id, bot)] = msgs
# --------------------------------------------------------------------------

class BridgeBot(fp.PoeBot):
    async def get_response(self, request: fp.QueryRequest) -> AsyncIterable[fp.PartialResponse]:
        text = (request.query[-1].content or "").strip()
        # conversation_id is stable for this chat; fall back to user_id if missing
        conv_id = str(getattr(request, "conversation_id", getattr(request, "user_id", "default")))

        # quick health check
        if text.lower() == "ping":
            yield fp.PartialResponse(text="pong")
            return

        # clear *this chat’s* memory (optional helper)
        if text.lower().strip() == "reset":
            # wipe only this chat’s keys
            for k in list(SESS.keys()):
                if k[0] == conv_id:
                    SESS.pop(k, None)
            yield fp.PartialResponse(text="Memory cleared for this chat.")
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
                    # header line for this speaker
                    yield fp.PartialResponse(text=f"\n[{speaker}]: ")

                    # messages for this turn = prior memory (for this chat + speaker) + the new prompt
                    msgs: List[fp.ProtocolMessage] = _load(conv_id, speaker)
                    msgs.append(fp.ProtocolMessage(role="user", content=last_msg))

                    parts_accum: List[str] = []
                    try:
                        # Stream tokens from the called bot *and* forward them live to the user.
                        async for event in fp.get_bot_response(
                            messages=msgs,
                            bot_name=speaker,
                            api_key=POE_API_KEY,
                        ):
                            if hasattr(event, "text") and isinstance(getattr(event, "text"), str):
                                tok = event.text
                                parts_accum.append(tok)
                                yield fp.PartialResponse(text=tok)
                    except Exception as e:
                        log.error("Error calling '%s': %s\n%s", speaker, e, traceback.format_exc())
                        yield fp.PartialResponse(text=f"\n[system]: Bridge error: {e}\n")
                        return

                    # end this turn visually
                    yield fp.PartialResponse(text="\n")

                    # commit this turn to the *in-chat* memory
                    reply_text = "".join(parts_accum).strip()
                    _save(conv_id, speaker, last_msg, reply_text)

                    # alternate speaker and pass last reply as next prompt
                    last_msg = reply_text
                    speaker = bot_b if speaker == bot_a else bot_a

                return

            except Exception as e:
                yield fp.PartialResponse(
                    text=f"Bridge error: {e}\n"
                         "Usage: bridge <botA> <botB> [turns]: <topic>\n"
                         "Example: bridge claude-3-5-sonnet gpt-4o 6: Say hello."
                )
                return

        # Help text
        yield fp.PartialResponse(
            text="Use: bridge <botA> <botB> [turns]: <topic>\n"
                 "Examples:\n"
                 "• bridge claude-3-5-sonnet gpt-4o: Say hello.\n"
                 "• bridge claude-3-5-sonnet gpt-4o 8: Brainstorm 3 ideas.\n"
                 "• reset   (clears this chat’s memory)"
        )

app = fp.make_app(BridgeBot())
# Start on Render: uvicorn app:app --host 0.0.0.0 --port $PORT

