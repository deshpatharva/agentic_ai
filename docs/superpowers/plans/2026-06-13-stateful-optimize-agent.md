# TDD: Stateful Agentic `/optimize` — Groq Llama 3.1 8B Co-Pilot

**Author:** Senior AI Full-Stack Engineer
**Date:** 2026-06-13
**Status:** Blueprint / for review

---

## 0. Context & guiding principle

The current `/optimize` route (`frontend/src/pages/ChatOptimizePage.jsx`) is **not** an LLM
chat — it is a hand-written JavaScript state machine: `jdText → matchedProfiles → selectedProfile
→ startPipeline()`. It calls four existing backend endpoints in a fixed order:

| Step | Endpoint | Handler |
|------|----------|---------|
| Scrape URL | `POST /jd/scrape` | `jd/router.py::scrape_jd` |
| Match profiles | `POST /profile/match` | `jd/router.py::match_profiles` |
| Seed a job | `POST /profile/prepare-job` | `profiles/router.py::prepare_job_from_profile` |
| Run + stream | `POST /run-pipeline` → SSE `GET /status/{job_id}` | `main.py::run_pipeline` / `stream_status` |

**Guiding principle of this design:** we are wrapping a *conversational planning layer* in front of
this proven chain — **not** replacing it. The LLM gathers intent and fills the three inputs the
chain already needs (`jd_text`, `profile_id`, `instruction`), then fires the **existing** functions
verbatim. The agent never re-implements optimization logic.

### Stack facts this design conforms to (verified in repo)

- **Backend:** FastAPI, async SQLAlchemy 2.0 (`DeclarativeBase`), PostgreSQL via `asyncpg`, Alembic
  (latest migration `0014`; ours is **`0015`**).
- **LLM access:** all calls go through `backend/llm.py::complete(prompt, model)` → LiteLLM
  `acompletion`. Returns `{text, input_tokens, output_tokens, cost_usd}`. **No streaming, no
  messages-array support today** — we extend it (§2).
- **Groq Llama 3.1 8B is already wired:** `config.py::MODEL_CRITIC = "groq/llama-3.1-8b-instant"`,
  `GROQ_API_KEY` already read. LiteLLM is the project's Groq transport — we keep that convention
  rather than adding the raw `groq` SDK.
- **Auth:** `get_current_user` (Bearer JWT) returns `User` with `.id: UUID`. Short-lived SSE tokens
  via `POST /user/sse-token` + `decode_sse_token` exist because `EventSource` can't send headers.
- **SSE convention:** `sse_starlette.EventSourceResponse`, events persisted in `pipeline_events`,
  Postgres `LISTEN/NOTIFY` for push (survives the 2 gunicorn workers + restarts).
- **There is already a stateless conversational pattern** (`profiles/router.py::interview_message`)
  that passes full history each turn — we generalize its idea, but make it stateful + streaming.

---

## 1. Session Memory Integration Strategy

### 1.1 Store choice — Postgres table, not Redis

**Decision: a dedicated `chat_messages` table (+ `chat_sessions`), via Alembic `0015`.** Rationale:

- Redis is **not** in the stack (`requirements.txt`, Dockerfile, config — none reference it). Adding
  it means new infra, a new connection pool, new failure modes, and a second source of truth.
- Conversations are low-volume, per-user, and benefit from durability (a user returning tomorrow
  should see their thread). Postgres already gives us that with zero new infra.
- It matches every existing pattern: `Uuid` PKs, `JSON` columns, tz-aware `created_at`.

> If chat volume ever dwarfs pipeline volume (10–100× more turns), promote the *hot window* to Redis
> as a read-through cache in front of this table. The table stays the system of record. Out of scope
> now.

### 1.2 JSON schema for the conversation array

Stored canonical form (one row per turn), and the in-memory/wire shape passed to Groq:

