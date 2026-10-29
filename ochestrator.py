import argparse, asyncio, json, math, random, re
from contextlib import aclosing
import httpx
from shared import MODERATOR, INTERRUPT, WAIT, render

PERSONAS = {
    "solidarity_us": {"url": "http://127.0.0.1:8081", "label": "SOLIDARITÄT (USA)"},
    "ddr":           {"url": "http://127.0.0.1:8082", "label": "DDR"},
}
MODES = {                       # thresh = minimum relative p(interrupt); None = never interrupt
    "polite": dict(thresh=None, min_chars=0),
    "free":   dict(thresh=0.6,  min_chars=60),
    "chaos":  dict(thresh=0.25, min_chars=40),
}
SENT_END = re.compile(r'[.!?…]["“”)]*\s*$')
client = httpx.AsyncClient(timeout=None)

async def stream(speaker, prompt, n_predict=160):
    async with client.stream("POST", PERSONAS[speaker]["url"] + "/completion", json={
            "prompt": prompt, "stream": True, "n_predict": n_predict, "cache_prompt": True,
            "temperature": 0.8, "top_p": 0.9, "repeat_penalty": 1.1,
            "stop": ["<|im_end|>"]}) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            d = json.loads(line[6:])
            yield d.get("content", "")
            if d.get("stop"):
                break

def _prob(t):
    if "prob" in t: return t["prob"]
    if "logprob" in t: return math.exp(t["logprob"])
    return 0.0

async def p_interrupt(listener, prompt):
    r = await client.post(PERSONAS[listener]["url"] + "/completion", json={
        "prompt": prompt, "n_predict": 1, "n_probs": 20, "temperature": 0, "cache_prompt": True})
    r.raise_for_status()
    top = r.json()["completion_probabilities"][0]       # field names differ per version: print one raw response first
    pi = pw = 0.0
    for t in top.get("top_logprobs") or top.get("probs") or []:
        name = t.get("token") or t.get("tok_str")
        if name == INTERRUPT: pi = _prob(t)
        elif name == WAIT:    pw = _prob(t)
    return pi / (pi + pw) if pi + pw > 0 else 0.0       # same relative p as in the training eval

async def speak(speaker, listener, transcript, mode, allow_interrupt, dice, debug):
    text = ""
    cut = False
    async with aclosing(stream(speaker, render(transcript, next_speaker=speaker))) as gen:
        async for piece in gen:
            text += piece
            print(piece, end="", flush=True)
            if not (allow_interrupt and mode["thresh"] is not None):
                continue
            if len(text) > mode["min_chars"] and SENT_END.search(text):
                if dice is not None:
                    p = random.random() if random.random() < dice else 0.0
                else:
                    p = await p_interrupt(listener, render(transcript, (speaker, text), listener))
                if debug: print(f" [p={p:.2f}]", end="", flush=True)
                if p > mode["thresh"]:
                    cut = True
                    break                                # leaving aclosing() closes the stream, which stops generation
    return text.strip(), cut

async def objection(speaker, listener, transcript, partial):
    prompt = render(transcript, (speaker, partial), listener) + INTERRUPT
    out = ""
    async with aclosing(stream(listener, prompt, n_predict=80)) as gen:
        async for piece in gen:
            out += piece
            print(piece, end="", flush=True)
    return out.strip()

async def debate(topic, mode_name, turns, dice, debug):
    mode = MODES[mode_name]
    transcript = [(MODERATOR, topic)]
    speaker, listener = "solidarity_us", "ddr"
    just_interrupted = False
    print(f"\n=== {topic} ({mode_name}) ===")
    for _ in range(turns):
        print(f"\n\n[{PERSONAS[speaker]['label']}] ", end="", flush=True)
        text, cut = await speak(speaker, listener, transcript, mode, not just_interrupted, dice, debug)
        transcript.append((speaker, text))
        if cut:
            print(" —", end="")
            print(f"\n\n[{PERSONAS[listener]['label']}] ", end="", flush=True)
            transcript.append((listener, await objection(speaker, listener, transcript[:-1], text)))
            just_interrupted = True                       # the interrupted persona answers next, no double interruption
            continue
        just_interrupted = False
        speaker, listener = listener, speaker
    print()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--mode", choices=MODES, default="free")
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--dice", type=float, default=None, help="random interrupts with this chance, ignores the model")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    asyncio.run(debate(a.topic, a.mode, a.turns, a.dice, a.debug))
    