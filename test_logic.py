import asyncio
import contextlib
import io
import random
import types
import ochestrator as o
from web.server import OrchestratorParser, RunParams, make_command

tr = [
    (o.MODERATOR, "Thema"),
    ("solidarity_us", "A1"),
    ("ddr", "B1"),
    ("solidarity_us", "A2"),
    ("ddr", "B2"),
]
topic_anchor = o.topic_context("Neu")
assert "Beantworte die Leitfrage direkt" in topic_anchor
obedience_topic = "Ist Gehorsam gegenüber dem Staat manchmal eine Pflicht, manchmal ein Verbrechen?"
assert o.topic_terms(obedience_topic) == ["gehorsam", "staat", "pflicht", "verbrechen"]
assert o.answers_topic(
    "Gehorsam gegenüber dem Staat ist nicht immer Pflicht; bei einem Verbrechen des Staates kann Widerstand geboten sein.",
    obedience_topic,
)
assert not o.answers_topic(
    "Gehorsam ist keine Pflicht, wenn der Staat Unrecht verlangt.", obedience_topic
)
assert not o.answers_topic(
    "Solidarität bedeutet, dass wir gemeinsam die Gesellschaft gestalten.", obedience_topic
)
freedom_help_topic = "Ist man frei, wenn man alles darf, aber niemand einem hilft?"
assert o.answers_topic(
    "Freiheit bleibt leer, wenn Menschen trotz aller Erlaubnisse keine Hilfe bekommen.",
    freedom_help_topic,
)
persecution_topic = "Darf man Verfolgten helfen, auch wenn das gegen die Gesetze verstößt?"
us_persecution_fallback = o.topic_fallback("solidarity_us", persecution_topic)
ddr_persecution_fallback = o.topic_fallback("ddr", persecution_topic)
assert us_persecution_fallback and o.answers_topic(us_persecution_fallback, persecution_topic)
assert ddr_persecution_fallback and o.answers_topic(ddr_persecution_fallback, persecution_topic)
assert us_persecution_fallback != ddr_persecution_fallback
assert o.topic_fallback("ddr", "Eine völlig andere offene Frage?").startswith(("Ich kann", "Ich möchte"))
repeated_topic_line = (
    "Gehorsam gegenüber dem Staat ist nicht immer Pflicht; "
    "bei einem Verbrechen des Staates kann Widerstand geboten sein."
)
assert not o.valid_debate_turn(
    repeated_topic_line,
    obedience_topic,
    [("solidarity_us", repeated_topic_line)],
)
assert o.topic_fallback("solidarity_us", obedience_topic).startswith("Gehorsam gegenüber")
fallback_once = o.topic_fallback("ddr", obedience_topic)
assert o.topic_fallback("ddr", obedience_topic, [("ddr", fallback_once)]) != fallback_once
assert o.explicitly_agrees("Ich stimme dir teilweise zu.")
assert not o.explicitly_agrees("Ich stimme dir nicht zu.")
grounding_transcript = [
    (o.MODERATOR, obedience_topic),
    ("solidarity_us", "Gehorsam gegenüber dem Staat ist keine Pflicht, wenn er Unrecht verlangt."),
    ("ddr", "Gehorsam kann dem Gemeinwohl dienen, solange der Staat das Recht schützt."),
]
assert o.grounded_weave(
    "Darin stimmen wir überein: Gehorsam gegenüber dem Staat braucht klare Grenzen.",
    grounding_transcript,
    obedience_topic,
)
assert not o.grounded_weave(
    "Darin stimmen wir überein: Niemand darf unangemeldet in unsere Häuser gehen.",
    grounding_transcript,
    obedience_topic,
)
assert not o.outcome_check_allowed(1)
assert not o.outcome_check_allowed(2)
assert o.outcome_check_allowed(3)
assert "höchstens einmal" in o.prompt_context("solidarity_us", [], [])[-1][1]
used_solidarity = [("solidarity_us", "Solidarität ist für mich wichtig.")]
assert "nicht erneut" in o.prompt_context("solidarity_us", used_solidarity, [])[-1][1]
assert o.prompt_context("ddr", [], []) == []
assert o.window(tr, "Neu", 1, 2) == [(o.MODERATOR, topic_anchor), ("solidarity_us", "A2"), ("ddr", "B2")]
assert o.window(tr, "Neu", 1, 4) == [(o.MODERATOR, topic_anchor)] + tr[1:]
assert o.window(tr, "Neu", len(tr), 4) == [(o.MODERATOR, topic_anchor)]
assert topic_anchor in o.render(o.window(tr, "Neu", 1, 2), next_speaker="solidarity_us")

