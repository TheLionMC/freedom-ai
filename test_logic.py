import asyncio
import contextlib
import io
import random
import types
import ochestrator as o

tr = [
    (o.MODERATOR, "Thema"),
    ("solidarity_us", "A1"),
    ("ddr", "B1"),
    ("solidarity_us", "A2"),
    ("ddr", "B2"),
]
assert o.window(tr, "Neu", 1, 2) == [(o.MODERATOR, "Neu"), ("solidarity_us", "A2"), ("ddr", "B2")]
assert o.window(tr, "Neu", 1, 4) == [(o.MODERATOR, "Neu")] + tr[1:]
assert o.window(tr, "Neu", len(tr), 4) == [(o.MODERATOR, "Neu")]

base = "Wir gehen jetzt alle gemeinsam nach Hause"
assert o.is_repeat_sentence(base, [base], 0.6)
assert not o.is_repeat_sentence("Kurzer Satz", [base], 0.6)

a = "der staat darf briefe und telefone überwachen"
b = "der staat darf briefe und telefone kontrollieren"
assert o.is_repeat_sentence(b, [a], 0.6)

c = "der staat darf briefe und telefone überwachen"
d = "der staat schützt briefe und telefone überwachen"
assert not o.is_repeat_sentence(d, [c], 0.6)

assert o.decide_outcome("auto", 0.2, 0, 2, 0.35) == ("agree", 0)
assert o.decide_outcome("auto", 0.35, 0, 2, 0.35) == ("disagree", 1)
assert o.decide_outcome("auto", 0.9, 1, 2, 0.35) == ("angry", 2)
assert o.decide_outcome("agree", None) == ("agree", 0)
assert o.decide_outcome("disagree", None) == ("disagree", 0)
assert o.decide_outcome("angry", None) == ("angry", 0)

class FixedRandom:
    def __init__(self, value):
        self.value = value
    def random(self):
        return self.value

assert o.decide_outcome("random", rng=FixedRandom(0.1))[0] == "agree"
assert o.decide_outcome("random", rng=FixedRandom(0.6))[0] == "disagree"
assert o.decide_outcome("random", rng=FixedRandom(0.9))[0] == "angry"
assert o.decide_outcome("random", rng=FixedRandom(0.9), first_round=True)[0] == "disagree"

assert o.rage_triggered([True, True, True, False], 3)
assert not o.rage_triggered([True, True, False], 3)
assert not o.rage_triggered([True, True, False, False], 3)

assert o.looks_like_assistant("Okay, the user is asking about the meaning of freedom ...")
assert o.looks_like_assistant("Hier die wichtigsten Punkte:")
assert o.looks_like_assistant("**konkrete Veranlassung**")
assert o.looks_like_assistant("(§ 21 Abs. 3 BVerfGE 54, 179)")
assert not o.looks_like_assistant(
    "Solidarität ist keine Nächstenliebe. Solidarität ist das Recht, dass wir gemeinsam auf der Suche nach Freiheit sind."
)
assert not o.looks_like_assistant("Freiheit ohne Ordnung ist Chaos.")

fake_prompt = (
    "<|im_start|>Moderator\nDarf ich die Schule abbrechen?<|im_end|>\n"
    "<|im_start|>solidarity_us\nBildung ist ein Recht.<|im_end|>\n"
    "<|im_start|>ddr\n"
)
assert o.extract_moderator(fake_prompt) == "Darf ich die Schule abbrechen?"
assert o.extract_moderator("no moderator here") is None
assert len(o.SCENARIOS) >= 8

assert o.needs_space("Satz.", "Weiter")
assert o.needs_space("Was?", "Ja")
assert o.needs_space("Halt!", "Nein")
assert not o.needs_space("Satz", "Weiter")
assert not o.needs_space("Satz.", " weiter")
assert not o.needs_space("", "Weiter")


