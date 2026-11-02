import argparse, asyncio, json, math, os, random, re, subprocess, sys, threading, time
from collections import Counter
from contextlib import ExitStack, aclosing, redirect_stdout, suppress
from pathlib import Path
from urllib.request import urlopen

import httpx
from shared import MODERATOR, INTERRUPT, WAIT, render

ROOT = Path(__file__).resolve().parent
DEFAULT_SERVER = Path(__file__).resolve().parent / "llama.cpp" / "bin" / "llama-server.exe"

PERSONAS = {   # insertion order = speaking order; solidarity_us opens
    "solidarity_us": {"port": 8081, "label": "SOLIDARITÄT (USA)"},
    "ddr":           {"port": 8082, "label": "DDR"},
}
MODES = {      # thresh = minimum relative p(interrupt); None = never interrupt
    "polite": dict(thresh=None, min_chars=0),
    "free":   dict(thresh=0.6,  min_chars=60),
    "chaos":  dict(thresh=0.25, min_chars=40),
}
SENT_END = re.compile(r'[.!?…]["“”)]*\s*$')
SENT_BOUNDARY = re.compile(r'[.!?…]+["“”)\]]*(?=\s|$)')
COLORS = {"solidarity_us": "\033[92m", "ddr": "\033[91m"}
RESET = "\033[0m"
client = None
OPTS = None
IDS = {}            # persona -> (interrupt token id, wait token id)
_raw_printed = False
SESSION = False     # JSON-lines protocol for the web frontend
STDIN_QUEUE = None

FALLBACK_SCENARIOS = [
    "Darf ich die Schule abbrechen?",
    "Soll es eine Wehrpflicht geben?",
    "Darf ich meinen Beruf frei wählen?",
    "Soll der Staat mir sagen, wo ich wohne?",
    "Darf ich reisen, wohin ich will?",
    "Soll ich für die Gemeinschaft arbeiten, auch wenn es mir nicht gefällt?",
    "Darf der Staat meine Briefe lesen?",
    "Soll die Zeitung schreiben dürfen, was sie will?",
    "Was ist wichtiger: Sicherheit oder Freiheit?",
    "Darf der Chef bestimmen, was ich in meiner Freizeit tue?",
    "Soll ich mich einer Gewerkschaft anschließen?",
    "Darf ich demonstrieren, wenn es anderen nicht passt?",
    "Muss ich für andere sorgen, auch wenn ich sie nicht kenne?",
    "Soll der Staat Wohnungen verteilen?",
    "Darf ich sagen, was ich denke, auch wenn es unbequem ist?",
    "Soll die Gemeinschaft entscheiden, was für mich gut ist?",
]
MODERATOR_RE = re.compile(r"<\|im_start\|>Moderator\n(.*?)<\|im_end\|>", re.DOTALL)

AGREE_OPENERS = ["Wir sind uns einig:", "Darin stimmen wir überein:", "Gemeinsam sagen wir:"]
DISAGREE_OPENERS = ["Wir bleiben uneins, aber", "Wir sehen es verschieden, doch"]
FALLBACK_INTERRUPT_OPENERS = ["Moment,", "Das stimmt so nicht,", "Halt,", "Nein,"]

FALLBACK_LINES = {
    "solidarity_us": [
        "Wir müssen genauer hinhören, was hier wirklich gesagt wird.",
        "Freiheit beginnt damit, dass wir einander zuhören.",
        "Das ist kein Streit über Worte, sondern über unser Zusammenleben.",
    ],
    "ddr": [
        "Wir bleiben bei der Sache. Ordnung und Sicherheit sind keine Nebensachen.",
        "Das Gespräch braucht Klarheit, nicht Ausflüchte.",
        "Die Gemeinschaft verlangt Verantwortung, nicht leere Worte.",
    ],
    MODERATOR: [
        "Ich möchte an dieser Stelle eine klare Antwort.",
        "Bleiben wir bei der Frage: Wie stehen Sie dazu?",
        "Bitte begründen Sie Ihre Position.",
    ],
}

def extract_moderator(prompt):
    m = MODERATOR_RE.search(prompt)
    return m.group(1).strip() if m else None