joint_parser = OrchestratorParser()
joint_events = joint_parser.feed("\n\n— Einigung —\n")
for chunk in ("Die Erklärung", "\x1b[9", "2m bleibt", "\x1b[0", "m beim Thema."):
    joint_events.extend(joint_parser.feed(chunk))
joint_events.extend(joint_parser.finish())
assert joint_events[0]["type"] == "joint_start"
joint_deltas = [event for event in joint_events if event["type"] == "delta"]
assert "".join(event["text"] for event in joint_deltas) == "Die Erklärung bleibt beim Thema."
assert all(event["speaker"] == "joint" for event in joint_deltas)

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
assert RunParams(topic="topic").patience == 7
web_command = make_command(RunParams(topic="topic"))
assert web_command[web_command.index("--patience") + 1] == "7"
assert RunParams(topic="topic").joint_sentences == 1
assert web_command[web_command.index("--joint-sentences") + 1] == "1"

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
assert "Gemeinsam sagen wir:" not in o.AGREE_OPENERS

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

    explicit_transcript = [
        (o.MODERATOR, "Thema"),
        ("solidarity_us", "Ich stimme dir zu. Freiheit braucht Regeln."),
        ("ddr", "Ich stimme dir teilweise zu. Regeln müssen Freiheit schützen."),
    ]
    assert not o.mutual_explicit_agreement(tr)
    assert o.mutual_explicit_agreement(explicit_transcript)
    try:
        o.IDS = {"solidarity_us": (1, 2), "ddr": (1, 2)}
        o.p_interrupt = fake_p_interrupt
        o.OPTS = types.SimpleNamespace(accept=0.35, debug=False, topic="Thema")
        assert await o.evaluate_stance(tr, "Thema", 1) == "disagree"
        assert await o.evaluate_stance(explicit_transcript, "Thema", 1) == "agree"
        probs["ddr"] = 0.9
        assert await o.evaluate_stance(explicit_transcript, "Thema", 1) == "disagree"
        probs["ddr"] = 0.1
        human_transcript = [
            (o.MODERATOR, "Thema"),
            ("ddr", "Freiheit braucht Regeln."),
            ("solidarity_us", "Ich stimme dir zu. Freiheit braucht Regeln."),
        ]
        assert await o.evaluate_human_stance(
            "ddr", "solidarity_us", human_transcript, 1
        ) == "agree"
        probs["solidarity_us"] = 0.9
        assert await o.evaluate_human_stance(
            "ddr", "solidarity_us", human_transcript, 1
        ) == "disagree"
        o.IDS = {}
        assert await o.evaluate_stance(explicit_transcript, "Thema", 1) == "disagree"
    finally:
        o.IDS, o.p_interrupt, o.OPTS = old_ids, old_interrupt, old_opts

asyncio.run(check_stance())

async def check_session_final_statement():
    old_opts, old_emit, old_weave = o.OPTS, o.emit, o.weave
    events = []

    async def fake_weave(*args, **kwargs):
        assert kwargs["session_stream"] is True
        o.emit({"type": "joint_start"})
        o.emit({"type": "delta", "speaker": "joint", "text": "Gemeinsam."})
        return "Darin stimmen wir überein: Freiheit braucht Regeln."

    try:
        o.OPTS = types.SimpleNamespace(mix_every=1, joint_sentences=5)
        o.emit = lambda event: events.append(event)
        o.weave = fake_weave
        await o.session_finalize_outcome("Thema", tr, 1, "ddr", "agree")
    finally:
        o.OPTS, o.emit, o.weave = old_opts, old_emit, old_weave
    assert [event["type"] for event in events] == ["joint_start", "delta", "outcome"]

