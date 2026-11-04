from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
ORCHESTRATOR = ROOT / "ochestrator.py"
RUNS_DIR = ROOT / "out" / "runs"

sys.path.insert(0, str(ROOT))
import ochestrator as orch

PERSONA_LABELS = {p: info["label"] for p, info in orch.PERSONAS.items()}
MODERATOR_LABEL = "Moderator"
LABELS = {**{p: p for p in orch.PERSONAS}, MODERATOR_LABEL: "moderator"}
LABEL_TO_PERSONA = {label: persona for persona, label in PERSONA_LABELS.items()}
LABEL_TO_PERSONA[MODERATOR_LABEL] = "moderator"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
DEBUG_SCORE_RE = re.compile(r"\s*\[p=[0-9.]+\]")
DEBUG_TEST_RE = re.compile(r"\n\n\[Einigungs-Test p=[0-9.]+\]")
TOPIC_RE = re.compile(r"=== (.*?) \((polite|free|chaos)\) ===")
HEADER_RE = re.compile(r"\n\n\[([^\]\n]+)\][ \t]")
JOINT_RE = re.compile(r"\n\n\u2014 Einigung \u2014\n")
AGREE_RE = re.compile(r"\n\n\[Einigung erreicht\]")
DISAGREE_RE = re.compile(r"\n\n\[Einigung: uneinig, aber respektvoll\]")
ANGRY_RE = re.compile(r"\n\n\[Abbruch: Streit eskaliert\]")
FALLBACK_RE = re.compile(r"\x1b\[(92|91)m\[([^\]\n]+)\][ \t]([^\x1b]*)\x1b\[0m\n?")
TAIL = 120

OUTCOME_LABELS = {
    "agree": "Einigung erreicht",
    "disagree": "Uneinig, aber respektvoll",
    "angry": "Abbruch: Streit eskaliert",
}