def load_scenarios():
    found, seen = [], set()
    for path in sorted((ROOT / "data").glob("test_*.jsonl")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    scenario = extract_moderator(row.get("prompt", ""))
                    if scenario and scenario not in seen:
                        seen.add(scenario)
                        found.append(scenario)
        except OSError:
            continue
    if len(found) < 8:
        found = list(FALLBACK_SCENARIOS)
    random.shuffle(found)
    return found

def _interrupt_opener(completion):
    s = completion[len(INTERRUPT):].strip()
    head = s.split(",", 1)[0]
    if "," in s:
        head += ","
    words = head.split()
    if len(words) > 2:
        words = words[:2]
    return " ".join(words)

def load_interrupt_openers():
    counts = Counter()
    for path in sorted((ROOT / "data").glob("train_*.jsonl")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    completion = row.get("completion", "")
                    if completion.startswith(INTERRUPT):
                        opener = _interrupt_opener(completion)
                        if opener:
                            counts[opener] += 1
        except OSError:
            continue
    openers = [opener for opener, _ in counts.most_common(6)]
    return openers or list(FALLBACK_INTERRUPT_OPENERS)

SCENARIOS = load_scenarios()
INTERRUPT_OPENERS = load_interrupt_openers()

ANGRY_LINES = {
    "solidarity_us": [
        "Ihr hört nie zu. Wir gehen.",
        "So redet man nicht mit Menschen. Wir sind hier fertig.",
        "Ihr wollt nur Recht haben, nicht gemeinsam weiterkommen. Wir gehen.",
        "Wir haben es ernst gemeint, ihr nicht. Das war's.",
        "Wer uns nicht zuhört, braucht uns auch nicht. Wir gehen.",
        "Wir lassen uns nicht länger vorführen. Wir sind raus.",
        "Ihr macht aus jedem Gespräch ein Tribunal. Wir gehen.",
        "Genug geredet. Wir nehmen unsere Leute und gehen.",
    ],
    "ddr": [
        "Mit dir ist keine Gesellschaft zu machen. Ich bin fertig.",
        "Du verwechselst Freiheit mit Beliebigkeit. Ich beende das hier.",
        "So wird das nichts. Ich habe keine Zeit für Theater.",
        "Deine Argumente sind laut, nicht tragfähig. Ich bin fertig.",
        "Ich habe dir zugehört. Mehr war nicht zu erwarten.",
        "Ordnung beginnt beim Zuhören. Daran fehlt es dir. Ich gehe.",
        "Das Gespräch ist an seinem Ende. Ich bin es auch.",
        "Du willst keine Lösung, du willst eine Bühne. Ich bin fertig.",
    ],
}

DISAGREE_LINES = {
    "solidarity_us": [
        "Wir bleiben uneins, doch niemand soll dafür schweigen müssen.",
        "Wir sehen es anders, aber wir hören einander weiter zu.",
        "Ein Streit ist kein Ende, solange wir im Gespräch bleiben.",
        "Wir sind nicht einer Meinung, und das muss auch sein dürfen.",
        "Wir halten den Respekt, auch wenn der Konsens fehlt.",
    ],
    "ddr": [
        "Wir sehen es verschieden, aber die Gesellschaft braucht auch deine Stimme.",
        "Einigkeit ist nicht nötig, um miteinander zu reden.",
        "Ich bleibe bei meiner Auffassung, ohne dich deshalb zu verachten.",
        "Verschiedene Wege können beide ehrlich sein.",
        "Wir müssen nicht übereinstimmen, um einander ernst zu nehmen.",
    ],
}


# ---------- pure helpers ----------
def window(transcript, scenario, start, k=2):
    tail = list(transcript[start:])
    if k > 0:
        tail = tail[-k:]
    return [(MODERATOR, scenario)] + tail

def split_sentences(text):
    return [p.strip() for p in re.split(r'(?<=[.!?…])\s+', text.strip()) if p.strip()]

def sentence_ends(text):
    return [m.end() for m in SENT_BOUNDARY.finditer(text.rstrip())]

def count_sentences(text):
    return len(sentence_ends(text))

def needs_space(text, piece):
    return bool(text and piece and text[-1] in ".!?" and piece[0].isalpha())

def trim_to_last_sentence(text):
    stripped = text.rstrip()
    ends = sentence_ends(stripped)
    if not ends:
        return stripped.strip()
    return stripped[:ends[-1]].strip()

def trim_to_sentences(text, limit):
    stripped = text.rstrip()
    ends = sentence_ends(stripped)
    if len(ends) <= limit:
        return stripped.strip()
    return stripped[:ends[limit - 1]].strip()

def valid_weave(text, opener):
    text = text.strip()
    return text.startswith(opener) and len(text) >= 15

def looks_like_assistant(text):
    low = text.lower()
    if "**" in text or "##" in text or "§" in text or "abs." in low or " thinking" in low:
        return True
    if low.lstrip().startswith(("okay", "sure", "here", "the user", "hier die", "natürlich", "gerne")):
        return True
    words = set(re.findall(r"\b[a-z]+\b", low))
    return len(words & {"the", "user", "is", "asking", "they", "quotes"}) >= 2

def _words(s):
    return re.findall(r"[a-zäöüß0-9]+", s.lower())

def trigrams(s):
    w = _words(s)
    return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}

def is_repeat_sentence(sentence, recent, threshold=0.6):
    w = _words(sentence)
    if len(w) < 4:
        return False
    grams = trigrams(sentence)
    if not grams:
        return False
    for other in recent:
        other_grams = trigrams(other)
        if other_grams and len(grams & other_grams) / len(grams) >= threshold:
            return True
    return False

def recent_sentences(transcript, turns=6):
    out = []
    for _, txt in transcript[-turns:]:
        out.extend(split_sentences(txt))
    return out

def decide_outcome(mode, prob=None, strikes=0, patience=2, accept=0.35, rng=None, first_round=False):
    rng = rng or random
    if mode == "agree":
        return "agree", strikes
    if mode == "disagree":
        return "disagree", strikes
    if mode == "angry":
        return "angry", strikes
    if mode == "random":
        r = rng.random()
        if r < 0.5:
            return "agree", strikes
        if first_round:
            return "disagree", strikes
        if r < 0.8:
            return "disagree", strikes
        return "angry", strikes
    accepted = prob is not None and prob < accept
    if accepted:
        return "agree", strikes
    strikes += 1
    return ("disagree" if strikes < patience else "angry"), strikes

def rage_triggered(flags, rage):
    return len(flags) >= 4 and sum(flags[-4:]) >= rage

def scenario_pool(topic):
    pool = [s for s in SCENARIOS if s != topic]
    random.shuffle(pool)
    return pool


# ---------- launching the servers ----------
def find_model(persona, override):
    if override:
        return Path(override)
    folder = ROOT / "out" / persona
    for pattern in ("*Q4_K_M.gguf", "*f16.gguf", "*.gguf"):
        hits = sorted(folder.glob(pattern))
        if hits:
            return hits[0]
    raise SystemExit(f"No GGUF found in {folder}. Pass --{persona.split('_')[0]}-model to choose one.")

def wait_for_server(process, base_url, timeout, log_file):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.flush(); log_file.seek(0)
            raise RuntimeError(f"llama-server exited with code {process.returncode}.\n{log_file.read()[-4000:]}")
        try:
            with urlopen(f"{base_url}/health", timeout=1) as r:
                if r.status == 200:
                    return
        except OSError:                 # not up yet, or still answering 503 while loading
            time.sleep(1)
    raise RuntimeError(f"{base_url} not ready after {timeout}s. Try a smaller --context.")

def launch_servers(a, stack):
    server = Path(a.server)
    if not server.is_file():
        raise SystemExit(f"llama-server not found at {server}. Pass --server.")
    overrides = {"solidarity_us": a.solidarity_model, "ddr": a.ddr_model}
    for persona, info in PERSONAS.items():
        model = find_model(persona, overrides[persona]).resolve()
        cmd = [str(server), "--model", str(model), "--host", "127.0.0.1", "--port", str(info["port"]),
               "--ctx-size", str(a.context), "--n-gpu-layers", str(a.gpu_layers), "--parallel", "1"]
        if a.threads:
            cmd += ["--threads", str(a.threads)]
        print(f"Starting {persona}: {model.name} on port {info['port']}")
        log = stack.enter_context(open(f"llama-server-{persona}.log", "w+", encoding="utf-8"))
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        stack.callback(_stop, proc)
        info["proc"], info["log"] = proc, log
    for persona, info in PERSONAS.items():   # both load at the same time, then wait for each
        wait_for_server(info["proc"], f"http://127.0.0.1:{info['port']}", a.startup_timeout, info["log"])
        print(f"{persona} ready")

def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()


# ---------- talking to the servers ----------
def url(persona):
    return f"http://127.0.0.1:{PERSONAS[persona]['port']}"

def clean(s):
    return s.replace(INTERRUPT, "").replace(WAIT, "")

def other(persona):
    return next(p for p in PERSONAS if p != persona)

async def check_response(response, operation):
    if response.is_error:
        body = (await response.aread()).decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"{operation} failed with HTTP {response.status_code}: "
            f"{body or response.reason_phrase}"
        )

