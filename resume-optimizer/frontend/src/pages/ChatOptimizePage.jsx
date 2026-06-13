import { useState, useRef, useEffect, useCallback } from 'react';
import { Send } from 'lucide-react';
import { clsx } from 'clsx';
import client from '../api/client';
import AppShell from '../components/layout/AppShell';
import ChatMessage from '../components/ChatMessage';
import PipelineProgress from '../components/PipelineProgress';
import ScoreReveal from '../components/ScoreReveal';

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
  const [phase, setPhase]               = useState('idle');    // idle | chatting | running | done | error
  const [sessionId, setSessionId]       = useState(null);
  const [stage, setStage]               = useState(null);
  const [stageMessage, setStageMessage] = useState('');
  const [iteration, setIteration]       = useState(0);
  const [liveScores, setLiveScores]     = useState(null);
  const [result, setResult]             = useState(null);
  const [downloadUrl, setDownloadUrl]   = useState(null);

  const esRef       = useRef(null);
  const bottomRef   = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => () => esRef.current?.close(), []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, stage, result]);

  const addMsg = useCallback((role, content, isError = false) => {
    const id = Date.now() + Math.random();
    setMessages(prev => [...prev, { role, content, isError, id }]);
    return id;
  }, []);

  const updateMsg = useCallback((id, patch) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, ...patch } : m));
  }, []);

  function startStatusStream(jobId, sseToken) {
    setPhase('running');
    setStage(null);
    setStageMessage('');
    setIteration(0);
    setLiveScores(null);
    setResult(null);
    setDownloadUrl(null);

    const es = new EventSource(
      `${client.defaults.baseURL}/status/${jobId}?token=${encodeURIComponent(sseToken)}`
    );
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.type === 'stage') { setStage(ev.stage); setStageMessage(ev.message || ''); }
        if (ev.type === 'average') { setIteration(ev.iteration || 0); setLiveScores(ev); }
        if (ev.type === 'done') {
          setPhase('done');
          setDownloadUrl(ev.download_url);
          setResult({ finalScore: ev.final_score ?? 0, iterations: ev.iterations ?? 0 });
          es.close();
        }
        if (ev.type === 'error') {
          setPhase('error');
          addMsg('assistant', `❌ ${ev.message || 'Pipeline failed.'}`, true);
          es.close();
        }
      } catch {}
    };
    es.onerror = () => {
      setPhase('error');
      addMsg('assistant', 'Connection to optimizer lost.', true);
      es.close();
    };
  }

  async function sendToAgent() {
    const text = input.trim();
    if (!text || phase === 'running' || phase === 'chatting') return;

    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    addMsg('user', text);
    setPhase('chatting');

    const assistantId = addMsg('assistant', '');

    try {
      const res = await fetch(`${client.defaults.baseURL}/optimize/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 403 && err?.detail?.error === 'profile_incomplete') {
          updateMsg(assistantId, { content: `❌ ${err.detail.message}`, isError: true, action: err.detail.action });
          setPhase('idle');
          return;
        }
        const msg = err?.detail?.upgrade_message || err?.detail?.message || err?.detail || 'Request failed.';
        updateMsg(assistantId, { content: `❌ ${msg}`, isError: true });
        setPhase('idle');
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let assistantText = '';

      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const { event, data } = parseSSEFrame(frame);

          if (event === 'session' && data.session_id) {
            setSessionId(data.session_id);
          } else if (event === 'token' && data.text) {
            assistantText += data.text;
            updateMsg(assistantId, { content: assistantText });
          } else if (event === 'handoff') {
            // Pipeline is firing — switch to progress mode.
            updateMsg(assistantId, { content: assistantText || 'Launching the optimizer now…' });
            startStatusStream(data.job_id, data.sse_token);
          } else if (event === 'error') {
            updateMsg(assistantId, { content: `❌ ${data.message || 'Something went wrong.'}`, isError: true });
          }
          // 'done' just signals the stream end; no UI action needed.
        }
      }
    } catch (err) {
      updateMsg(assistantId, { content: '❌ Network error — please try again.', isError: true });
    }

    if (phase !== 'running') setPhase('idle');
  }

  const isWaiting = phase === 'chatting' || phase === 'running';
  const sendDisabled = !input.trim() || isWaiting;

  const placeholder = phase === 'running'
    ? 'Pipeline running…'
    : phase === 'chatting'
    ? 'Waiting for response…'
    : 'Paste a job URL or description, or chat with the co-pilot…';

  return (
    <AppShell scroll={false}>
      <div className="flex flex-col flex-1 min-h-0">
        <header className="border-b border-line px-6 py-4 shrink-0 bg-surface">
          <h1 className="text-base font-semibold text-ink tracking-tight">Optimize</h1>
          <p className="text-xs text-ink-faint mt-0.5">
            Chat with the AI co-pilot · paste a job URL or description · download your resume
          </p>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-8">
          <ChatMessage
            role="assistant"
            content="Hi! Paste a job URL or job description and I'll help tailor your resume profile to it."
          />

          {messages.map((msg) => (
            <ChatMessage key={msg.id} role={msg.role} content={msg.content} isError={msg.isError} action={msg.action} />
          ))}

          {phase === 'running' && (
            <PipelineProgress
              stage={stage}
              iteration={iteration}
              score={liveScores?.score}
              message={stageMessage}
            />
          )}

          {phase === 'done' && result && (
            <ScoreReveal
              finalScore={result.finalScore}
              scores={liveScores?.scores}
              iterations={result.iterations}
              downloadUrl={downloadUrl}
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
                  : 'bg-primary text-white dark:text-ink hover:bg-primary-dark shadow-primary active:scale-95'
              )}
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
