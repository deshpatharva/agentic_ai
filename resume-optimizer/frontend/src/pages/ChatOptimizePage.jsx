import { useState, useRef, useEffect, useCallback } from 'react';
import { Send } from 'lucide-react';
import { clsx } from 'clsx';
import client, { buildDownloadUrl } from '../api/client';
import { getSession } from '../api/sessions';
import AppShell from '../components/layout/AppShell';
import ChatMessage from '../components/ChatMessage';
import PipelineProgress from '../components/PipelineProgress';
import ScoreReveal from '../components/ScoreReveal';
import SessionRail from '../components/chat/SessionRail';
import ProfilePicker from '../components/chat/ProfilePicker';
import WelcomeHero from '../components/chat/WelcomeHero';
import useChatSessionStore from '../store/chatSessionStore';

const SESSION_KEY = 'chat_session_id';

function autoResize(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

function getToken() {
  return localStorage.getItem('token') || sessionStorage.getItem('token') || '';
}

function parseSSEFrame(frame) {
  const lines = frame.split('\n');
  let event = 'message';
  let data = '';
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data = line.slice(5).trim();
  }
  try { return { event, data: JSON.parse(data) }; } catch { return { event, data: {} }; }
}

export default function ChatOptimizePage() {
  const [messages, setMessages]         = useState([]);
  const [input, setInput]               = useState('');
  const [phase, setPhase]               = useState('idle');
  const [sessionId, setSessionId]       = useState(null);
  const [stage, setStage]               = useState(null);
  const [stageMessage, setStageMessage] = useState('');
  const [iteration, setIteration]       = useState(0);
  const [liveScores, setLiveScores]     = useState(null);
  const [result, setResult]             = useState(null);
  const [downloadUrl, setDownloadUrl]   = useState(null);
  const [railOpen, setRailOpen]         = useState(true);
  const [streamingMsgId, setStreamingMsgId] = useState(null);
  // Profile picker: show chips when JD is captured but optimizer not yet launched
  const [profileSuggestions, setProfileSuggestions] = useState([]);
  const [optimizerLaunched, setOptimizerLaunched]   = useState(false);

  const esRef        = useRef(null);
  const pollRef      = useRef(null);   // result-polling interval (SSE fallback)
  const chatAbortRef = useRef(null);   // aborts the in-flight /optimize/chat stream
  const bottomRef    = useRef(null);
  const textareaRef  = useRef(null);

  const { fetchSessions } = useChatSessionStore();

  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  useEffect(() => {
    const stored = sessionStorage.getItem(SESSION_KEY);
    if (stored) loadSession(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup on unmount: close stream and stop any polling.
  useEffect(() => () => {
    esRef.current?.close();
    chatAbortRef.current?.abort();
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  // Apply a persisted last_result to the result UI (shared by load + poll + SSE).
  const applyLastResult = useCallback((lr) => {
    if (!lr) return;
    setPhase('done');
    setResult({ finalScore: lr.final_score ?? 0, iterations: lr.iterations ?? 0, report: lr.report || null });
    setLiveScores(lr.scores ? { scores: lr.scores, score: lr.final_score } : null);
    setDownloadUrl(lr.download_url || null);
    setStage(null);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, stage, result]);

  const addMsg = useCallback((role, content, isError = false) => {
    const id = Date.now() + Math.random();
    setMessages((prev) => [...prev, { role, content, isError, id }]);
    return id;
  }, []);

  const updateMsg = useCallback((id, patch) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }, []);

  // ── Load a past session ──────────────────────────────────────────────────────
  async function loadSession(id) {
    // Cancel any in-flight chat/SSE stream so its late events can't clobber the
    // session we're about to load.
    chatAbortRef.current?.abort();
    esRef.current?.close();
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    try {
      const { data } = await getSession(id);
      setSessionId(data.id);
      sessionStorage.setItem(SESSION_KEY, data.id);
      setMessages(
        data.messages.map((m) => ({ id: m.id, role: m.role, content: m.content, isError: false }))
      );
      setStreamingMsgId(null);

      const launched = Boolean(data.optimizer_launched);
      setOptimizerLaunched(launched);

      // Show profile picker if JD captured but optimizer not yet launched.
      if (data.has_jd && !launched && data.profiles?.length) {
        setProfileSuggestions(data.profiles);
      } else {
        setProfileSuggestions([]);
      }

      if (data.last_result) {
        applyLastResult(data.last_result);
      } else {
        setPhase('idle');
        setResult(null);
        setDownloadUrl(null);
        setLiveScores(null);
        setStage(null);
      }
    } catch {
      sessionStorage.removeItem(SESSION_KEY);
    }
  }

  // ── New chat ─────────────────────────────────────────────────────────────────
  function newChat() {
    esRef.current?.close();
    chatAbortRef.current?.abort();
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setMessages([]);
    setInput('');
    setSessionId(null);
    setPhase('idle');
    setStage(null);
    setStageMessage('');
    setIteration(0);
    setLiveScores(null);
    setResult(null);
    setDownloadUrl(null);
    setStreamingMsgId(null);
    setProfileSuggestions([]);
    setOptimizerLaunched(false);
    sessionStorage.removeItem(SESSION_KEY);
  }

  // ── SSE status stream for the pipeline ───────────────────────────────────────
  function startStatusStream(jobId, sseToken) {
    setPhase('running');
    setStage(null);
    setStageMessage('');
    setIteration(0);
    setLiveScores(null);
    setResult(null);
    setDownloadUrl(null);
    setProfileSuggestions([]);
    setOptimizerLaunched(true);

    // `resolved` flips once we have a terminal outcome (via SSE or polling),
    // so a late EventSource error/close can't overwrite a finished run.
    let resolved = false;
    const finish = () => { resolved = true; esRef.current?.close(); if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

    // Fallback: poll the session for the persisted result. SSE over some proxies
    // (e.g. Azure) can drop before delivering `done`, yet the job finishes fine.
    function startPolling() {
      if (pollRef.current || resolved) return;
      const sid = sessionId || sessionStorage.getItem(SESSION_KEY);
      if (!sid) return;
      let attempts = 0;
      pollRef.current = setInterval(async () => {
        attempts += 1;
        try {
          const { data } = await getSession(sid);
          if (data.last_result) {
            finish();
            applyLastResult(data.last_result);
            fetchSessions();
            return;
          }
        } catch {}
        if (attempts >= 60) { // ~3 min at 3s — give up, leave a soft note
          finish();
          setPhase((p) => (p === 'done' ? p : 'error'));
          addMsg('assistant', 'The optimizer is taking longer than expected. Your job may still be running — refresh in a moment to see the result.', true);
        }
      }, 3000);
    }

    // Close any previous status stream before opening a new one, so a second
    // optimize launch can't leak the first connection or have its late terminal
    // event tear down this one.
    esRef.current?.close();
    const es = new EventSource(
      `${client.defaults.baseURL}/status/${jobId}?token=${encodeURIComponent(sseToken)}`
    );
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.type === 'stage')   { setStage(ev.stage); setStageMessage(ev.message || ''); }
        if (ev.type === 'average') { setIteration(ev.iteration || 0); setLiveScores(ev); }
        if (ev.type === 'done') {
          finish();
          setPhase('done');
          setDownloadUrl(ev.download_url);
          setResult({ finalScore: ev.final_score ?? 0, iterations: ev.iterations ?? 0, report: ev.report || null });
          fetchSessions();
        }
        if (ev.type === 'error') {
          finish();
          setPhase('error');
          addMsg('assistant', `❌ ${ev.message || 'Pipeline failed.'}`, true);
        }
      } catch {}
    };
    es.onerror = () => {
      es.close(); // stop EventSource's own retries; we poll instead
      if (resolved) return;
      // Don't declare failure — fall back to polling for the persisted result.
      startPolling();
    };
  }

  // ── Core send logic (shared by textarea and profile picker) ──────────────────
  async function sendMessage(text) {
    if (!text?.trim() || phase === 'running' || phase === 'chatting') return;

    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    addMsg('user', text);
    setPhase('chatting');
    setProfileSuggestions([]); // hide picker while AI responds

    const assistantId = addMsg('assistant', '');
    setStreamingMsgId(assistantId);
    const isFirstTurn = !sessionId;

    // New AbortController per send; aborting it (session switch / unmount) cancels
    // the stream so its late events can't mutate a different session's state.
    chatAbortRef.current?.abort();
    const ac = new AbortController();
    chatAbortRef.current = ac;

    try {
      const res = await fetch(`${client.defaults.baseURL}/optimize/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({ session_id: sessionId, message: text }),
        signal: ac.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 403 && err?.detail?.error === 'profile_incomplete') {
          updateMsg(assistantId, { content: `❌ ${err.detail.message}`, isError: true, action: err.detail.action });
          setPhase('idle');
          setStreamingMsgId(null);
          return;
        }
        const msg = err?.detail?.upgrade_message || err?.detail?.message || err?.detail || 'Request failed.';
        updateMsg(assistantId, { content: `❌ ${msg}`, isError: true });
        setPhase('idle');
        setStreamingMsgId(null);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let assistantText = '';

      for (;;) {
        const { value, done } = await reader.read();
        if (done || ac.signal.aborted) break;
        buf += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const { event, data } = parseSSEFrame(frame);

          if (event === 'session' && data.session_id) {
            setSessionId(data.session_id);
            sessionStorage.setItem(SESSION_KEY, data.session_id);
            if (isFirstTurn) setTimeout(() => fetchSessions(), 500);

            // Update profile picker state from session event.
            const launched = Boolean(data.optimizer_launched);
            setOptimizerLaunched(launched);
            if (data.has_jd && !launched && data.profiles?.length) {
              setProfileSuggestions(data.profiles);
            }

          } else if (event === 'token' && data.text) {
            assistantText += data.text;
            updateMsg(assistantId, { content: assistantText });

          } else if (event === 'final' && data.content !== undefined) {
            assistantText = data.content;
            // Ensure bubble is never empty — use a zero-width space so min-height holds.
            updateMsg(assistantId, { content: assistantText || '​' });

          } else if (event === 'handoff') {
            updateMsg(assistantId, { content: assistantText || 'Launching the optimizer now…' });
            startStatusStream(data.job_id, data.sse_token);

          } else if (event === 'saved_profile' && data.label) {
            addMsg('assistant', `✅ Profile "${data.label}" saved to your profiles.`);
            fetchSessions();

          } else if (event === 'profile_docx' && data.download_url) {
            // Plain profile export — attach a download button to a chat message.
            const label = data.label || 'resume';
            const id = addMsg('assistant', `Here's your ${label} resume as a Word document:`);
            updateMsg(id, { download: { href: buildDownloadUrl(data.download_url), label: `Download ${label}.docx` } });

          } else if (event === 'resume_edited') {
            // Resume was edited in-session; the AI's text message already summarises the change.
            // Re-fetch sessions so the rail title stays fresh.
            fetchSessions();

          } else if (event === 'error') {
            updateMsg(assistantId, { content: `❌ ${data.message || 'Something went wrong.'}`, isError: true });
          }
        }
      }
    } catch {
      // Aborted (the user switched sessions / unmounted) — leave the newly loaded
      // session's state untouched.
      if (ac.signal.aborted) return;
      updateMsg(assistantId, { content: '❌ Network error — please try again.', isError: true });
    }

    if (ac.signal.aborted) return;
    setStreamingMsgId(null);
    // Functional updater reads the latest phase — if a handoff set it to 'running',
    // don't clobber it back to 'idle' (stale-closure trap).
    setPhase((p) => (p === 'running' || p === 'done' || p === 'error' ? p : 'idle'));
  }

  // ── Send from textarea ────────────────────────────────────────────────────────
  function sendToAgent() {
    const text = input.trim();
    if (text) sendMessage(text);
  }

  // ── Profile picker selection ──────────────────────────────────────────────────
  function handleProfileSelect(profile) {
    sendMessage(`Use my "${profile.label}" profile`);
  }

  // ── Welcome starter prompt — populate input and focus (let user edit/send) ─────
  function handleStarterPick(text) {
    setInput(text);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) { el.focus(); autoResize(el); }
    });
  }

  const isWaiting    = phase === 'chatting' || phase === 'running';
  const sendDisabled = !input.trim() || isWaiting;

  // Show profile picker when JD is captured, profiles available, and optimizer not yet launched.
  const showProfilePicker = profileSuggestions.length > 0 && !optimizerLaunched && phase === 'idle';

  const placeholder = phase === 'running'
    ? 'Pipeline running…'
    : phase === 'chatting'
    ? 'AI is thinking…'
    : 'Paste a job URL or description, or chat with the co-pilot…';

  return (
    <AppShell scroll={false}>
      <div className="flex flex-1 min-h-0">
        {railOpen && (
          <SessionRail
            activeSessionId={sessionId}
            onSelect={(sess) => loadSession(sess.id)}
            onNewChat={newChat}
          />
        )}

        <div className="flex flex-col flex-1 min-h-0 min-w-0">
          <header className="border-b border-line px-4 py-3 shrink-0 bg-surface flex items-center gap-3">
            <button
              onClick={() => setRailOpen((v) => !v)}
              className="p-1.5 rounded-lg text-ink-faint hover:text-ink hover:bg-surface-2 transition-colors"
              title={railOpen ? 'Hide history' : 'Show history'}
              aria-label="Toggle session history"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div>
              <h1 className="text-sm font-semibold text-ink tracking-tight leading-none">Optimize</h1>
              <p className="text-[11px] text-ink-faint mt-0.5">
                Chat with the AI co-pilot · paste a job URL or description · download your resume
              </p>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-8">
            {messages.length === 0 && phase === 'idle' && (
              <WelcomeHero onPick={handleStarterPick} />
            )}

            {messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                role={msg.role}
                content={msg.content}
                isError={msg.isError}
                action={msg.action}
                download={msg.download}
                loading={msg.id === streamingMsgId}
              />
            ))}

            {/* Profile picker — appears after JD capture, before optimizer launch */}
            {showProfilePicker && (
              <ProfilePicker
                profiles={profileSuggestions}
                onSelect={handleProfileSelect}
                disabled={isWaiting}
              />
            )}

            {phase === 'running' && (
              <PipelineProgress
                stage={stage}
                iteration={iteration}
                score={liveScores?.score}
                message={stageMessage}
                running={true}
              />
            )}

            {result && phase !== 'running' && (
              <ScoreReveal
                finalScore={result.finalScore}
                scores={liveScores?.scores}
                iterations={result.iterations}
                downloadUrl={downloadUrl}
                report={result.report}
              />
            )}

            <div ref={bottomRef} />
          </div>

          <div className="border-t border-line px-4 py-3 shrink-0 bg-surface">
            <div className="flex items-end gap-2 bg-card border border-line rounded-card px-4 py-2 shadow-card focus-within:border-primary/50 transition-all">
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                disabled={isWaiting}
                onChange={(e) => { setInput(e.target.value); autoResize(e.target); }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendToAgent(); } }}
                placeholder={placeholder}
                className="flex-1 resize-none text-sm text-ink bg-transparent focus:outline-none max-h-32 leading-relaxed placeholder:text-ink-faint py-1 disabled:opacity-60"
              />
              <button
                onClick={sendToAgent}
                disabled={sendDisabled}
                aria-label="Send message"
                className={clsx(
                  'shrink-0 mb-0.5 w-8 h-8 rounded-lg flex items-center justify-center transition-all',
                  sendDisabled
                    ? 'text-ink-faint/50 cursor-not-allowed'
                    : 'bg-primary text-white dark:text-surface hover:bg-primary-dark shadow-primary active:scale-95'
                )}
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
