#!/usr/bin/env python3
"""Local server for the Assignment 1 oral-quiz practice page.

Run it from the repository root (or anywhere; paths are resolved from this file):

    python3 quiz/app/server.py                 # http://127.0.0.1:8329, opens the browser
    python3 quiz/app/server.py --model sonnet --no-open

Grading runs Claude Code headless (``claude -p``) in the repository root, so the
grader reads the working tree as it is now. It runs in ``--safe-mode`` (no hooks,
plugins, MCP servers or CLAUDE.md), with only the Read, Grep and Glob tools, never
``.env``, and with permission prompts answered "no", so it cannot edit anything or
read outside the repository. Each graded answer is one Claude Code session (named
"oral-quiz: <question>"); a follow-up resumes that session, so the grader still
has what it read.

The question bank (``questions.json``) is reread whenever it changes, so edits to
it show up on the next page load without restarting the server.

Code references on the page open ``/code/<path>?lines=a-b`` (``code.html``), which
shows the file as it is in the working tree with those lines marked, and links
to the same place in your editor (``--editor``). It serves only what git tracks
or would track, so ignored files such as ``.env`` are never shown.

Sample answers live in ``quiz/samples/<question id>.md``, one Markdown file per
question (``GET /api/samples``, ``PUT /api/samples/<id>``). The page shows and
edits them, and can replace one with a graded answer of yours.

Attempts in progress are kept in ``quiz/.attempts/<id>.json``. "Save to quiz/"
writes ``quiz/quizN/`` (the lowest-numbered empty one, else the next number) with
``quiz.md`` (the transcript), ``quiz.json`` (all data, rubric included) and
``index.html`` (a static copy of the results). Saving the same attempt again
rewrites its folder.

Only the standard library is used. The server listens on 127.0.0.1 and refuses
requests whose Host or Origin is another site.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

APP_DIR = Path(__file__).resolve().parent
QUIZ_DIR = APP_DIR.parent
REPO = QUIZ_DIR.parent
ATTEMPTS_DIR = QUIZ_DIR / ".attempts"
SAMPLES_DIR = QUIZ_DIR / "samples"
BANK_PATH = APP_DIR / "questions.json"
PUBLIC_FIELDS = ("id", "title", "tag", "prompt", "hints", "context")

ATTEMPT_ID = re.compile(r"a-\d{8}-\d{6}-[a-z0-9]{4}")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MAX_BODY = 4 * 1024 * 1024
PING_SECONDS = 2.0

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "verdict": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "code_check": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cited": {"type": "string"},
                    "status": {"type": "string", "enum": ["correct", "close", "wrong", "unverifiable"]},
                    "note": {"type": "string"},
                },
                "required": ["cited", "status", "note"],
            },
        },
        "missing_refs": {"type": "array", "items": {"type": "string"}},
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "model_answer": {"type": "string"},
    },
    "required": ["score", "verdict", "strengths", "gaps", "code_check", "missing_refs", "suggestions", "model_answer"],
}

SCALE = """5 - Complete and precise: names the actual decision, the reasoning or trade-off behind it, and points to the right code. An examiner would move on without a follow-up.
4 - Correct and nearly complete; a minor point missing, or code references slightly off (right file and function, lines a little off).
3 - The core idea is right, but a key element is missing (the rationale, a key mechanism, a concrete example) or the code references are vague or partly wrong.
2 - Partly correct: significant errors, mostly generic, or cannot point to the code.
1 - Wrong, off-topic, or empty."""

FOLLOWUP_RULES = (
    "The student asks a follow-up about your grade. Answer as their TA preparing them for the real "
    "oral quiz: direct, specific, under about 200 words unless they ask for more, in plain Markdown "
    "(not JSON). Cite file:line, and check the code with your tools before you quote it. If they ask "
    "you to quiz them, ask one follow-up question the way a TA would and stop there. If they are "
    "answering a question you asked, say briefly what was right and what was missing."
)

CONFIG: dict = {}


# --------------------------------------------------------------- helpers ----


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def repo_state() -> dict:
    head = git("rev-parse", "--short", "HEAD")
    changed = git("status", "--porcelain", "--", "cs329z_hw1")
    return {"head": head, "package_changed": bool(changed)}


def rel(path: Optional[str]) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


def repo_files() -> list[str]:
    """The files the code viewer may show: what git tracks or would track.

    Ignored files (.env, .venv, quiz/.attempts, data/raw) never appear, and
    nothing outside the repository can, so this list is the whole allowlist.
    """
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    root = REPO.resolve()
    return sorted(
        f for f in out.split("\0")
        if f and Path(f).name != ".env" and (REPO / f).is_file() and (REPO / f).resolve().is_relative_to(root)
    )


def find_code(want: str) -> dict:
    """Resolve the path of a code reference for the viewer.

    A file or directory is matched exactly; failing that, a bare or partial path
    such as ``session.py`` or ``agent/`` matches the one entry that ends with it.
    """
    files = repo_files()
    while want.startswith("./"):
        want = want[2:]
    clean = want.strip("/")
    if clean in files:
        return {"kind": "file", "path": clean}
    dirs = {str(p) + "/" for f in files for p in Path(f).parents if str(p) != "."}
    if not clean or clean + "/" in dirs:
        prefix = clean + "/" if clean else ""
        entries = {f[len(prefix):].split("/")[0] + ("/" if "/" in f[len(prefix):] else "") for f in files if f.startswith(prefix)}
        return {"kind": "dir", "path": prefix, "entries": sorted(entries, key=lambda e: (not e.endswith("/"), e))}
    suffix = "/" + clean
    matches = sorted(f for f in files if ("/" + f).endswith(suffix)) or sorted(d for d in dirs if ("/" + d).endswith(suffix + "/"))
    if len(matches) == 1:
        return {**find_code(matches[0]), "resolved_from": want}
    if matches:
        return {"kind": "ambiguous", "path": want, "entries": matches}
    return {"kind": "missing", "path": want}


TEXT_LIMIT = 2 * 1024 * 1024


def code_payload(want: str) -> dict:
    found = find_code(want)
    found.update(repo=str(REPO), editor=CONFIG.get("editor"))
    if found["kind"] != "file":
        return found
    path = REPO / found["path"]
    if path.suffix.lower() == ".pdf":
        return {**found, "kind": "pdf"}
    data = path.read_bytes()
    head = data[:TEXT_LIMIT]
    try:
        if b"\0" in head[:8192]:
            raise UnicodeDecodeError("utf-8", head, 0, 1, "NUL byte")
        text = head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A long file cut at TEXT_LIMIT may end inside a character; anything else is binary.
        if len(data) <= TEXT_LIMIT or exc.start < len(head) - 3:
            return {**found, "kind": "binary", "size": len(data)}
        text = head[:exc.start].decode("utf-8")
    return {**found, "text": text, "size": len(data), "truncated": len(data) > TEXT_LIMIT}


_bank: dict = {}
_bank_guard = threading.Lock()


def bank() -> dict:
    """The question bank, reread whenever questions.json changes on disk.

    The page and the grader always see the bank as it is now, without a restart.
    If the file does not parse (an edit in progress), the last good copy stays.
    """
    mtime = BANK_PATH.stat().st_mtime_ns
    with _bank_guard:
        if _bank.get("mtime") != mtime:
            try:
                data = json.loads(BANK_PATH.read_text(encoding="utf-8"))
                by_id = {q["id"]: q for q in data["questions"]}
            except (ValueError, KeyError, TypeError) as exc:
                if not _bank:
                    raise
                print(f"questions.json is not valid ({exc!r}); keeping the copy loaded before.", file=sys.stderr)
            else:
                _bank.update(data=data, by_id=by_id)
            _bank["mtime"] = mtime
        return _bank["data"]


def question(qid: object) -> Optional[dict]:
    bank()
    return _bank["by_id"].get(qid)


def rubric_text(q: dict) -> str:
    return (
        f"Key points a complete answer covers (paths are repo-relative; line numbers were taken at commit "
        f"{bank()['rubric_commit']}):\n" + "\n".join(f"- {p}" for p in q["points"])
        + "\n\nReference locations:\n" + "\n".join(f"- {r}" for r in q["refs"])
        + "\n\nCommon weak answers:\n" + "\n".join(f"- {p}" for p in q["pitfalls"])
    )


def handout_text(q: dict) -> str:
    c = q["context"]
    where = "; ".join(f"{s['label']}, p. {'-'.join(map(str, s['pages']))}" for s in c["sources"])

    def item(x: dict) -> str:
        return x["text"] + (f" [{'; '.join(x['refs'])}]" if x["refs"] else "")

    return (
        f"Source in {bank()['handout']}: {where}\n"
        "What the starter code provided:\n" + "\n".join(f"- {item(p)}" for p in c["provided"])
        + "\nWhat the handout asked for:\n" + "\n".join(f"- {item(a)}" for a in c["asked"])
        + f"\nDesign decision: {item(c['decision'])}"
    )


def grade_prompt(q: dict, answer: str, refs: str) -> str:
    state = repo_state()
    drift = (
        f"The repository is at commit {state['head']}"
        + (" with uncommitted changes under cs329z_hw1/" if state["package_changed"] else "")
        + f"; the rubric's line numbers come from {bank()['rubric_commit']}. Trust the code as it is now."
    )
    return f"""You grade a practice question for the oral quiz of Stanford CS329Z (Engineering AI Agents), Assignment 1, "Building an Agentic Harness". In the real quiz a TA asks the student, for 10 minutes, to explain design decisions in their own code and to point to where they are implemented. There are no trick questions. Your feedback should get the student ready for that conversation.