def sampling_params(temperature=None, with_stop=True):
    d = {
        "temperature": OPTS.temperature if temperature is None else temperature,
        "top_p": 0.9,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
        "repeat_last_n": 512,
        "dry_multiplier": OPTS.dry,
        "dry_base": 1.75,
        "dry_allowed_length": 3,
        "dry_penalty_last_n": 64,
    }
    if with_stop:
        d["stop"] = ["<|im_end|>", "\n\n", "---", "**", "##", " thinking"]
    return d

async def tokenize(persona, content):
    r = await client.post(url(persona) + "/tokenize", json={"content": content, "parse_special": True})
    await check_response(r, f"{persona} tokenization")
    return r.json().get("tokens", [])

async def load_token_ids():
    for persona in PERSONAS:
        ids = []
        for tok in (INTERRUPT, WAIT):
            r = await client.post(url(persona) + "/tokenize", json={"content": tok, "parse_special": True})
            await check_response(r, f"{persona} tokenization")
            toks = r.json()["tokens"]
            if len(toks) != 1:
                raise SystemExit(f"{tok} is {len(toks)} tokens in {persona}'s model, expected 1. "
                                 "The special token did not survive training/export.")
            ids.append(toks[0])
        IDS[persona] = tuple(ids)

async def stream(speaker, prompt, n_predict, temperature=None, seed=None):
    payload = {"prompt": prompt, "stream": True, "n_predict": n_predict, "cache_prompt": True}
    payload.update(sampling_params(temperature))
    if seed is not None:
        payload["seed"] = seed
    async with client.stream("POST", url(speaker) + "/completion", json=payload) as r:
        if r.is_error:
            await check_response(r, f"{speaker} generation")
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            d = json.loads(line[6:])
            if d.get("error"):
                raise RuntimeError(f"{speaker} generation failed: {d['error']}")
            yield clean(d.get("content", ""))
            if d.get("stop"):
                break

def _prob(t):
    if "prob" in t: return t["prob"]
    if "logprob" in t: return math.exp(t["logprob"])
    return 0.0