asyncio.run(check_session_final_statement())

async def check_unverified_agreement_is_downgraded():
    old_opts, old_emit, old_weave = o.OPTS, o.emit, o.weave
    events = []

    async def invalid_weave(*args, **kwargs):
        return ""

    try:
        o.OPTS = types.SimpleNamespace(mix_every=1, joint_sentences=1)
        o.emit = lambda event: events.append(event)
        o.weave = invalid_weave
        await o.session_finalize_outcome("Thema", tr, 1, "ddr", "agree")
    finally:
        o.OPTS, o.emit, o.weave = old_opts, old_emit, old_weave
    assert not any(event["type"] == "joint_start" for event in events)
    assert events[-1] == {"type": "outcome", "outcome": "disagree"}

asyncio.run(check_unverified_agreement_is_downgraded())

async def check_cli_agreement_downgrade():
    old_opts, old_weave = o.OPTS, o.weave
    output = io.StringIO()

    async def invalid_weave(*args, **kwargs):
        return ""

    try:
        o.OPTS = types.SimpleNamespace(mix_every=1)
        o.weave = invalid_weave
        with contextlib.redirect_stdout(output):
            await o.finalize_outcome(obedience_topic, grounding_transcript, 1, "ddr", "agree")
    finally:
        o.OPTS, o.weave = old_opts, old_weave
    rendered = output.getvalue()
    assert "[Einigung erreicht]" not in rendered
    assert "[Einigung: uneinig, aber respektvoll]" in rendered

asyncio.run(check_cli_agreement_downgrade())

async def check_single_model_closing_stream():
    old_opts, old_emit, old_stream = o.OPTS, o.emit, o.stream
    events = []
    calls = []

    async def fake_stream(speaker, prompt, n_predict, temperature=None, seed=None):
        calls.append((speaker, prompt, n_predict))
        yield " Freiheit und Sicherheit"
        yield " müssen gemeinsam betrachtet werden."

    closing_transcript = [
        (o.MODERATOR, "Ist Freiheit ohne Sicherheit möglich?"),
        ("solidarity_us", "Freiheit und Sicherheit müssen gemeinsam geschützt werden."),
        ("ddr", "Sicherheit gibt Freiheit einen verlässlichen Rahmen."),
    ]
    try:
        o.OPTS = types.SimpleNamespace(tokens=80, joint_sentences=1, temperature=0.8, dry=0.8)
        o.emit = lambda event: events.append(event)
        o.stream = fake_stream
        statement = await o.weave(
            "Ist Freiheit ohne Sicherheit möglich?",
            closing_transcript,
            1,
            ["ddr", "solidarity_us"],
            opener="Wir sind uns einig:",
            session_stream=True,
        )
    finally:
        o.OPTS, o.emit, o.stream = old_opts, old_emit, old_stream
    assert statement == "Wir sind uns einig: Freiheit und Sicherheit müssen gemeinsam betrachtet werden."
    assert len(calls) == 1 and calls[0][0] == "ddr"
    assert "höchstens 20 Wörtern" in calls[0][1]
    assert "Wiederhole keine Schlüsselwörter" in calls[0][1]
    assert "Erfinde keine Beispiele" in calls[0][1]
    assert events[0]["type"] == "joint_start"
    streamed = [event for event in events if event["type"] == "delta"]
    assert "".join(event["text"] for event in streamed) == statement

asyncio.run(check_single_model_closing_stream())

async def check_ungrounded_closing_is_not_streamed():
    old_opts, old_emit, old_stream = o.OPTS, o.emit, o.stream
    events = []

    async def hallucinated_stream(*args, **kwargs):
        yield " Niemand darf unangemeldet in unsere Häuser gehen."

    try:
        o.OPTS = types.SimpleNamespace(tokens=80, joint_sentences=1, temperature=0.8, dry=0.8)
        o.emit = lambda event: events.append(event)
        o.stream = hallucinated_stream
        statement = await o.weave(
            obedience_topic,
            grounding_transcript,
            1,
            ["ddr", "solidarity_us"],
            opener="Darin stimmen wir überein:",
            session_stream=True,
        )
    finally:
        o.OPTS, o.emit, o.stream = old_opts, old_emit, old_stream
    assert statement == ""
    assert events == []