def run_speak(pieces, mode=None, allow_interrupt=False, max_sentences=2, dice=None):
    old_stream = o.stream
    old_opts = o.OPTS

    async def fake_stream(*args, **kwargs):
        for piece in pieces:
            yield piece

    o.stream = fake_stream
    o.OPTS = types.SimpleNamespace(
        temperature=0.8,
        repeat_guard=False,
        max_sentences=max_sentences,
        tokens=160,
        dice=dice,
        debug=False,
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return asyncio.run(o.speak(
                "solidarity_us",
                "ddr",
                [(o.MODERATOR, "Thema")],
                [(o.MODERATOR, "Thema")],
                mode or {"thresh": None, "min_chars": 0},
                allow_interrupt,
            ))
    finally:
        o.stream = old_stream
        o.OPTS = old_opts


first_piece = run_speak(["J", "edes Recht"])
assert first_piece == ("Jedes Recht", False), first_piece

polite = run_speak(["Eins. ", "Zwei. ", "Drei."], mode={"thresh": None, "min_chars": 0},
                   allow_interrupt=True, max_sentences=2)
cooldown = run_speak(["Eins. ", "Zwei. ", "Drei."], mode={"thresh": 0.5, "min_chars": 0},
                     allow_interrupt=False, max_sentences=2)
dice = run_speak(["Eins. ", "Zwei. ", "Drei."], mode={"thresh": 0.5, "min_chars": 0},
                 allow_interrupt=True, max_sentences=2, dice=0.0)
assert polite == ("Eins. Zwei.", False), polite
assert cooldown == ("Eins. Zwei.", False), cooldown
assert dice == ("Eins. Zwei.", False), dice

assert o.trim_to_last_sentence("Eins. Zwei") == "Eins."
assert o.trim_to_last_sentence("Eins. Zwei.") == "Eins. Zwei."
assert o.trim_to_last_sentence("kein Ende") == "kein Ende"
assert o.trim_to_sentences("Moment, eins. zwei. drei.", 2) == "Moment, eins. zwei."
trimmed = run_speak(["Eins. ", "Zwei"], max_sentences=5)
kept = run_speak(["kein ", "Ende"], max_sentences=5)
assert trimmed == ("Eins.", False), trimmed
assert kept == ("kein Ende", False), kept

assert o.valid_weave("Wir sind uns einig: Freiheit braucht Regeln.", "Wir sind uns einig:")
assert o.valid_weave("Wir bleiben uneins, aber respektvoll.", "Wir bleiben uneins, aber")
assert not o.valid_weave("Soziologie sagt uns, dass Freiheit Regeln braucht.", "Wir sind uns einig:")
assert not o.valid_weave("Hi: ok", "Hi:")

fallback_buf = io.StringIO()
with contextlib.redirect_stdout(fallback_buf):
    o.print_fallback(o.DISAGREE_LINES, ["solidarity_us", "ddr"])
fallback_out = fallback_buf.getvalue()
assert fallback_out.startswith("\n\n")
assert o.COLORS["solidarity_us"] in fallback_out
assert o.COLORS["ddr"] in fallback_out

old_stream = o.stream
old_opts = o.OPTS

async def fake_tail(*args, **kwargs):
    yield " Aber"

o.stream = fake_tail
o.OPTS = types.SimpleNamespace(temperature=0.8)
try:
    with contextlib.redirect_stdout(io.StringIO()):
        tail = asyncio.run(o.continue_after_interrupt(
            "solidarity_us", [(o.MODERATOR, "Thema")], "Satz."
        ))
finally:
    o.stream = old_stream
    o.OPTS = old_opts
assert tail == " Aber", tail

assert o.last_statement_index(tr, "ddr") == 4
assert o.last_statement_index(tr, o.MODERATOR) == 0
assert o.last_statement_index([(o.MODERATOR, "Thema")], "ddr") is None

async def check_stance():
    old_ids, old_interrupt, old_opts = o.IDS, o.p_interrupt, o.OPTS
    probs = {"solidarity_us": 0.1, "ddr": 0.1}

    async def fake_p_interrupt(persona, prompt):
        return probs[persona]

    try:
        o.IDS = {"solidarity_us": (1, 2), "ddr": (1, 2)}
        o.p_interrupt = fake_p_interrupt
        o.OPTS = types.SimpleNamespace(accept=0.35, debug=False, topic="Thema")
        assert await o.evaluate_stance(tr, "Thema", 1) == "agree"
        probs["ddr"] = 0.9
        assert await o.evaluate_stance(tr, "Thema", 1) == "disagree"
        probs["ddr"] = 0.1
        assert await o.evaluate_human_stance("ddr", "solidarity_us", tr, 1) == "agree"
        probs["solidarity_us"] = 0.9
        assert await o.evaluate_human_stance("ddr", "solidarity_us", tr, 1) == "disagree"
        o.IDS = {}
        assert await o.evaluate_stance(tr, "Thema", 1) == "disagree"
    finally:
        o.IDS, o.p_interrupt, o.OPTS = old_ids, old_interrupt, old_opts

asyncio.run(check_stance())

print("all logic tests passed")