```jsonc
// wire / window shape — exactly what Groq's messages[] expects
[
  { "role": "system",    "content": "<agent system prompt, injected at runtime>" },
  { "role": "user",      "content": "Here's the JD: https://…" },
  { "role": "assistant", "content": "Got it — which profile should I tailor, your DE or SWE one?" },
  { "role": "user",      "content": "the data engineering one" }
]
```

`role ∈ {system, user, assistant}`. The `system` row is **never persisted** — it is injected fresh
each turn from `config` so prompt edits ship without a migration (see §3).

### 1.3 Models — `backend/db/models.py` (append)

```python
class ChatSession(Base):
    """One optimization conversation thread for a user."""
    __tablename__ = "chat_sessions"

    id         = Column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id    = Column(Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Snapshot of intent the agent has gathered so far (jd_text, profile_id, instruction…).
    # Lets us resume a thread without re-deriving state from message text.
    context    = Column(JSON, nullable=True)
    # Set once the [READY_TO_OPTIMIZE] handoff fires, linking the thread to its pipeline run.
    job_id     = Column(Uuid(), ForeignKey("pipeline_jobs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    messages = relationship("ChatMessage", back_populates="session",
                            cascade="all, delete-orphan", order_by="ChatMessage.id")


class ChatMessage(Base):
    """Append-only turn log. `id` (sequential) is the canonical ordering key."""
    __tablename__ = "chat_messages"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(Uuid(), ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    role         = Column(String(16), nullable=False)   # "user" | "assistant"
    content      = Column(Text, nullable=False)
    input_tokens  = Column(Integer, nullable=True, default=0)
    output_tokens = Column(Integer, nullable=True, default=0)
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("ChatSession", back_populates="messages")
```

Mirrors `PipelineJob`/`PipelineEvent` exactly (autoincrement `id` for ordering, `JSON` context,
token columns so chat cost flows into the same cost-tracking story).

### 1.4 Alembic migration `backend/alembic/versions/0015_add_chat_sessions.py`

```python
"""add chat_sessions and chat_messages

Revision ID: 0015_add_chat_sessions
Revises: 0014_add_tokens_to_pipeline_jobs
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_add_chat_sessions"
down_revision = "0014_add_tokens_to_pipeline_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", "chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_user_id", "chat_sessions")
    op.drop_table("chat_sessions")
```

### 1.5 `session_id` middleware/dependency — derived from the authenticated user