async def p_interrupt(listener, prompt):
    global _raw_printed
    r = await client.post(url(listener) + "/completion", json={
        "prompt": prompt, "n_predict": 1, "n_probs": 20, "temperature": 0, "cache_prompt": True})
    await check_response(r, f"{listener} interrupt scoring")
    data = r.json()
    if OPTS.debug and not _raw_printed:
        print("\n[raw probs response]", json.dumps(data.get("completion_probabilities"))[:600])
        _raw_printed = True
    cp = data.get("completion_probabilities") or []
    if not cp:
        return 0.0
    entry = cp[0]
    iid, wid = IDS[listener]
    pi = pw = 0.0
    for t in (entry.get("top_logprobs") or entry.get("probs") or []) + [entry]:
        tid, name = t.get("id"), t.get("token") or t.get("tok_str")
        if tid == iid or name == INTERRUPT: pi = max(pi, _prob(t))
        elif tid == wid or name == WAIT:    pw = max(pw, _prob(t))
    return pi / (pi + pw) if pi + pw > 0 else 0.0     # same relative p as in the training eval

async def speak(speaker, listener, ctx, transcript, mode, allow_interrupt):
    prev_sentences = recent_sentences(transcript, 6)
    for attempt in range(3):
        temperature = max(0.0, OPTS.temperature - 0.15 * attempt)
        seed = random.randint(0, 2**31 - 1) if attempt else None
        text = ""
        buffer = ""
        flushed = False
        assistant = False
        cut = False
        done = 0
        checked_end = 0
        prev_end = 0

        async def check_sentences(stripped):
            nonlocal done, checked_end, prev_end, cut
            for e in [x for x in sentence_ends(stripped) if x > checked_end]:
                sentence = stripped[prev_end:e].strip()
                checked_end = e
                if OPTS.repeat_guard and is_repeat_sentence(sentence, prev_sentences, 0.6):
                    return "repeat"
                prev_end = e
                done += 1
                if allow_interrupt and mode["thresh"] is not None and len(stripped[:e]) > mode["min_chars"]:
                    if OPTS.dice is not None:
                        p = random.random() if random.random() < OPTS.dice else 0.0
                    else:
                        p = await p_interrupt(listener, render(ctx, (speaker, stripped[:e]), listener))
                    if OPTS.debug:
                        print(f" [p={p:.2f}]", end="", flush=True)
                    if p > mode["thresh"]:
                        cut = True
                        return "cut"
                if done >= OPTS.max_sentences:
                    return "max"
            return None

        async with aclosing(stream(speaker, render(ctx, next_speaker=speaker), OPTS.tokens,
                                    temperature, seed)) as gen:
            async for piece in gen:
                text += piece
                if not flushed:
                    buffer += piece
                    if len(buffer) < 30:
                        continue
                    if looks_like_assistant(buffer):
                        assistant = True
                        break
                    print(buffer, end="", flush=True)
                    flushed = True
                else:
                    before = text[:-len(piece)] if piece else text
                    if needs_space(before, piece):
                        print(" ", end="", flush=True)
                    print(piece, end="", flush=True)
                action = await check_sentences(text.rstrip())
                if action == "repeat":
                    text = text.rstrip()[:prev_end]
                    return trim_to_last_sentence(text), False
                if action in ("cut", "max"):
                    text = text.rstrip()[:prev_end]
                    break
        if assistant:
            continue
        if not flushed:
            if looks_like_assistant(buffer):
                continue
            print(buffer, end="", flush=True)
            flushed = True
            action = await check_sentences(text.rstrip())
            if action == "repeat":
                text = text.rstrip()[:prev_end]
                return trim_to_last_sentence(text), False
            if action in ("cut", "max"):
                text = text.rstrip()[:prev_end]
        if not text.strip():
            continue
        return trim_to_last_sentence(text), cut
    line = random.choice(FALLBACK_LINES[speaker])
    print(line, end="", flush=True)
    return line, False

async def objection(speaker, listener, ctx, partial):
    opener = random.choice(INTERRUPT_OPENERS)
    prompt = render(ctx, (speaker, partial), listener) + INTERRUPT + opener
    print(opener, end="", flush=True)
    for attempt in range(3):
        temperature = max(0.0, OPTS.temperature - 0.15 * attempt)
        seed = random.randint(0, 2**31 - 1) if attempt else None
        out = opener
        buffer = ""
        flushed = False
        assistant = False
        async with aclosing(stream(listener, prompt, 60, temperature, seed)) as gen:
            async for piece in gen:
                out += piece
                if not flushed:
                    buffer += piece
                    if len(buffer) < 30:
                        continue
                    if looks_like_assistant(buffer):
                        assistant = True
                        break
                    print(buffer, end="", flush=True)
                    flushed = True
                    if count_sentences(out) >= 2:
                        break
                    continue
                before = out[:-len(piece)] if piece else out
                if needs_space(before, piece):
                    print(" ", end="", flush=True)
                print(piece, end="", flush=True)
                if count_sentences(out) >= 2:
                    break
        if assistant:
            continue
        if not flushed:
            if looks_like_assistant(buffer):
                continue
            print(buffer, end="", flush=True)
        if not out.strip() or out.strip() == opener.strip():
            continue
        return trim_to_sentences(out, 2)
    line = random.choice(FALLBACK_LINES[listener])
    print(line, end="", flush=True)
    return (opener + " " + line).strip()