asyncio.run(check_ungrounded_closing_is_not_streamed())

async def check_terminal_closing_color_stream():
    old_opts, old_stream = o.OPTS, o.stream
    output = io.StringIO()

    async def fake_stream(speaker, prompt, n_predict, temperature=None, seed=None):
        yield " Wir sind uns"
        yield " einig: Solidarität"
        yield " trägt Freiheit."

    closing_transcript = [
        (o.MODERATOR, "Kann Solidarität Freiheit sichern?"),
        ("solidarity_us", "Solidarität kann die Freiheit aller schützen."),
        ("ddr", "Freiheit braucht Solidarität und Verantwortung."),
    ]
    try:
        o.OPTS = types.SimpleNamespace(tokens=80, joint_sentences=5, temperature=0.8, dry=0.8)
        o.stream = fake_stream
        with contextlib.redirect_stdout(output):
            await o.weave(
                "Thema: Freiheit",
                closing_transcript,
                1,
                ["solidarity_us", "ddr"],
                opener="",
                session_stream=False,
            )
    finally:
        o.OPTS, o.stream = old_opts, old_stream
    rendered = output.getvalue()
    assert rendered.count("\x1b[92m") == 1
    assert rendered.count("\x1b[0m") == 1
    assert "Solidarität" in rendered
    assert "Solidar\x1b" not in rendered

asyncio.run(check_terminal_closing_color_stream())

async def check_off_topic_turn_does_not_leak():
    old_opts, old_stream = o.OPTS, o.stream
    calls = []
    output = io.StringIO()
    invalid = "Solidarität bedeutet, dass wir gemeinsam die Gesellschaft gestalten."

    async def fake_stream(*args, **kwargs):
        calls.append(1)
        yield invalid

    try:
        o.OPTS = types.SimpleNamespace(
            topic=persecution_topic,
            temperature=0.8,
            repeat_guard=True,
            max_sentences=2,
            tokens=160,
            dice=None,
            debug=False,
        )
        o.stream = fake_stream
        with contextlib.redirect_stdout(output):
            result = await o.speak(
                "solidarity_us",
                "ddr",
                [(o.MODERATOR, o.topic_context(persecution_topic))],
                [(o.MODERATOR, persecution_topic)],
                {"thresh": None, "min_chars": 0},
                False,
                scenario=persecution_topic,
            )
    finally:
        o.OPTS, o.stream = old_opts, old_stream
    assert len(calls) == 3
    assert result[0] == us_persecution_fallback
    assert invalid not in output.getvalue()
    assert result[0] in output.getvalue()

asyncio.run(check_off_topic_turn_does_not_leak())

async def check_session_turn_failure_uses_safe_fallback():
    old_opts, old_emit, old_stream = o.OPTS, o.emit, o.stream
    events = []

    async def invalid_stream(*args, **kwargs):
        yield "Solidarität ist wichtig."

    try:
        o.OPTS = types.SimpleNamespace(
            topic=persecution_topic,
            max_sentences=2,
            tokens=80,
            temperature=0.8,
            repeat_guard=True,
        )
        o.emit = lambda event: events.append(event)
        o.stream = invalid_stream
        transcript = [(o.MODERATOR, persecution_topic)]
        result = await o.session_ai_turn("ddr", transcript, 1)
    finally:
        o.OPTS, o.emit, o.stream = old_opts, old_emit, old_stream
    assert result == ddr_persecution_fallback
    assert transcript[-1] == ("ddr", ddr_persecution_fallback)
    assert any(event["type"] == "log" and "Ersatzantwort verwendet" in event["text"] for event in events)
    assert "".join(event.get("text", "") for event in events if event["type"] == "delta") == result

asyncio.run(check_session_turn_failure_uses_safe_fallback())

print("all logic tests passed")