`get_current_user` already gives us the identity. We do **not** trust a client-supplied `user_id`;
the session is always scoped to `current_user.id`. The client sends an optional `session_id` to
continue a thread; absent/unknown → we create one. This is a thin FastAPI dependency, not WSGI
middleware (matches the project's dependency-injection style).

```python
# backend/chat/dependencies.py
import uuid
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import ChatSession, User
from db.session import get_db


async def get_or_create_session(
    session_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSession:
    """Resolve the conversation thread for this turn, scoped to the authenticated user.

    - session_id present & owned  -> resume it
    - session_id present & foreign -> 404 (never leak another user's thread)
    - session_id absent/invalid    -> create a fresh thread for this user
    """
    if session_id:
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            sid = None
        if sid:
            sess = await db.scalar(select(ChatSession).where(ChatSession.id == sid))
            if sess and sess.user_id == current_user.id:
                return sess
            if sess:                       # exists but not ours
                raise HTTPException(status_code=404, detail="Session not found.")

    sess = ChatSession(user_id=current_user.id, context={})
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess
```

### 1.6 Sliding-window utility (last 8–10 turns)

Keeps the system prompt pinned, then the most recent `n` stored turns. We trim by **turn count**
here; a token-budget trim is a trivial extension (we already count tokens per row) and noted inline.

```python
# backend/chat/window.py
from typing import TypedDict

WINDOW_TURNS = 10   # last N user/assistant turns sent to Groq (8–10 per spec)


class ChatTurn(TypedDict):
    role: str       # "system" | "user" | "assistant"
    content: str


def build_window(system_prompt: str, history: list, *, n: int = WINDOW_TURNS) -> list[ChatTurn]:
    """Return Groq-ready messages[]: pinned system prompt + last n turns.

    `history` is a list of ORM ChatMessage (ascending id) or dicts with .role/.content.
    The system prompt is injected fresh every turn — never read from storage — so prompt
    edits ship without touching data.
    """
    recent = history[-n:] if len(history) > n else history
    window: list[ChatTurn] = [{"role": "system", "content": system_prompt}]
    for m in recent:
        role = getattr(m, "role", None) or m["role"]
        content = getattr(m, "content", None) or m["content"]
        window.append({"role": role, "content": content})
    return window
    # Token-budget variant: instead of [-n:], walk backwards summing
    # (input_tokens+output_tokens) until <= BUDGET, then reverse.
```

---

## 2. Backend API endpoint — refactor + SSE streaming

### 2.1 Extend `llm.py` with a streaming, multi-turn entry point

`complete()` takes a single prompt and returns once. A chat agent needs (a) a `messages[]` array and
(b) token-by-token streaming. We add a sibling generator that keeps the same LiteLLM convention
(so provider routing, `drop_params`, timeouts all behave identically) and still surfaces token usage
for cost tracking.

```python
# backend/llm.py  (append)
from typing import AsyncIterator

async def stream_chat(messages: list[dict], model: str) -> AsyncIterator[dict]:
    """Stream a multi-turn chat completion token-by-token via LiteLLM.

    Yields dicts:
      {"type": "token", "text": "<delta>"}            # 0..N times
      {"type": "usage", "input_tokens": int,          # exactly once, last
                        "output_tokens": int, "cost_usd": float}

    `messages` is the standard [{role, content}, ...] array (system + window).
    Routes to Groq when model is "groq/llama-3.1-8b-instant" — same prefix convention as complete().
    """
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        timeout=_CALL_TIMEOUT_S,
        stream=True,
        stream_options={"include_usage": True},   # ask Groq to send a final usage chunk
    )

    in_tok = out_tok = 0
    cost = 0.0
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield {"type": "token", "text": delta}
        usage = getattr(chunk, "usage", None)
        if usage:                                   # final chunk carries totals
            in_tok = usage.prompt_tokens or 0
            out_tok = usage.completion_tokens or 0
            cost = getattr(chunk, "_hidden_params", {}).get("response_cost") or 0.0

    yield {"type": "usage", "input_tokens": in_tok,
           "output_tokens": out_tok, "cost_usd": float(cost)}
```

> A bounded retry-on-transient (as `complete()` has) is harder mid-stream; for an 8B model with sub-
> second TTFT, we instead let the route emit an `error` SSE event and let the client offer "retry"
> — cheaper and clearer than replaying a partial stream.

### 2.2 Config

```python
# backend/config.py  (add near the other models)
# Conversational optimize co-pilot — Llama 3.1 8B via Groq (fast, near-free, good instruction-following)
MODEL_CHAT_AGENT = "groq/llama-3.1-8b-instant"
CHAT_WINDOW_TURNS = 10
```

### 2.3 The route — `POST /optimize/chat` (SSE response)

**Why POST-returns-SSE, not `EventSource`:** `EventSource` is GET-only and can't carry a request
body or an `Authorization` header — that's precisely why the pipeline had to invent `/user/sse-token`
and pass it in the URL. For chat we must send the user's message *and* authenticate, so we return an
`EventSourceResponse` from a normal **POST** and the frontend reads it with `fetch()` + a stream
reader (§4). This keeps the Bearer-token auth (no token-in-URL) and needs no SSE-token dance.

```python
# backend/chat/router.py
import json
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from config import MODEL_CHAT_AGENT, CHAT_WINDOW_TURNS
from db.models import ChatMessage, ChatSession, User
from db.session import get_db, AsyncSessionLocal
from llm import stream_chat
from auth.dependencies import get_current_user
from chat.dependencies import get_or_create_session
from chat.window import build_window
from chat.agent import SYSTEM_PROMPT, render_system_prompt, extract_handoff
from chat.handoff import fire_optimizer            # §3.2

router = APIRouter(prefix="/optimize", tags=["optimize-agent"])


class ChatTurnRequest(BaseModel):
    session_id: str | None = None
    message: str


@router.post("/chat")
async def optimize_chat(
    body: ChatTurnRequest,
    current_user: User = Depends(get_current_user),
    session: ChatSession = Depends(get_or_create_session),
    db: AsyncSession = Depends(get_db),
):
    # 1. Persist the user turn immediately (durable history).
    db.add(ChatMessage(session_id=session.id, role="user", content=body.message))
    await db.commit()

    # 2. Load history (ascending) and build the sliding window + fresh system prompt.
    history = (await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id)
    )).scalars().all()

    system_prompt = render_system_prompt(current_user, session.context or {})
    window = build_window(system_prompt, history, n=CHAT_WINDOW_TURNS)

    async def event_generator():
        # Always tell the client its session id first so it can continue the thread.
        yield {"event": "session", "data": json.dumps({"session_id": str(session.id)})}

        assembled = []          # full assistant text, for persistence + sentinel scan
        usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

        try:
            async for ev in stream_chat(window, MODEL_CHAT_AGENT):
                if ev["type"] == "token":
                    assembled.append(ev["text"])
                    # Stream visible tokens, but hold back the trigger sentinel (§3.2).
                    safe = _redact_sentinel_tail("".join(assembled))
                    if ev["text"] and not _in_sentinel("".join(assembled)):
                        yield {"event": "token", "data": json.dumps({"text": ev["text"]})}
                elif ev["type"] == "usage":
                    usage = ev
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"message": "Agent stream failed."})}
            return

        full_text = "".join(assembled)

        # 3. Persist the assistant turn (with the sentinel stripped from stored content).
        clean_text, handoff = extract_handoff(full_text)
        async with AsyncSessionLocal() as wdb:
            wdb.add(ChatMessage(
                session_id=session.id, role="assistant", content=clean_text,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
            ))
            await wdb.commit()

        # 4. If the agent green-lit optimization, fire the EXISTING chain and hand off.
        if handoff:
            job_id, sse_token = await fire_optimizer(current_user, session, handoff)
            yield {"event": "handoff", "data": json.dumps({
                "job_id": job_id,
                "sse_token": sse_token,        # short-lived; frontend opens /status/{job_id}
            })}

        yield {"event": "done", "data": json.dumps({"session_id": str(session.id)})}

    return EventSourceResponse(event_generator())
```

Mounted in `main.py` alongside the others:

```python
from chat.router import router as chat_router
app.include_router(chat_router)        # /optimize/chat
```

> `_in_sentinel` / `_redact_sentinel_tail` (helpers) suppress any text once a `[READY_TO_OPTIMIZE`
> prefix appears in the stream, so the raw control token is never shown in a bubble. They live in
> `chat/agent.py` next to `extract_handoff` — see §3.2.

---

## 3. Smart-Agent system prompt & execution hook

### 3.1 System prompt — `backend/chat/agent.py`

The prompt is rendered per-turn so it can embed the user's actual profile labels (their real options),
which both grounds the conversation and lets the model emit a valid `profile_id` at handoff.

```python
# backend/chat/agent.py
import json, re
from db.models import User

SYSTEM_PROMPT = """You are ResumeAI's Optimization Co-Pilot — a sharp, friendly career strategist \
embedded in the user's dashboard. Your job is to help the user tailor one of THEIR saved resume \
profiles to a specific job, then launch the optimizer for them.

YOU CAN SEE the user's saved profiles (listed below). You CANNOT browse the web or read files.

CONVERSATION GOALS, in order:
1. Obtain the target job. Accept a pasted job description OR a job URL. If they give a URL, tell them
   you'll fetch it (the system scrapes it for you on launch) — do not pretend to read it yourself.
2. Help them pick which profile to tailor. Recommend the closest-matching profile from their list and
   say why in one sentence. If only one profile exists, confirm it.
3. Surface gaps conversationally: skills/keywords the JD wants that the chosen profile may be light on.
   Ask at most TWO clarifying questions total — keep momentum, don't interrogate.
4. When the user clearly says go ahead (e.g. "run it", "do it", "go", "optimize"), LAUNCH.

STYLE: concise, warm, expert. 1–3 sentences per reply. Never invent the user's experience or skills.

LAUNCH PROTOCOL — read carefully:
When and ONLY when the user has (a) given a job description or URL and (b) chosen a profile and
(c) given the green light, end your reply with EXACTLY this control token on its own line:

[READY_TO_OPTIMIZE: {"profile_id": "<id from the list>", "instruction": "<one-line tailoring note or empty>"}]

Rules for the token:
- Emit it at most once, only at launch, as the LAST thing in your message.
- profile_id MUST be one of the ids in the profile list below — never fabricate one.
- Put any special user instruction (e.g. "emphasize leadership") in instruction; else "".
- Do NOT include the job text in the token — the system already has it from the conversation.
- Before the token, write one short human sentence like "Great — launching the optimizer on your
  Data Engineer profile now." The token itself is hidden from the user."""


def render_system_prompt(user: User, context: dict) -> str:
    """Inject the user's real profiles + any gathered context into the system prompt."""
    profiles = context.get("profiles", [])      # [{id, label}] cached on the session (see handoff)
    if profiles:
        listing = "\n".join(f'- id={p["id"]}  label="{p["label"]}"' for p in profiles)
    else:
        listing = "(no saved profiles — tell the user to create one at /profiles/new first)"
    jd_state = "A job description has been provided." if context.get("jd_text") \
        else "No job description yet — ask for one."
    return f"{SYSTEM_PROMPT}\n\nUSER'S SAVED PROFILES:\n{listing}\n\nSTATE: {jd_state}"


_HANDOFF_RE = re.compile(r"\[READY_TO_OPTIMIZE:\s*(\{.*?\})\s*\]", re.DOTALL)


def extract_handoff(text: str) -> tuple[str, dict | None]:
    """Split assistant text into (visible_text, handoff_payload|None).

    Strips the control token from what we store/show. Returns parsed JSON payload if present
    and valid; tolerates the model fumbling the JSON by returning None (we then just continue
    the conversation instead of firing).
    """
    m = _HANDOFF_RE.search(text)
    if not m:
        return text.strip(), None
    visible = (text[:m.start()] + text[m.end():]).strip()
    try:
        payload = json.loads(m.group(1))
    except json.JSONDecodeError:
        return visible, None
    return visible, payload
```

### 3.2 Execution hook — intercept the token, fire the EXISTING chain

This is the crux: the backend detects the sentinel and calls the **same functions** the JS state
machine called — no optimizer logic is reimplemented. We reuse `prepare_job_from_profile`'s body
(seed a `PipelineJob` from the profile), then `run_pipeline`'s body (flip to running + enqueue
`_run_pipeline_task`), and mint an SSE token so the frontend can subscribe to the existing
`/status/{job_id}` stream.