class OrchestratorParser:
    def __init__(self) -> None:
        self.buf = ""
        self.state = "idle"
        self.speaker: str | None = None
        self.section = "turn"
        self.ansi_state = 0

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        self.buf += chunk
        self.buf = self.buf.replace("\r\n", "\n")
        self.buf = DEBUG_TEST_RE.sub("", self.buf)
        self.buf = DEBUG_SCORE_RE.sub("", self.buf)
        events: list[dict[str, Any]] = []
        while True:
            marker = self._find_marker()
            if marker:
                start, end, kind, match = marker
                if start:
                    events.extend(self._text(self.buf[:start]))
                events.extend(self._marker(kind, match))
                self.buf = self.buf[end:]
                continue
            if len(self.buf) > TAIL:
                safe, self.buf = self.buf[:-TAIL], self.buf[-TAIL:]
                events.extend(self._text(safe))
            break
        return events

    def finish(self) -> list[dict[str, Any]]:
        events = self._text(self.buf)
        self.buf = ""
        return events

    def _find_marker(self):
        candidates = []
        for kind, regex in (
            ("joint", JOINT_RE),
            ("agree", AGREE_RE),
            ("disagree", DISAGREE_RE),
            ("angry", ANGRY_RE),
            ("fallback", FALLBACK_RE),
        ):
            match = regex.search(self.buf)
            if match:
                candidates.append((match.start(), match.end(), kind, match))
        for match in HEADER_RE.finditer(self.buf):
            if match.group(1) in LABEL_TO_PERSONA:
                candidates.append((match.start(), match.end(), "header", match))
                break
        return min(candidates, key=lambda item: item[0]) if candidates else None

    def _marker(self, kind: str, match: re.Match) -> list[dict[str, Any]]:
        if kind == "header":
            label = match.group(1)
            self.speaker = LABEL_TO_PERSONA[label]
            self.section = "moderator" if self.speaker == "moderator" else "turn"
            self.state = self.section
            return [{
                "type": "turn_start",
                "speaker": self.speaker,
                "label": PERSONA_LABELS.get(self.speaker, MODERATOR_LABEL),
                "section": self.section,
            }]
        if kind == "joint":
            self.state = "joint"
            self.section = "joint"
            self.speaker = "joint"
            return [{"type": "joint_start"}]
        if kind in ("agree", "disagree", "angry"):
            outcome = kind
            self.state = "idle"
            self.section = "turn"
            self.speaker = None
            return [{"type": "outcome", "outcome": outcome}]
        if kind == "fallback":
            color, label, text = match.group(1), match.group(2), match.group(3).strip()
            speaker = "solidarity_us" if color == "92" else "ddr"
            if label in LABEL_TO_PERSONA:
                speaker = LABEL_TO_PERSONA[label]
            return [{
                "type": "line",
                "speaker": speaker,
                "label": PERSONA_LABELS.get(speaker, label),
                "text": text,
            }]
        return []

    def _text(self, raw: str) -> list[dict[str, Any]]:
        if not raw:
            return []
        if self.state == "idle":
            return self._idle(raw)
        if self.state == "joint":
            return self._joint(raw)
        return self._turn(raw)

    def _idle(self, raw: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        topic = TOPIC_RE.search(raw)
        if topic:
            events.append({"type": "topic", "topic": topic.group(1).strip(), "mode": topic.group(2)})
            raw = TOPIC_RE.sub("", raw)
        for line in raw.splitlines():
            line = line.strip()
            if line:
                events.append({"type": "status", "text": line})
        return events

    def _turn(self, raw: str) -> list[dict[str, Any]]:
        interrupted = raw.rstrip().endswith(" \u2014")
        if interrupted:
            raw = raw.rstrip()[:-2]
        events: list[dict[str, Any]] = []
        if raw:
            events.append({"type": "delta", "speaker": self.speaker, "text": raw})
        if interrupted:
            events.append({"type": "interrupt", "speaker": self.speaker})
        return events

    def _joint(self, raw: str) -> list[dict[str, Any]]:
        text = []
        for char in raw:
            if self.ansi_state == 1:
                self.ansi_state = 2 if char == "[" else 0
            elif self.ansi_state == 2:
                if "@" <= char <= "~":
                    self.ansi_state = 0
            elif char == "\x1b":
                self.ansi_state = 1
            else:
                text.append(char)
        plain = "".join(text)
        if not plain:
            return []
        return [{"type": "delta", "speaker": "joint", "text": plain, "section": "joint"}]


class RunParams(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    format: Literal["ai_vs_ai", "human_vs_ai", "human_vs_both", "moderator", "quick"] = "ai_vs_ai"
    human_persona: Literal["solidarity_us", "ddr"] | None = None
    turn_seconds: int = Field(60, ge=10, le=600)
    exchanges: int = Field(12, ge=1, le=50)
    suggestions: bool = True
    mode: Literal["polite", "free", "chaos"] = "free"
    turns: int = Field(40, ge=1, le=100)
    rotate: int = Field(0, ge=0, le=100)
    agree: bool = True
    outcome: Literal["auto", "agree", "disagree", "angry", "random"] = "auto"
    temperature: float = Field(0.8, ge=0.0, le=2.0)
    dice: float | None = Field(None, ge=0.0, le=1.0)
    auto_launch: bool = True
    context: int = Field(4096, ge=512, le=32768)
    tokens: int = Field(160, ge=16, le=2048)
    max_sentences: int = Field(2, ge=1, le=10)
    cooldown: int = Field(3, ge=0, le=50)
    dry: float = Field(0.8, ge=0.0, le=5.0)
    repeat_guard: bool = True
    mix_every: int = Field(1, ge=1, le=20)
    joint_sentences: int = Field(1, ge=1, le=10)
    accept: float = Field(0.35, ge=0.0, le=1.0)
    attempts: int = Field(2, ge=1, le=10)
    patience: int = Field(7, ge=1, le=20)
    rage: int = Field(3, ge=1, le=10)
    debug: bool = False

    @field_validator("topic")
    @classmethod
    def _topic_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("topic must not be blank")
        return value


class InputCommand(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ActionCommand(BaseModel):
    action: Literal["agree", "end"]


@dataclass
class Run:
    id: str
    params: dict[str, Any]
    created: float
    status: str = "starting"
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    proc: Any = None
    task: Any = None
    stop_requested: bool = False
    final: bool = False
    exit_code: int | None = None

    def emit(self, event: dict[str, Any]) -> None:
        event.setdefault("seq", len(self.events))
        self.events.append(event)
        for queue in list(self.subscribers):
            queue.put_nowait(event)


ACTIVE: dict[str, Run] = {}


def make_command(params: RunParams) -> list[str]:
    if params.format != "ai_vs_ai":
        command = [
            sys.executable, "-u", str(ORCHESTRATOR),
            "--session",
            "--session-mode", params.format,
            "--turn-seconds", str(params.turn_seconds),
            "--exchanges", str(params.exchanges),
            "--suggestions" if params.suggestions else "--no-suggestions",
        ]
        if params.human_persona:
            command += ["--human-persona", params.human_persona]
        if not params.auto_launch:
            command.append("--no-launch")
        if params.debug:
            command.append("--debug")
        return [*command, "--", params.topic]
    options = [
        "--mode", params.mode,
        "--turns", str(params.turns),
        "--rotate", str(params.rotate),
        "--outcome", params.outcome,
        "--temperature", f"{params.temperature:g}",
        "--context", str(params.context),
        "--tokens", str(params.tokens),
        "--max-sentences", str(params.max_sentences),
        "--cooldown", str(params.cooldown),
        "--dry", f"{params.dry:g}",
        "--mix-every", str(params.mix_every),
        "--joint-sentences", str(params.joint_sentences),
        "--accept", f"{params.accept:g}",
        "--attempts", str(params.attempts),
        "--patience", str(params.patience),
        "--rage", str(params.rage),
        "--repeat-guard" if params.repeat_guard else "--no-repeat-guard",
    ]
    options.append("--agree" if params.agree else "--no-agree")
    if params.dice is not None:
        options.extend(["--dice", f"{params.dice:g}"])
    if not params.auto_launch:
        options.append("--no-launch")
    if params.debug:
        options.append("--debug")
    return [sys.executable, "-u", str(ORCHESTRATOR), *options, "--", params.topic]


async def kill_tree(proc) -> None:
    if proc is None or proc.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/F", "/T", "/PID", str(proc.pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()


def save_run(run: Run) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "id": run.id,
        "created": run.created,
        "finished": time.time(),
        "params": run.params,
        "status": run.status,
        "exit_code": run.exit_code,
        "events": run.events,
        "blocks": blocks_from_events(run.events),
    }
    target = RUNS_DIR / f"{run.id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)


async def run_debate(run: Run, command: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    parser = OrchestratorParser()
    try:
        run.params["command"] = command
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            creationflags=creationflags,
        )
        run.proc = proc
        run.status = "running"
        run.emit({"type": "status", "state": "running", "text": "Debatte läuft"})
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(2048)
            if not chunk:
                break
            for event in parser.feed(chunk.decode("utf-8", errors="replace")):
                run.emit(event)
        for event in parser.finish():
            run.emit(event)
        await proc.wait()
        run.exit_code = proc.returncode
        if run.stop_requested:
            run.status = "stopped"
        elif proc.returncode == 0:
            run.status = "done"
        else:
            run.status = "error"
        run.emit({"type": "end", "status": run.status, "exit_code": run.exit_code})
    except Exception as exc:
        run.status = "error"
        run.emit({"type": "error", "text": str(exc)})
        run.emit({"type": "end", "status": "error", "exit_code": None})
    finally:
        run.final = True
        save_run(run)
        for queue in list(run.subscribers):
            queue.put_nowait(None)
        ACTIVE.pop(run.id, None)


async def run_session(run: Run, command: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        run.params["command"] = command
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            creationflags=creationflags,
        )
        run.proc = proc
        run.status = "running"
        run.emit({"type": "status", "state": "running", "text": "Debatte läuft"})

        async def drain_stderr() -> None:
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(1024)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace").strip()
                if text:
                    run.emit({"type": "log", "text": text})

        err_task = asyncio.create_task(drain_stderr())
        end_status: str | None = None
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                run.emit({"type": "log", "text": line})
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "end" and isinstance(event.get("status"), str):
                end_status = event["status"]
                if not run.stop_requested:
                    run.status = end_status
            run.emit(event)
        await proc.wait()
        with suppress(asyncio.CancelledError):
            await err_task
        run.exit_code = proc.returncode
        if run.stop_requested:
            run.status = "stopped"
        elif end_status:
            run.status = end_status
        elif proc.returncode == 0:
            run.status = "done"
        else:
            run.status = "error"
        if end_status is None:
            run.emit({"type": "end", "status": run.status, "exit_code": run.exit_code})
    except Exception as exc:
        run.status = "error"
        run.emit({"type": "error", "text": str(exc)})
        run.emit({"type": "end", "status": "error", "exit_code": None})
    finally:
        run.final = True
        save_run(run)
        for queue in list(run.subscribers):
            queue.put_nowait(None)
        ACTIVE.pop(run.id, None)


async def write_command(run: Run, message: dict[str, Any]) -> None:
    if run.proc is None or run.proc.stdin is None:
        raise HTTPException(status_code=409, detail="run does not accept input")
    try:
        run.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await run.proc.stdin.drain()
    except (BrokenPipeError, ConnectionError) as exc:
        raise HTTPException(status_code=409, detail="run has already ended") from exc


def blocks_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("type")
        if kind == "topic":
            blocks.append({"kind": "topic", "text": event.get("topic", "")})
        elif kind == "turn_start":
            blocks.append({
                "kind": "turn",
                "speaker": event.get("speaker"),
                "label": event.get("label"),
                "section": event.get("section", "turn"),
                "human": bool(event.get("human")),
                "auto": bool(event.get("auto")),
                "text": "",
            })
        elif kind == "joint_start":
            blocks.append({"kind": "joint", "text": ""})
        elif kind == "delta":
            if blocks and blocks[-1]["kind"] in ("turn", "joint"):
                blocks[-1]["text"] += event.get("text", "")
        elif kind == "interrupt" and blocks:
            blocks[-1]["interrupted"] = True
        elif kind == "line":
            blocks.append({
                "kind": "line",
                "speaker": event.get("speaker"),
                "label": event.get("label"),
                "text": event.get("text", ""),
            })
        elif kind == "outcome":
            blocks.append({"kind": "outcome", "outcome": event.get("outcome")})
        elif kind == "timeout" and blocks:
            blocks[-1]["timed_out"] = True
    for block in blocks:
        if "text" in block:
            block["text"] = block["text"].strip()
    return blocks


def normalize_record(record: dict[str, Any], orphan: bool = True) -> dict[str, Any]:
    if orphan and record.get("status") in ("starting", "running"):
        record["status"] = "stopped"
    if not record.get("outcome"):
        for event in reversed(record.get("events") or []):
            if event.get("type") == "outcome" and event.get("outcome"):
                record["outcome"] = event["outcome"]
                break
    return record


def load_record(run_id: str) -> dict[str, Any]:
    run = ACTIVE.get(run_id)
    if run:
        return normalize_record({
            "id": run.id,
            "created": run.created,
            "params": run.params,
            "status": run.status,
            "events": run.events,
            "blocks": blocks_from_events(run.events),
        }, orphan=False)
    path = RUNS_DIR / f"{run_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="run not found")
    try:
        return normalize_record(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"could not read run: {exc}") from exc


def record_summary(record: dict[str, Any]) -> dict[str, Any]:
    params = record.get("params", {})
    return {
        "id": record.get("id"),
        "created": record.get("created"),
        "topic": params.get("topic", ""),
        "format": params.get("format", "ai_vs_ai"),
        "mode": params.get("mode", ""),
        "outcome": next(
            (event.get("outcome") for event in reversed(record.get("events", [])) if event.get("type") == "outcome"),
            None,
        ),
        "status": record.get("status", ""),
    }


def export_markdown(record: dict[str, Any]) -> str:
    params = record.get("params", {})
    blocks = record.get("blocks") or blocks_from_events(record.get("events", []))
    lines = [f"# {params.get('topic', 'Debatte')}", ""]
    meta = [f"Modus: {params.get('mode', '')}", f"Runden: {params.get('turns', '')}"]
    if params.get("agree"):
        meta.append("Einigungsrunden: ja")
    lines += ["_" + " · ".join(meta) + "_", ""]
    for block in blocks:
        kind = block.get("kind")
        if kind == "topic":
            lines += ["## Moderator", block.get("text", ""), ""]
        elif kind == "turn":
            heading = "Moderator" if block.get("speaker") == "moderator" else block.get("label", "")
            lines += [f"## {heading}", block.get("text", ""), ""]
        elif kind == "joint":
            lines += ["## Gemeinsame Erklärung", block.get("text", ""), ""]
        elif kind == "line":
            lines += [f"**{block.get('label', '')}:** {block.get('text', '')}", ""]
        elif kind == "outcome":
            lines += [f"> {OUTCOME_LABELS.get(block.get('outcome'), block.get('outcome'))}", ""]
    return "\n".join(lines).strip() + "\n"


def export_text(record: dict[str, Any]) -> str:
    params = record.get("params", {})
    blocks = record.get("blocks") or blocks_from_events(record.get("events", []))
    lines = [params.get("topic", "Debatte"), "=" * 48, ""]
    for block in blocks:
        kind = block.get("kind")
        if kind == "topic":
            lines += ["[Moderator]", block.get("text", ""), ""]
        elif kind == "turn":
            heading = "Moderator" if block.get("speaker") == "moderator" else block.get("label", "")
            lines += [f"[{heading}]", block.get("text", ""), ""]
        elif kind == "joint":
            lines += ["[Gemeinsame Erklärung]", block.get("text", ""), ""]
        elif kind == "line":
            lines += [f"[{block.get('label', '')}] {block.get('text', '')}", ""]
        elif kind == "outcome":
            lines += [f"[{OUTCOME_LABELS.get(block.get('outcome'), block.get('outcome'))}]", ""]
    return "\n".join(lines).strip() + "\n"


app = FastAPI(title="Religions- und Freiheitsdebatte", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/scenarios")
async def scenarios() -> dict[str, Any]:
    return {"scenarios": list(orch.SCENARIOS)}


@app.get("/api/runs")
async def runs() -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}
    if RUNS_DIR.is_dir():
        for path in RUNS_DIR.glob("*.json"):
            try:
                record = normalize_record(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            items[record.get("id", path.stem)] = record_summary(record)
    for run in ACTIVE.values():
        items[run.id] = record_summary({
            "id": run.id,
            "created": run.created,
            "params": run.params,
            "status": run.status,
            "events": run.events,
        })
    ordered = sorted(items.values(), key=lambda item: item.get("created") or 0, reverse=True)
    return {"runs": ordered[:100]}


@app.post("/api/runs")
async def create_run(params: RunParams) -> dict[str, Any]:
    if any(run.status in ("starting", "running") for run in ACTIVE.values()):
        raise HTTPException(status_code=409, detail="Eine Debatte läuft bereits. Bitte zuerst stoppen.")
    if not ORCHESTRATOR.is_file():
        raise HTTPException(status_code=500, detail="ochestrator.py wurde nicht gefunden.")
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run = Run(id=run_id, params=params.model_dump(), created=time.time())
    ACTIVE[run_id] = run
    command = make_command(params)
    runner = run_session if params.format != "ai_vs_ai" else run_debate
    run.task = asyncio.create_task(runner(run, command))
    return {"id": run_id, "status": run.status}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    return JSONResponse(load_record(run_id))


@app.post("/api/runs/{run_id}/input")
async def send_input(run_id: str, payload: InputCommand) -> dict[str, Any]:
    run = ACTIVE.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    await write_command(run, {"type": "input", "text": payload.text.strip()})
    return {"id": run_id, "status": "sent"}


@app.post("/api/runs/{run_id}/action")
async def send_action(run_id: str, payload: ActionCommand) -> dict[str, Any]:
    run = ACTIVE.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    await write_command(run, {"type": payload.action})
    return {"id": run_id, "status": "sent", "action": payload.action}


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, Any]:
    run = ACTIVE.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    run.stop_requested = True
    await kill_tree(run.proc)
    return {"id": run_id, "status": "stopping"}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    run = ACTIVE.get(run_id)
    if run:
        queue: asyncio.Queue = asyncio.Queue()
        start = len(run.events)
        run.subscribers.add(queue)
        replay = list(run.events[:start])
        already_final = run.final
    else:
        record = load_record(run_id)
        replay = list(record.get("events", []))
        queue = None
        already_final = True
        start = 0

    async def generate():
        try:
            for event in replay:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if already_final or queue is None:
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if queue is not None and run:
                run.subscribers.discard(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/export")
async def export_run(run_id: str, format: str = "md") -> Response:
    record = load_record(run_id)
    if format == "json":
        return JSONResponse(record, headers={
            "Content-Disposition": f'attachment; filename="{run_id}.json"',
        })
    if format == "txt":
        return PlainTextResponse(export_text(record), headers={
            "Content-Disposition": f'attachment; filename="{run_id}.txt"',
        })
    if format == "md":
        return PlainTextResponse(export_markdown(record), media_type="text/markdown", headers={
            "Content-Disposition": f'attachment; filename="{run_id}.md"',
        })
    raise HTTPException(status_code=400, detail="format must be md, txt or json")


@app.on_event("shutdown")
async def shutdown() -> None:
    for run in list(ACTIVE.values()):
        run.stop_requested = True
        await kill_tree(run.proc)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
