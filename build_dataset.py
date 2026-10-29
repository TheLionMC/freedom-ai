import glob, json, re
from collections import Counter
from shared import MODERATOR, INTERRUPT, WAIT, render

PERSONAS = {"solidarity_us", "ddr"}
BANNED = ["es ist wichtig zu beachten", "beide seiten haben", "als ki", "in der tat", "letztendlich"]
SENT_END = re.compile(r'[.!?…]["“”)]*\s*$')
SENT_COUNT = re.compile(r'[.!?…]+(?=\s|$)')
TEST_FRACTION = 0.10
BATCH_SIZE = 50
EXPECTED_TYPES = {"reply": 25, "interrupt": 8, "wait": 17}
EXPECTED_PERSONAS = {"solidarity_us": 25, "ddr": 25}
REQUIRED = {"type", "persona", "scenario", "context", "opponent_partial", "reply"}

def words(text):
    return len(text.split())

def sentences(text):
    return len(SENT_COUNT.findall(text.strip())) if text.strip() else 0

def check(e):
    missing = REQUIRED - set(e)
    if missing:
        return [f"missing fields: {sorted(missing)}"]
    t, p = e["type"], e["persona"]
    if t not in EXPECTED_TYPES or p not in PERSONAS:
        return ["bad type/persona"]

    errs = []
    scenario = e["scenario"] if isinstance(e["scenario"], str) else ""
    r = e["reply"].strip() if isinstance(e["reply"], str) else ""
    part = e["opponent_partial"].strip() if isinstance(e["opponent_partial"], str) else ""
    ctx = e["context"] if isinstance(e["context"], list) else []

    if not scenario.strip(): errs.append("no scenario")
    if not 1 <= len(ctx) <= 4:
        errs.append("context must have 1-4 turns")
    else:
        for turn in ctx:
            if (not isinstance(turn, dict) or turn.get("speaker") not in PERSONAS
                    or not isinstance(turn.get("text"), str) or not turn["text"].strip()):
                errs.append("bad context turn")
                break

    if t == "reply":
        if part: errs.append("reply has partial")
        if not ctx or ctx[-1].get("speaker") == p: errs.append("context must end with opponent turn")
        if not 1 <= sentences(r) <= 3 or words(r) > 50: errs.append("reply length")
    elif t == "interrupt":
        if not part or not SENT_END.search(part) or not 1 <= sentences(part) <= 3:
            errs.append("interrupt partial must be 1-3 finished sentences")
        if not 1 <= sentences(r) <= 3 or words(r) > 25: errs.append("interrupt length")
        if not re.match(r"^(Moment|Das stimmt so nicht|Halt|So nicht|Nein|Falsch)\b", r):
            errs.append("interrupt opener")
    else:
        if not part or not SENT_END.search(part) or not 1 <= sentences(part) <= 3:
            errs.append("wait partial must be 1-3 finished sentences")
        if r: errs.append("wait must have empty reply")

    texts = [scenario, part, r] + [turn.get("text", "") for turn in ctx if isinstance(turn, dict)]
    if any(b in " ".join(texts).lower() for b in BANNED): errs.append("banned phrase")
    return errs

def build(e):
    p = e["persona"]
    opp = next(x for x in PERSONAS if x != p)
    transcript = [(MODERATOR, e["scenario"])] + [(c["speaker"], c["text"]) for c in e["context"]]
    r = e["reply"].strip()
    if e["type"] == "reply":
        prompt, target = render(transcript, next_speaker=p), r
    else:
        prompt = render(transcript, partial=(opp, e["opponent_partial"].strip()), next_speaker=p)
        target = (INTERRUPT + r) if e["type"] == "interrupt" else WAIT
    return {"prompt": prompt, "completion": target + "<|im_end|>", "type": e["type"],
            "persona": p, "scenario": e["scenario"]}

def assign_splits(rows):
    # Split within persona/type, so every test file keeps interrupt and wait examples.
    step = max(1, round(1 / TEST_FRACTION))
    groups = {}
    for row in rows:
        groups.setdefault((row["persona"], row["type"]), []).append(row)
    for group in groups.values():
        for i, row in enumerate(sorted(group, key=lambda r: r["scenario"])):
            row["test"] = i % step == 0

def main():
    seen, seen_scenarios, rows, rejected = set(), set(), [], Counter()
    for f in sorted(glob.glob("data/batch_*.json")):
        with open(f, encoding="utf-8") as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            rejected["batch is not a list"] += 1
            continue
        if len(entries) != BATCH_SIZE:
            rejected["wrong batch size"] += 1
        type_counts = Counter(e.get("type") for e in entries)
        persona_counts = Counter(e.get("persona") for e in entries)
        if dict(type_counts) != EXPECTED_TYPES:
            rejected["wrong type mix"] += 1
        if dict(persona_counts) != EXPECTED_PERSONAS:
            rejected["wrong persona mix"] += 1

        for e in entries:
            if not isinstance(e, dict):
                rejected["entry is not an object"] += 1
                continue
            errs = check(e)
            scenario = e.get("scenario")
            if scenario in seen_scenarios:
                errs.append("duplicate scenario")
            seen_scenarios.add(scenario)
            key = (e.get("persona"), scenario, e.get("reply"), e.get("opponent_partial"))
            if key in seen:
                errs.append("duplicate")
            if errs:
                rejected.update(errs)
                continue
            seen.add(key)
            rows.append(build(e))

    assign_splits(rows)
    for p in PERSONAS:
        for split in ("train", "test"):
            sel = [r for r in rows if r["persona"] == p and r["test"] == (split == "test")]
            with open(f"data/{split}_{p}.jsonl", "w", encoding="utf-8") as out:
                for r in sel:
                    out.write(json.dumps({k: r[k] for k in ("prompt", "completion", "type")}, ensure_ascii=False) + "\n")
            print(p, split, dict(Counter(r["type"] for r in sel)))
    print("rejected:", dict(rejected))

if __name__ == "__main__":
    main()