```python
# backend/chat/handoff.py
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from db.session import AsyncSessionLocal
from db.models import JobStatus, PipelineJob, Profile, ChatSession, User
from utils.profile_utils import sections_to_text
from auth.router import _mint_sse_token          # factor the token builder out of get_sse_token


async def fire_optimizer(user: User, session: ChatSession, handoff: dict) -> tuple[str, str]:
    """Turn a [READY_TO_OPTIMIZE] payload into a running pipeline. Returns (job_id, sse_token).

    Reuses the exact same steps as POST /profile/prepare-job + POST /run-pipeline so the
    optimizer's behaviour is identical to the legacy flow — the agent is just the new front door.
    """
    profile_id = handoff.get("profile_id", "")
    instruction = handoff.get("instruction", "") or ""
    jd_text = (session.context or {}).get("jd_text", "")
    if not jd_text:
        raise ValueError("handoff fired without jd_text in session context")

    async with AsyncSessionLocal() as db:
        # Ownership-checked profile load (same guard as _get_owned / run_pipeline).
        prof = await db.scalar(
            select(Profile).where(Profile.id == uuid.UUID(profile_id),
                                  Profile.user_id == user.id)
        )
        if not prof:
            raise ValueError("handoff referenced a profile the user does not own")

        resume_text = sections_to_text(prof.sections or {}) or "Resume text not available."

        # ── prepare-job equivalent ──
        job = PipelineJob(
            user_id=user.id,
            original_filename=f"{prof.label or 'profile'}.txt",
            resume_text=resume_text,
            jd_text=jd_text,
            status=JobStatus.running,            # run-pipeline flips pending->running
            updated_at=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Link the conversation to its run.
        sess = await db.get(ChatSession, session.id)
        sess.job_id = job.id
        await db.commit()

    # ── run-pipeline equivalent: enqueue the existing background task ──
    from main import _run_pipeline_task          # same task the legacy route uses
    import asyncio
    asyncio.create_task(_run_pipeline_task(str(job.id), str(user.id)))

    sse_token = _mint_sse_token(str(user.id))     # frontend opens /status/{job_id}?token=...
    return str(job.id), sse_token
```