You are running in the root of the student's repository. Their implementation is in cs329z_hw1/ (agent/ and pipelines/ are theirs; llm.py, sandbox.py, cardinal.py, user.py, types.py and simulation/ are course code). Their write-ups are NOTES.md, TODO.md, design_memo.pdf and field_notes.pdf; runs/ holds their saved evaluation and chat runs. You have read-only tools (Read, Grep, Glob). Never open .env. {drift}

QUESTION ({q['tag']}): {q['prompt']}

HANDOUT
{handout_text(q)}

RUBRIC
{rubric_text(q)}

SCALE
{SCALE}

THE STUDENT'S ANSWER
\"\"\"
{answer or "(no answer)"}
\"\"\"

CODE THE STUDENT POINTED TO (one per line; file:line, a range, or a function name)
\"\"\"
{refs or "(none given)"}
\"\"\"

How to grade:
- Open every code reference the student gave and check that it holds what they claim. Line numbers within about 10 lines, or the right function named, count as correct.
- Before you credit or penalize a mechanism they describe, confirm it in the code. A correct point that the rubric does not list still counts once you have confirmed it.
- Keep tool use focused: the cited references plus whatever you need to confirm the key points.
- Grade the substance, not the prose. A short answer that is precise can score 5.
- A claim that contradicts the code is an error, even if it sounds plausible.
- An answer without code references can score at most 3 on a question that asks the student to point to code.
- Be specific in the gaps: say what was missing and where it lives (file:line).
- model_answer is what a 5/5 student would say out loud in about 45 seconds, in plain sentences, citing file:line.
- Use inline backticks for code names. Use empty arrays where nothing applies.

