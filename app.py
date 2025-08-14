# app.py
import asyncio
import fastapi_poe as fp
from typing import AsyncIterable

TURNS = 4  # how many back-and-forth turns for bridge mode
CRITIC_BOT = "gpt-4o"       # a strong critic model on Poe
DEFAULT_HELPER = "claude-3-5-sonnet"  # helper/second-opinion

def as_text(content: fp.Content) -> str:
    if content.type == "text":
        return content.text or ""
    return ""

async def call_poe(bot: str, prompt: str, meta: fp.Meta) -> str:
    out = []
    async for event in fp.stream_request(
        bot_name=bot,
        message=prompt,
        api_key=meta.api_key,
        # Pass along the conversation visibility & user meta
        metadata=fp.RequestMetadata(user_id=meta.user_id),
    ):
        if isinstance(event, fp.TextChunk):
            out.append(event.text)
    return "".join(out).strip()

class BridgeAndReflectBot(fp.PoeBot):
    async def get_response(self, request: fp.QueryRequest) -> AsyncIterable[fp.PartialResponse]:
        meta = request.meta
        user_msg = as_text(request.query[0].content[0])

        # Mode A: Bridge two bots
        if user_msg.lower().startswith("/bridge"):
            # Format: /bridge botA botB: topic...
            try:
                header, topic = user_msg.split(":", 1)
                _, a, b = header.strip().split()  # /bridge a b
                a, b = a.strip(), b.strip()
                topic = topic.strip()
            except Exception:
                yield fp.PartialResponse(text="Usage: /bridge <botA> <botB>: <topic>")
                return

            transcript = []
            speaker, listener = a, b
            last_msg = topic

            for i in range(TURNS):
                reply = await call_poe(speaker, last_msg, meta)
                transcript.append(f"[{speaker}]: {reply}")
                # next turn: swap
                last_msg = reply
                speaker, listener = listener, speaker

            yield fp.PartialResponse(text="\n".join(transcript))
            return

        # Mode B: Recursive Mind (draft -> critique -> revise)
        # 1) Draft with your preferred helper model
        draft = await call_poe(DEFAULT_HELPER, f"Draft a helpful answer to:\n{user_msg}", meta)

        # 2) Critique with a critic model
        critique_prompt = (
            "CRITIC TASK: Evaluate the DRAFT for accuracy, clarity, safety, and completeness. "
            "List concrete edits without rewriting everything. Then provide a revised answer.\n\n"
            f"DRAFT:\n{draft}"
        )
        critique = await call_poe(CRITIC_BOT, critique_prompt, meta)

        # 3) (Optional) Second opinion & merge
        merge_prompt = (
            "Merge the following into one final, concise, high-quality answer. "
            "Prefer factual accuracy and clear steps. If any unsafe or speculative content appears, remove it.\n\n"
            f"USER:\n{user_msg}\n\nCRITIQUE+REVISION:\n{critique}"
        )
        final_answer = await call_poe(DEFAULT_HELPER, merge_prompt, meta)

        yield fp.PartialResponse(text=final_answer)

app = fp.make_app(BridgeAndReflectBot())

if __name__ == "__main__":
    # Local run helper; in prod deploy behind uvicorn/gunicorn
    fp.run(BridgeAndReflectBot())