Two tiny supporting refactors (non-breaking):

1. **`auth/router.py`** — extract the token body of `get_sse_token` into a reusable
   `_mint_sse_token(user_id) -> str`; the existing route calls it. (Pure refactor.)
2. **Plan-limit parity:** the legacy `/run-pipeline` depends on `check_plan_limit`. To keep quota
   enforcement, call the same check before `fire_optimizer` (e.g. run the `DailyUsageCounter` lookup
   in the route and emit an `error` SSE event with the upgrade message on 429, mirroring the existing
   `429 → upgrade_message` handling the frontend already knows).

### 3.3 JD capture into session context

When the user pastes a URL or JD in chat, we want the real scraped text in
`session.context["jd_text"]` (the agent must not hallucinate it).

**Decision (locked): pre-resolve in the route, before the LLM call.** The route inspects
`body.message`; if it contains a URL it calls the existing `jd/router.py::scrape_jd` logic, otherwise
it treats a long message as the pasted JD. It writes `session.context["jd_text"]` and seeds
`session.context["profiles"]` from `match_profiles`. The LLM then reasons over already-resolved facts
and picks among the user's *real* profiles — no hallucinated JD, fewer round-trips, and the proven
scraping/matching code is reused unchanged.

```python
# inside POST /optimize/chat, before building the window — runs only while jd_text is unset
ctx = dict(session.context or {})
if not ctx.get("jd_text"):
    text = body.message.strip()
    if re.match(r"^https?://", text, re.I):
        ctx["jd_text"] = await _scrape_jd_text(text)        # reuse jd/router.py::scrape_jd
    elif len(text) > 200:                                   # heuristic: a pasted JD, not a chat reply
        ctx["jd_text"] = text
    if ctx.get("jd_text"):
        matches = await _match_profiles(current_user, ctx["jd_text"], db)  # reuse match_profiles
        ctx["profiles"] = [{"id": str(m["id"]), "label": m["label"]} for m in matches]
        session.context = ctx
        await db.commit()
```