async def continue_after_interrupt(speaker, ctx, partial, n_predict=8):
    prompt = render(ctx, next_speaker=speaker) + partial
    extra = ""
    async with aclosing(stream(speaker, prompt, n_predict, max(0.0, OPTS.temperature - 0.1))) as gen:
        async for piece in gen:
            extra += piece
    extra = clean(extra).strip()
    if not extra or looks_like_assistant(extra):
        return ""
    if needs_space(partial, extra):
        extra = " " + extra
    print(extra, end="", flush=True)
    return extra


# ---------- joint text and round outcomes ----------
async def weave(scenario, transcript, start, order, mix_every=1, temperature=None, joint_sentences=None, opener=None):
    ctx = window(transcript, scenario, start, k=2)
    prefix, end_ids = {}, {}
    for p in PERSONAS:
        prefix[p] = await tokenize(p, render(ctx, next_speaker=p))
        ids = await tokenize(p, "<|im_end|>")
        end_ids[p] = ids[0] if ids else None
    opener = opener or random.choice(AGREE_OPENERS)
    gen_ids = list(await tokenize(order[0], opener))
    text = opener
    limit = OPTS.joint_sentences if joint_sentences is None else joint_sentences
    print("\n\n\u2014 Einigung \u2014")
    print(opener, end="", flush=True)
    for i in range(OPTS.tokens):
        who = order[(i // max(1, mix_every)) % 2]
        payload = {"prompt": prefix[who] + gen_ids, "n_predict": 1, "cache_prompt": True, "return_tokens": True}
        payload.update(sampling_params(temperature, with_stop=False))
        r = await client.post(url(who) + "/completion", json=payload)
        await check_response(r, f"{who} joint generation (prompt tokens: {len(prefix[who]) + len(gen_ids)})")
        d = r.json()
        if d.get("stopped_eos") or d.get("stop_type") == "eos":
            break
        toks = d.get("tokens") or []
        piece = d.get("content", "")
        if not toks:
            if not piece:
                break
            toks = await tokenize(who, piece)
        if not toks:
            break
        if end_ids.get(who) in toks:
            break
        gen_ids.extend(toks)
        piece = clean(piece)
        if piece:
            if needs_space(text, piece):
                print(" ", end="", flush=True)
            text += piece
            print(f"{COLORS[who]}{piece}{RESET}", end="", flush=True)
        if "\n\n" in text or "---" in text:
            break
        if count_sentences(text) >= limit:
            break
    print()
    if not text.strip():
        raise RuntimeError(
            "Joint generation returned no text. Both models stopped before producing a response."
        )
    return text.strip()

def print_scripted(lines, order):
    for p in order:
        print(f"{COLORS[p]}[{PERSONAS[p]['label']}] {random.choice(lines[p])}{RESET}")

def print_fallback(lines, order):
    print("\n\n", end="")
    print_scripted(lines, order)

def angry_exit(next_speaker):
    print_fallback(ANGRY_LINES, [next_speaker, other(next_speaker)])

def last_statement_index(transcript, persona):
    for index in range(len(transcript) - 1, -1, -1):
        if transcript[index][0] == persona:
            return index
    return None


async def evaluate_stance(transcript, scenario, start):
    """Agree only when both personas accept the other's latest statement."""
    if not IDS:
        return "disagree"
    accept = getattr(OPTS, "accept", 0.35)
    for persona in PERSONAS:
        other_persona = other(persona)
        index = last_statement_index(transcript, other_persona)
        if index is None:
            return "disagree"
        ctx = window(transcript[:index], scenario, start, k=2)
        prob = await p_interrupt(persona, render(ctx, (other_persona, transcript[index][1]), persona))
        if getattr(OPTS, "debug", False):
            print(f"\n\n[{persona} Stimmung p={prob:.2f}]")
        if prob >= accept:
            return "disagree"
    return "agree"


async def evaluate_human_stance(human, ai, transcript, start):
    """Agree when the AI accepts the human's latest statement."""
    if not IDS:
        return "disagree"
    index = last_statement_index(transcript, human)
    if index is None:
        return "disagree"
    ctx = window(transcript[:index], OPTS.topic, start, k=2)
    prob = await p_interrupt(ai, render(ctx, (human, transcript[index][1]), ai))
    if getattr(OPTS, "debug", False):
        print(f"\n\n[{ai} Stimmung p={prob:.2f}]")
    return "agree" if prob < getattr(OPTS, "accept", 0.35) else "disagree"


async def finalize_outcome(scenario, transcript, start, next_speaker, decision):
    order = [next_speaker, other(next_speaker)]
    if decision == "agree":
        opener = random.choice(AGREE_OPENERS)
        joint = await weave(scenario, transcript, start, order, mix_every=OPTS.mix_every,
                            opener=opener)
        if not valid_weave(joint, opener) or looks_like_assistant(joint):
            print_fallback(FALLBACK_LINES, order)
        print("\n\n[Einigung erreicht]")
        return
    if decision == "disagree":
        opener = random.choice(DISAGREE_OPENERS)
        joint = await weave(scenario, transcript, start, order, mix_every=OPTS.mix_every,
                            joint_sentences=1, opener=opener)
        if not valid_weave(joint, opener) or looks_like_assistant(joint):
            print_fallback(DISAGREE_LINES, order)
        print("\n\n[Einigung: uneinig, aber respektvoll]")
        return
    angry_exit(next_speaker)
    print("\n\n[Abbruch: Streit eskaliert]")


async def resolve_round(scenario, transcript, start, next_speaker, strikes, first_round=False):
    if OPTS.outcome == "auto":
        decision = await evaluate_stance(transcript, scenario, start)
        if decision == "agree":
            await finalize_outcome(scenario, transcript, start, next_speaker, "agree")
            return "agree", strikes
        strikes += 1
        if strikes >= getattr(OPTS, "patience", 4):
            await finalize_outcome(scenario, transcript, start, next_speaker, "disagree")
            return "disagree", strikes
        if OPTS.debug:
            print(f"\n\n[Runde ohne Einigung: {strikes}/{getattr(OPTS, 'patience', 4)}]")
        return "continue", strikes

    decision, strikes = decide_outcome(OPTS.outcome, None, strikes, OPTS.patience, OPTS.accept,
                                       first_round=first_round)
    await finalize_outcome(scenario, transcript, start, next_speaker, decision)
    return decision, strikes


# ---------- the debate ----------
async def debate():
    global client
    mode = MODES[OPTS.mode]
    async with httpx.AsyncClient(timeout=None) as client:
        await load_token_ids()
        scenario = OPTS.topic
        transcript = [(MODERATOR, scenario)]
        start = len(transcript)
        speaker, listener = list(PERSONAS)
        just_interrupted = False
        last_interrupt_turn = -OPTS.cooldown - 1
        strikes = 0
        pool = scenario_pool(scenario)
        turn = 0
        round_turns = 0
        round_index = 0
        print(f"\n=== {OPTS.topic} ({OPTS.mode}) ===")
        while turn < OPTS.turns:
            ctx = window(transcript, scenario, start, 4)
            allow_interrupt = (not just_interrupted) and (turn - last_interrupt_turn > OPTS.cooldown)
            print(f"\n\n[{PERSONAS[speaker]['label']}] ", end="", flush=True)
            text, cut = await speak(speaker, listener, ctx, transcript, mode, allow_interrupt)
            if cut:
                text += await continue_after_interrupt(speaker, ctx, text)
            transcript.append((speaker, text))
            if cut:
                last_interrupt_turn = turn
                print(" —", end="")
                print(f"\n\n[{PERSONAS[listener]['label']}] ", end="", flush=True)
                transcript.append((listener, await objection(speaker, listener, ctx, text)))
                just_interrupted = True
            else:
                just_interrupted = False
                speaker, listener = listener, speaker
            turn += 1
            round_turns += 1

            if OPTS.agree:
                if round_turns >= 2:
                    round_turns = 0
                    decision, strikes = await resolve_round(
                        scenario, transcript, start, speaker, strikes,
                        first_round=(round_index == 0),
                    )
                    round_index += 1
                    if decision in ("agree", "disagree", "angry"):
                        return
            else:
                round_done = (OPTS.rotate > 0 and round_turns >= OPTS.rotate) or (turn >= OPTS.turns)
                if round_done:
                    round_turns = 0
                    if turn < OPTS.turns:
                        nxt = pool.pop() if pool else None
                        if nxt:
                            scenario = nxt
                            transcript.append((MODERATOR, scenario))
                            start = len(transcript)
                            just_interrupted = False
                            print(f"\n\n[Moderator] {scenario}")
        if OPTS.agree:
            if round_turns > 0:
                decision, strikes = await resolve_round(
                    scenario, transcript, start, speaker, strikes,
                    first_round=(round_index == 0),
                )
                if decision in ("agree", "disagree", "angry"):
                    return
            await finalize_outcome(scenario, transcript, start, speaker, "disagree")
        print()


# ---------- session protocol (web frontend) ----------
def emit(event):
    """Write one NDJSON event. Only active in --session mode."""
    if not SESSION:
        return
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read_stdin(loop, queue):
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                loop.call_soon_threadsafe(queue.put_nowait, message)
    except (OSError, ValueError):
        pass
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "eof"})