Return the grade as the structured output."""


def normalize_grade(g: dict) -> dict:
    def strings(v) -> list[str]:
        return [x if isinstance(x, str) else json.dumps(x) for x in v] if isinstance(v, list) else []

    try:
        score = int(round(float(g.get("score", 1))))
    except (TypeError, ValueError):
        score = 1
    checks = []
    for c in g.get("code_check") or []:
        if isinstance(c, dict):
            status = c.get("status") if c.get("status") in ("correct", "close", "wrong", "unverifiable") else "unverifiable"
            checks.append({"cited": str(c.get("cited", "")), "status": status, "note": str(c.get("note", ""))})
    return {
        "score": min(5, max(1, score)),
        "verdict": str(g.get("verdict", "")),
        "strengths": strings(g.get("strengths")),
        "gaps": strings(g.get("gaps")),
        "code_check": checks,
        "missing_refs": strings(g.get("missing_refs")),
        "suggestions": strings(g.get("suggestions")),
        "model_answer": str(g.get("model_answer", "")),
    }


def parse_json_text(text: str) -> Optional[dict]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    for candidate in (text, fence.group(1) if fence else None, text[text.find("{") : text.rfind("}") + 1]):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def describe_tool(block: dict) -> str:
    name, inp = block.get("name", ""), block.get("input") or {}
    if name == "Read":
        start, limit = inp.get("offset"), inp.get("limit")
        span = f" {start}-{start + limit}" if start and limit else f" from line {start}" if start else ""
        return f"read {rel(inp.get('file_path'))}{span}"
    if name == "Grep":
        where = f" in {rel(inp.get('path'))}" if inp.get("path") else ""
        return f"grep /{inp.get('pattern', '')}/{where}"
    if name == "Glob":
        return f"glob {inp.get('pattern', '')}"
    if name == "StructuredOutput":
        return "writing the grade"
    return name


def claude_command(*, session_id: Optional[str] = None, resume: Optional[str] = None,
                   schema: Optional[dict] = None, partial: bool = False, name: str = "") -> list[str]:
    cmd = [
        CONFIG["claude"], "-p", "--safe-mode",
        "--tools", "Read,Grep,Glob",
        "--disallowedTools", "Read(./.env)",
        "--permission-prompts", "none",
        "--output-format", "stream-json", "--verbose",
        "--max-budget-usd", str(CONFIG["budget"]),
    ]
    if CONFIG.get("model"):
        cmd += ["--model", CONFIG["model"]]
    if CONFIG.get("effort"):
        cmd += ["--effort", CONFIG["effort"]]
    if session_id:
        cmd += ["--session-id", session_id, "--name", name or "oral-quiz"]
    if resume:
        cmd += ["--resume", resume]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if partial:
        cmd += ["--include-partial-messages"]
    return cmd


# ---------------------------------------------------------------- storage ----

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def attempt_lock(attempt_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(attempt_id, threading.Lock())


def attempt_path(attempt_id: str) -> Path:
    return ATTEMPTS_DIR / f"{attempt_id}.json"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# Sample answers: quiz/samples/<qid>.md, one per question, written so they read
# well on GitHub and in an editor. The page reads the "## Answer" and "## Code
# to point to" sections back; the title and question above them are rewritten
# from the bank on every save.
SAMPLE_ANSWER, SAMPLE_REFS = "## Answer", "## Code to point to"
SAMPLE_SOURCE = re.compile(r"<!--\s*source:\s*(.*?)\s*-->", re.S)
MAX_SAMPLE = 64 * 1024


def sample_path(qid: str) -> Path:
    return SAMPLES_DIR / f"{qid}.md"


def read_sample(qid: str) -> Optional[dict]:
    path = sample_path(qid)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    source = SAMPLE_SOURCE.search(text)
    _, found, body = text.partition(f"\n{SAMPLE_ANSWER}\n")
    if not found:  # hand-edited without the heading: everything after the comment
        body = text[source.end():] if source else text
    answer, _, refs = body.partition(f"\n{SAMPLE_REFS}\n")
    return {
        "answer": answer.strip(),
        "refs": "\n".join(re.sub(r"^\s*[-*]\s+", "", l).rstrip() for l in refs.strip().splitlines() if l.strip()),
        "source": source.group(1) if source else "",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(path.stat().st_mtime)),
    }


def write_sample(q: dict, answer: str, refs: str, source: str) -> dict:
    refs_md = "\n".join(f"- {l.strip()}" for l in refs.splitlines() if l.strip())
    source = " ".join(source.replace("--", "-").split())  # keep the comment closed
    text = (
        f"# {q['title']}\n\n*{q['tag']}*\n\n> {q['prompt']}\n\n<!-- source: {source} -->\n\n"
        f"{SAMPLE_ANSWER}\n\n{answer.strip()}\n\n{SAMPLE_REFS}\n\n{refs_md}\n"
    )
    write_atomic(sample_path(q["id"]), text)
    return read_sample(q["id"])


def ensure_attempts_dir() -> None:
    ATTEMPTS_DIR.mkdir(parents=True, exist_ok=True)
    ignore = ATTEMPTS_DIR / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# Attempts in progress; saved quizzes go to quiz/quizN/.\n*\n", encoding="utf-8")


def load_attempt(attempt_id: str) -> Optional[dict]:
    path = attempt_path(attempt_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def summary(state: dict) -> dict:
    """An attempt's header, its latest score per question, and every answer it
    holds per question (graded tries, or one unsubmitted draft)."""
    a = state.get("attempt") or {}
    scores, responses = {}, {}
    for qid, item in (state.get("items") or {}).items():
        subs = item.get("submissions") or []
        if subs and subs[-1].get("grade"):
            scores[qid] = subs[-1]["grade"]["score"]
        rows = [{"at": s.get("at"), "score": (s.get("grade") or {}).get("score")} for s in subs]
        if not rows and (item.get("answer") or "").strip():
            rows = [{"at": a.get("updatedAt"), "score": None, "draft": True}]
        if rows:
            responses[qid] = rows
    return {**a, "scores": scores, "responses": responses}


def target_dir(current: Optional[str]) -> Path:
    if current:
        path = (REPO / current).resolve()
        if path.parent == QUIZ_DIR and re.fullmatch(r"quiz\d+", path.name):
            return path
    numbered = {}
    for d in QUIZ_DIR.iterdir():
        m = re.fullmatch(r"quiz(\d+)", d.name)
        if d.is_dir() and m:
            numbered[int(m.group(1))] = d
    for n in sorted(numbered):
        if not any(not p.name.startswith(".") for p in numbered[n].iterdir()):
            return numbered[n]
    return QUIZ_DIR / f"quiz{max(numbered, default=0) + 1}"


# ---------------------------------------------------------------- handler ----


class Handler(BaseHTTPRequestHandler):
    server_version = "OralQuiz/1"

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        if CONFIG.get("verbose"):
            super().log_message(fmt, *args)

    # -- plumbing --

    def _trusted(self) -> bool:
        port = CONFIG["port"]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in hosts}

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("request body too large")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _start_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _emit(self, obj: dict) -> None:
        self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.wfile.flush()

    # -- routes --

    def do_GET(self) -> None:
        if not self._trusted():
            return self._json(403, {"error": "forbidden"})
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, (APP_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/code" or path.startswith("/code/"):
            return self._send(200, (APP_DIR / "code.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/code":
            want = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("path", [""])[0]
            return self._json(200, code_payload(want))
        if path.startswith("/raw/"):
            found = find_code(urllib.parse.unquote(path[len("/raw/"):]))
            if found["kind"] != "file" or not found["path"].lower().endswith(".pdf"):
                return self._json(404, {"error": "only PDFs in the repository are served raw"})
            return self._send(200, (REPO / found["path"]).read_bytes(), "application/pdf")
        b = bank()
        if path == "/handout.pdf":
            handout = REPO / b["handout"]
            if not handout.is_file():
                return self._json(404, {"error": f"{b['handout']} is not in the repository root"})
            return self._send(200, handout.read_bytes(), "application/pdf")
        if path == "/api/info":
            return self._json(200, {
                **repo_state(), "rubric_commit": b["rubric_commit"], "repo": str(REPO), "editor": CONFIG.get("editor"), "files": repo_files(),
                "model": CONFIG.get("model") or "your Claude Code default", "claude": CONFIG["claude_version"],
            })
        if path == "/api/questions":
            return self._json(200, {
                "chips": b["chips"], "handout": b["handout"],
                "questions": [{k: q[k] for k in PUBLIC_FIELDS} for q in b["questions"]],
            })
        if path == "/api/samples":
            return self._json(200, {"samples": {q["id"]: s for q in b["questions"] if (s := read_sample(q["id"]))}})
        if path == "/api/attempts":
            out = []
            for p in sorted(ATTEMPTS_DIR.glob("a-*.json"), reverse=True):
                try:
                    out.append(summary(json.loads(p.read_text(encoding="utf-8"))))
                except (OSError, ValueError):
                    continue
            return self._json(200, {"attempts": out})
        m = re.fullmatch(r"/api/attempts/([^/]+)", path)
        if m and ATTEMPT_ID.fullmatch(m.group(1)):
            state = load_attempt(m.group(1))
            return self._json(200, state) if state else self._json(404, {"error": "no such attempt"})
        return self._json(404, {"error": "not found"})

    def do_PUT(self) -> None:
        if not self._trusted():
            return self._json(403, {"error": "forbidden"})
        m = re.fullmatch(r"/api/samples/([^/]+)", self.path)
        if m:
            return self._put_sample(m.group(1))
        m = re.fullmatch(r"/api/attempts/([^/]+)", self.path)
        if not (m and ATTEMPT_ID.fullmatch(m.group(1))):
            return self._json(404, {"error": "not found"})
        try:
            body = self._body()
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        attempt = body.get("attempt") or {}
        if attempt.get("id") != m.group(1):
            return self._json(400, {"error": "attempt id does not match the URL"})
        with attempt_lock(m.group(1)):
            old = load_attempt(m.group(1)) or {}
            # The server owns savedDir; the page cannot point it elsewhere.
            attempt["savedDir"] = (old.get("attempt") or {}).get("savedDir")
            write_atomic(attempt_path(m.group(1)), json.dumps({"attempt": attempt, "items": body.get("items") or {}}, indent=2))
        return self._json(200, {"ok": True})

    def do_POST(self) -> None:
        if not self._trusted():
            return self._json(403, {"error": "forbidden"})
        try:
            body = self._body()
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        if self.path == "/api/grade":
            return self._grade(body)
        if self.path == "/api/followup":
            return self._followup(body)
        m = re.fullmatch(r"/api/attempts/([^/]+)/save", self.path)
        if m and ATTEMPT_ID.fullmatch(m.group(1)):
            return self._save(m.group(1), body)
        return self._json(404, {"error": "not found"})

    def _put_sample(self, qid: str) -> None:
        q = question(qid)
        if q is None:
            return self._json(404, {"error": "unknown question"})
        try:
            body = self._body()
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        answer, refs, source = (str(body.get(k) or "") for k in ("answer", "refs", "source"))
        if not answer.strip():
            return self._json(400, {"error": "the sample answer is empty"})
        if len(answer) + len(refs) > MAX_SAMPLE:
            return self._json(400, {"error": "the sample answer is too long"})
        with attempt_lock("sample:" + qid):
            return self._json(200, {"sample": write_sample(q, answer, refs, source)})

    # -- grading --

    def _grade(self, body: dict) -> None:
        q = question(body.get("qid"))
        if q is None:
            return self._json(400, {"error": "unknown question"})
        answer, refs = str(body.get("answer", "")).strip(), str(body.get("refs", "")).strip()
        if not answer:
            return self._json(400, {"error": "empty answer"})
        session_id = str(uuid.uuid4())
        cmd = claude_command(session_id=session_id, schema=GRADE_SCHEMA, name=f"oral-quiz: {q['title']}")
        self._run(cmd, grade_prompt(q, answer, refs), mode="grade", session_id=session_id)

    def _followup(self, body: dict) -> None:
        q = question(body.get("qid"))
        sid = str(body.get("session_id", ""))
        message = str(body.get("message", "")).strip()
        if q is None or not SESSION_ID.fullmatch(sid) or not message:
            return self._json(400, {"error": "need qid, session_id and message"})
        cmd = claude_command(resume=sid, partial=True)
        self._run(cmd, f"{FOLLOWUP_RULES}\n\nStudent: {message}", mode="followup", session_id=sid)

    def _run(self, cmd: list[str], prompt: str, *, mode: str, session_id: str) -> None:
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd, cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as exc:
            return self._json(500, {"error": f"could not start claude: {exc}"})
        lines: queue.Queue = queue.Queue()
        err: list[str] = []

        def pump_out() -> None:
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        def pump_err() -> None:
            for line in proc.stderr:
                err.append(line)

        threading.Thread(target=pump_out, daemon=True).start()
        threading.Thread(target=pump_err, daemon=True).start()
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except OSError:
            pass

        self._start_stream()
        result = None
        try:
            self._emit({"type": "started", "session_id": session_id})
            while True:
                try:
                    line = lines.get(timeout=PING_SECONDS)
                except queue.Empty:
                    self._emit({"type": "ping"})
                    continue
                if line is None:
                    break
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                kind = ev.get("type")
                if kind == "assistant":
                    for block in (ev.get("message") or {}).get("content") or []:
                        if block.get("type") == "tool_use":
                            self._emit({"type": "activity", "text": describe_tool(block)})
                elif kind == "stream_event":
                    e = ev.get("event") or {}
                    delta = e.get("delta") or {}
                    if e.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                        self._emit({"type": "delta", "text": delta.get("text", "")})
                elif kind == "result":
                    result = ev
            proc.wait(timeout=30)
            self._finish(result, err, mode=mode, session_id=session_id, seconds=time.monotonic() - started)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page stopped the request
        except subprocess.TimeoutExpired:
            pass
        finally:
            if proc.poll() is None:
                proc.kill()

    def _finish(self, result: Optional[dict], err: list[str], *, mode: str, session_id: str, seconds: float) -> None:
        if result is None:
            tail = "".join(err)[-600:].strip() or "claude exited without a result"
            return self._emit({"type": "error", "message": tail})
        if result.get("is_error") or result.get("subtype") != "success":
            msg = result.get("result") or result.get("subtype") or "claude reported an error"
            return self._emit({"type": "error", "message": str(msg)[:600]})
        meta = {"session_id": result.get("session_id") or session_id, "cost": result.get("total_cost_usd"),
                "seconds": round(seconds, 1)}
        if mode == "grade":
            raw = result.get("structured_output")
            if not isinstance(raw, dict):
                raw = parse_json_text(str(result.get("result") or ""))
            if raw is None:
                return self._emit({"type": "error", "message": "the grader's reply held no grade; submit again"})
            return self._emit({"type": "grade", "grade": normalize_grade(raw), **meta})
        return self._emit({"type": "reply", "text": str(result.get("result") or "").strip(), **meta})

    # -- saving --

    def _save(self, attempt_id: str, body: dict) -> None:
        markdown, html = body.get("markdown"), body.get("html")
        if not isinstance(markdown, str) or not isinstance(html, str):
            return self._json(400, {"error": "need markdown and html"})
        with attempt_lock(attempt_id):
            state = load_attempt(attempt_id)
            if state is None:
                return self._json(404, {"error": "no such attempt"})
            dest = target_dir(state["attempt"].get("savedDir"))
            dest.mkdir(exist_ok=True)
            order = state["attempt"].get("order") or []
            data = {
                "format": "cs329z-oral-prep/v1",
                "savedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "repo": repo_state(),
                "rubric_commit": bank()["rubric_commit"],
                "attempt": state["attempt"],
                "questions": [q for q in map(question, order) if q],
                "items": [state["items"].get(q, {"qid": q}) for q in order],
            }
            write_atomic(dest / "quiz.md", markdown)
            write_atomic(dest / "index.html", html)
            write_atomic(dest / "quiz.json", json.dumps(data, indent=2))
            saved = str(dest.relative_to(REPO))
            state["attempt"]["savedDir"] = saved
            write_atomic(attempt_path(attempt_id), json.dumps(state, indent=2))
        return self._json(200, {"dir": saved, "files": ["quiz.md", "quiz.json", "index.html"]})


# ------------------------------------------------------------------- main ----


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the oral-quiz practice page and grade answers with Claude Code.")
    ap.add_argument("--port", type=int, default=8329)
    ap.add_argument("--model", help="model for the grader, e.g. opus or sonnet (default: your Claude Code default)")
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="grader effort level")
    ap.add_argument("--budget", type=float, default=1.0, help="most US dollars one grading or follow-up call may spend (default 1.0)")
    ap.add_argument("--claude", default=shutil.which("claude"), help="path to the claude CLI")
    ap.add_argument("--editor", choices=["cursor", "vscode", "windsurf", "none"],
                    default="cursor" if shutil.which("cursor") else "vscode" if shutil.which("code") else "none",
                    help="editor that code links open in (default: cursor or vscode, whichever is installed)")
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    ap.add_argument("--verbose", action="store_true", help="log every request")
    args = ap.parse_args()
    if not args.claude:
        sys.exit("The claude CLI was not found on PATH. Install Claude Code or pass --claude /path/to/claude.")
    try:
        version = subprocess.run([args.claude, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        sys.exit(f"Could not run {args.claude}: {exc}")
    CONFIG.update(port=args.port, model=args.model, effort=args.effort, budget=args.budget,
                  claude=args.claude, claude_version=version, verbose=args.verbose,
                  editor=None if args.editor == "none" else args.editor)
    ensure_attempts_dir()
    bank()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        sys.exit(f"Port {args.port} is not free ({exc}). Pass --port with another number.")
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Oral quiz practice: {url}")
    print(f"Grader: {version}, model {args.model or 'default'}, in {REPO}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