> Rejected alternative: an agent-driven `[FETCH_JD: {url}]` intermediate token. More LLM round-trips
> and more failure surface on an 8B model, for no benefit over deterministic pre-resolution.

---

## 4. Frontend changes (`ChatOptimizePage.jsx`)

The page keeps its existing pipeline-progress UI (`PipelineProgress`, `ScoreReveal`) wholesale — we
only replace the **input→conversation** half. New flow:

1. On send, POST to `/optimize/chat` with `{ session_id, message }` using `fetch` (so we send the
   `Authorization` header + body) and read the SSE stream from the response body.
2. Handle events: `session` → store `session_id`; `token` → append into the in-progress assistant
   bubble (token-by-token); `handoff` → we received `{job_id, sse_token}`, so **reuse the existing
   `EventSource('/status/{job_id}?token=…')` code path verbatim** to drive `PipelineProgress`;
   `done`/`error` → finalize.

```jsx
async function sendToAgent(message) {
  const res = await fetch(`${client.defaults.baseURL}/optimize/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,        // same token the axios client uses
    },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let assistantId = addMsg("assistant", "");          // empty bubble we stream into

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // Parse SSE frames ("event: x\ndata: {...}\n\n")
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      const ev = parseSSEFrame(frame);                // {event, data}
      if (ev.event === "session") setSessionId(ev.data.session_id);
      else if (ev.event === "token") appendToMsg(assistantId, ev.data.text);
      else if (ev.event === "handoff") startStatusStream(ev.data.job_id, ev.data.sse_token);
      else if (ev.event === "error") markMsgError(assistantId, ev.data.message);
    }
  }
}
```

`startStatusStream` is the **existing** `EventSource` block lifted out of `startPipeline` — the
agent's `handoff` event simply replaces the old `/profile/prepare-job` + `/run-pipeline` calls. The
pipeline-progress and score-reveal experience is unchanged.

---

## 5. Implementation order (step-by-step)

1. **Migration & models** — add `ChatSession`/`ChatMessage` (`db/models.py`) + Alembic `0015`;
   `alembic upgrade head`; add a model round-trip test next to `tests/test_migrations.py`.
2. **LLM streaming** — add `stream_chat` to `llm.py`; unit-test it the way `tests/test_llm.py`
   mocks `litellm.acompletion` (assert Groq prefix routes through, assert a `usage` event is yielded).
3. **Agent module** — `chat/agent.py` (prompt + `extract_handoff`); pure-function tests for the
   sentinel regex (valid, malformed JSON, no token, token mid-text).
4. **Window + session dep** — `chat/window.py`, `chat/dependencies.py`; test ownership 404 + auto-create.
5. **Handoff** — `chat/handoff.py` + the `_mint_sse_token` refactor in `auth/router.py`; test that
   firing creates a `running` `PipelineJob` and enqueues `_run_pipeline_task` (mock it).
6. **Route** — `chat/router.py`, mount in `main.py`; integration test the SSE event sequence
   (`session → token* → [handoff] → done`) with `stream_chat` mocked.
7. **JD/profile pre-resolution** — wire `scrape_jd` / `match_profiles` reuse into context seeding (§3.3).
8. **Frontend** — swap the input half of `ChatOptimizePage.jsx` to `sendToAgent`; lift
   `startStatusStream` out of `startPipeline`; keep progress/score components.
9. **Quota parity** — apply `check_plan_limit` equivalent before `fire_optimizer`; surface 429 as an
   `error` event with `upgrade_message`.
10. **Session cleanup** — extend the stuck-job reaper (which already calls
    `cleanup_stale_sessions`) to also delete `chat_sessions` with no activity > N days, or rely on
    `ON DELETE CASCADE` from user deletion. (Optional; low volume.)

## 6. Risk notes

- **8B sentinel reliability.** Llama 3.1 8B can mangle the JSON or emit the token early.
  `extract_handoff` fails safe (no token → keep talking); the `profile_id ∈ list` guard in
  `fire_optimizer` rejects fabricated ids. Consider a one-shot "are you sure?" confirm in the UI on
  first handoff if false-fires appear in testing.
- **Streaming + 2 gunicorn workers.** SSE is fine (each request pins one worker for its duration);
  the pipeline already runs under this exact topology with `--timeout 300`.
- **Cost.** Llama 3.1 8B on Groq is ~free at this volume; we still record `input/output_tokens` per
  `ChatMessage` so chat cost joins the existing cost-tracking story without special-casing.
- **No token in URL.** POST-returns-SSE keeps the Bearer token in a header — strictly better than the
  pipeline's `?token=` SSE-token workaround, which we only reuse for the *handoff* `/status` stream
  (unchanged, already audited).