async def wait_command(seconds, allow_agree=True):
    """Wait for the next input/agree/end command, or return None on timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        try:
            message = await asyncio.wait_for(STDIN_QUEUE.get(), timeout=remaining)
        except asyncio.TimeoutError:
            return None
        kind = message.get("type")
        if kind == "eof":
            return {"type": "end"}
        if kind == "end":
            return message
        if kind == "agree":
            if allow_agree:
                return message
            continue
        if kind == "input":
            return message


async def collect_text(speaker, prompt, n_predict=None, temperature=None):
    out = []
    async with aclosing(stream(speaker, prompt, n_predict or OPTS.tokens, temperature)) as gen:
        async for piece in gen:
            if piece:
                out.append(piece)
    return clean("".join(out)).strip()


async def session_suggestion(model, transcript, start):
    try:
        ctx = window(transcript, OPTS.topic, start, 4)
        prompt = render(ctx, next_speaker=model)
        text = await collect_text(model, prompt, 60, max(0.4, OPTS.temperature - 0.2))
    except Exception:
        return
    text = trim_to_sentences(text, 2)
    if text and not looks_like_assistant(text):
        emit({"type": "suggestion", "speaker": model, "text": text})


async def session_ai_turn(speaker, transcript, start, section="turn", n_predict=None,
                          human=False, auto=False):
    ctx = window(transcript, OPTS.topic, start, 4)
    event = {
        "type": "turn_start",
        "speaker": speaker,
        "label": PERSONAS[speaker]["label"],
        "section": section,
    }
    if human:
        event["human"] = True
    if auto:
        event["auto"] = True
    emit(event)
    prompt = render(ctx, next_speaker=speaker)
    text = ""
    async with aclosing(stream(speaker, prompt, n_predict or OPTS.tokens)) as gen:
        async for piece in gen:
            if not piece:
                continue
            text += piece
            emit({"type": "delta", "speaker": speaker, "text": piece, "section": section})
    text = clean(text).strip()
    if not text:
        text = random.choice(FALLBACK_LINES[speaker])
        emit({"type": "delta", "speaker": speaker, "text": text, "section": section, "fallback": True})
    transcript.append((speaker, text))
    return text


async def session_human_turn(role, speaker, transcript, start, section="turn",
                             allow_suggestion=False, suggestion_model=None):
    label = PERSONAS[speaker]["label"] if speaker in PERSONAS else speaker
    emit({
        "type": "turn_start",
        "speaker": speaker,
        "label": label,
        "section": section,
        "human": True,
    })
    emit({
        "type": "await_input",
        "speaker": speaker,
        "label": label,
        "seconds": OPTS.turn_seconds,
        "allow_agree": True,
        "suggestions": bool(allow_suggestion and OPTS.suggestions),
    })
    task = None
    if allow_suggestion and OPTS.suggestions:
        task = asyncio.create_task(session_suggestion(suggestion_model or role, transcript, start))
    try:
        message = await wait_command(OPTS.turn_seconds, allow_agree=True)
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    if message is not None and message.get("type") == "agree":
        emit({"type": "outcome", "outcome": "agree"})
        return "agree"
    if message is not None and message.get("type") == "end":
        return "end"
    if message is None:
        emit({"type": "timeout", "speaker": speaker})
        text = random.choice(FALLBACK_LINES.get(role) or FALLBACK_LINES["solidarity_us"])
        emit({"type": "delta", "speaker": speaker, "text": text, "section": section, "auto": True})
        transcript.append((role, text))
        return "timeout"
    text = str(message.get("text", "")).strip()
    if not text:
        emit({"type": "timeout", "speaker": speaker})
        text = random.choice(FALLBACK_LINES.get(role) or FALLBACK_LINES["solidarity_us"])
        emit({"type": "delta", "speaker": speaker, "text": text, "section": section, "auto": True})
        transcript.append((role, text))
        return "timeout"
    emit({"type": "delta", "speaker": speaker, "text": text, "section": section})
    transcript.append((role, text))
    return "input"


async def session_human_vs_ai(quick=False):
    human = OPTS.human_persona or "ddr"
    ai = other(human)
    transcript = [(MODERATOR, OPTS.topic)]
    start = 1
    emit({"type": "topic", "topic": OPTS.topic, "mode": "quick" if quick else "human_vs_ai"})
    rounds = 4 if quick else max(1, OPTS.exchanges)
    patience = getattr(OPTS, "patience", 4)
    strikes = 0
    for _ in range(rounds):
        result = await session_human_turn(human, human, transcript, start,
                                          allow_suggestion=True, suggestion_model=human)
        if result in ("agree", "end"):
            return
        await session_ai_turn(ai, transcript, start)
        decision = await evaluate_human_stance(human, ai, transcript, start)
        if decision == "agree":
            emit({"type": "outcome", "outcome": "agree"})
            return
        strikes += 1
        if not quick and strikes >= patience:
            emit({"type": "outcome", "outcome": "disagree"})
            return
    if quick:
        emit({"type": "status", "state": "closing", "text": "Abschlussstatements"})
        await session_ai_turn(ai, transcript, start, section="closing")
        await session_ai_turn(human, transcript, start, section="closing", human=True, auto=True)
    emit({"type": "outcome", "outcome": "disagree"})


async def session_human_vs_both():
    transcript = [(MODERATOR, OPTS.topic)]
    start = 1
    emit({"type": "topic", "topic": OPTS.topic, "mode": "human_vs_both"})
    patience = getattr(OPTS, "patience", 4)
    strikes = 0
    for _ in range(max(1, OPTS.exchanges)):
        result = await session_human_turn(MODERATOR, "human", transcript, start,
                                          allow_suggestion=False)
        if result in ("agree", "end"):
            return
        for speaker in PERSONAS:
            await session_ai_turn(speaker, transcript, start)
        decision = await evaluate_stance(transcript, OPTS.topic, start)
        if decision == "agree":
            emit({"type": "outcome", "outcome": "agree"})
            return
        strikes += 1
        if strikes >= patience:
            emit({"type": "outcome", "outcome": "disagree"})
            return
    emit({"type": "outcome", "outcome": "disagree"})


async def session_moderator():
    transcript = [(MODERATOR, OPTS.topic)]
    start = 1
    emit({"type": "topic", "topic": OPTS.topic, "mode": "moderator"})
    patience = getattr(OPTS, "patience", 4)
    strikes = 0
    for _ in range(max(1, OPTS.exchanges)):
        result = await session_human_turn(MODERATOR, "moderator", transcript, start,
                                          allow_suggestion=False)
        if result in ("agree", "end"):
            return
        for speaker in PERSONAS:
            await session_ai_turn(speaker, transcript, start)
        decision = await evaluate_stance(transcript, OPTS.topic, start)
        if decision == "agree":
            emit({"type": "outcome", "outcome": "agree"})
            return
        strikes += 1
        if strikes >= patience:
            emit({"type": "outcome", "outcome": "disagree"})
            return
    emit({"type": "outcome", "outcome": "disagree"})


async def session_main():
    global client, STDIN_QUEUE
    loop = asyncio.get_running_loop()
    STDIN_QUEUE = asyncio.Queue()
    threading.Thread(target=_read_stdin, args=(loop, STDIN_QUEUE), daemon=True).start()
    emit({"type": "status", "state": "starting", "text": "Server werden vorbereitet"})
    async with httpx.AsyncClient(timeout=None) as http:
        client = http
        try:
            await load_token_ids()
        except (Exception, SystemExit) as exc:
            emit({"type": "error", "text": f"Stimmungsanalyse nicht verfügbar: {exc}"})
            emit({"type": "end", "status": "error", "exit_code": 1})
            return
        emit({"type": "status", "state": "running", "text": "Debatte läuft"})
        try:
            if OPTS.session_mode == "quick":
                await session_human_vs_ai(quick=True)
            elif OPTS.session_mode == "human_vs_both":
                await session_human_vs_both()
            elif OPTS.session_mode == "moderator":
                await session_moderator()
            else:
                await session_human_vs_ai()
        except Exception as exc:
            emit({"type": "error", "text": str(exc)})
            emit({"type": "end", "status": "error", "exit_code": 1})
            return
    emit({"type": "end", "status": "done", "exit_code": 0})


def settings_summary():
    return (f"[settings] mode={OPTS.mode} turns={OPTS.turns} rotate={OPTS.rotate} agree={OPTS.agree} "
            f"outcome={OPTS.outcome} temperature={OPTS.temperature} dry={OPTS.dry} "
            f"max_sentences={OPTS.max_sentences} tokens={OPTS.tokens} repeat_guard={OPTS.repeat_guard} cooldown={OPTS.cooldown} "
            f"mix_every={OPTS.mix_every} joint_sentences={OPTS.joint_sentences} accept={OPTS.accept} "
            f"attempts={OPTS.attempts} patience={OPTS.patience} rage={OPTS.rage} dice={OPTS.dice}")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--mode", choices=MODES, default="free")
    ap.add_argument("--turns", type=int, default=7)
    ap.add_argument("--dice", type=float, default=None, help="random interrupts with this chance, ignores the model")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--server", default=str(DEFAULT_SERVER))
    ap.add_argument("--ddr-model"); ap.add_argument("--solidarity-model")
    ap.add_argument("--no-launch", action="store_true", help="servers already running on 8081/8082")
    ap.add_argument("--context", type=int, default=4096)
    ap.add_argument("--tokens", type=int, default=160, help="max tokens per turn")
    ap.add_argument("--gpu-layers", type=int, default=99)
    ap.add_argument("--threads", type=int, default=0, help="CPU threads per server (0 = llama.cpp default)")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--startup-timeout", type=int, default=300)
    ap.add_argument("--dry", type=float, default=0.8, help="DRY sampling multiplier (0 = off)")
    ap.add_argument("--max-sentences", type=int, default=2)
    ap.add_argument("--cooldown", type=int, default=3)
    ap.add_argument("--rotate", type=int, default=0, help="turns per scenario (0 = stay on the requested topic)")
    ap.add_argument("--repeat-guard", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--agree", action="store_true", default=True, help="auto-resolve by stance each round")
    ap.add_argument("--no-agree", dest="agree", action="store_false")
    ap.add_argument("--mix-every", type=int, default=1)
    ap.add_argument("--joint-sentences", type=int, default=3)
    ap.add_argument("--accept", type=float, default=0.35)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--rage", type=int, default=3)
    ap.add_argument("--outcome", choices=("auto", "agree", "disagree", "angry", "random"), default="auto")
    ap.add_argument("--session", action="store_true", help="JSON-lines session protocol for the web frontend")
    ap.add_argument("--session-mode", choices=("human_vs_ai", "human_vs_both", "moderator", "quick"),
                    default="human_vs_ai")
    ap.add_argument("--human-persona", choices=tuple(PERSONAS))
    ap.add_argument("--turn-seconds", type=int, default=60)
    ap.add_argument("--exchanges", type=int, default=12, help="maximum human rounds (safety cap)")
    ap.add_argument("--suggestions", action=argparse.BooleanOptionalAction, default=True)
    return ap.parse_args()


if __name__ == "__main__":
    os.system("")
    OPTS = parse_args()
    SESSION = OPTS.session
    if SESSION:
        for handle in (sys.stdin, sys.stdout):
            try:
                handle.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass
    if OPTS.debug and not SESSION:
        print(settings_summary())
    with ExitStack() as stack:
        if not OPTS.no_launch:
            if SESSION:
                with redirect_stdout(sys.stderr):
                    launch_servers(OPTS, stack)
            else:
                launch_servers(OPTS, stack)
        if SESSION:
            asyncio.run(session_main())
        else:
            asyncio.run(debate())
