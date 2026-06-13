import { useState, useRef, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Send } from 'lucide-react';
import { clsx } from 'clsx';
import client from '../api/client';
import useProfileStore from '../store/profileStore';
import AppShell from '../components/layout/AppShell';
import ChatMessage from '../components/ChatMessage';
import ProfileMatchCard from '../components/ProfileMatchCard';
import PipelineProgress from '../components/PipelineProgress';
import ScoreReveal from '../components/ScoreReveal';

function autoResize(el) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

export default function ChatOptimizePage() {
  const { profiles, fetchProfiles } = useProfileStore();

  const [messages, setMessages]               = useState([]);
  const [input, setInput]                     = useState('');
  const [phase, setPhase]                     = useState('idle');
  const [matchedProfiles, setMatchedProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [jdText, setJdText]                   = useState('');
  const [downloadUrl, setDownloadUrl]         = useState(null);
  const [stage, setStage]                     = useState(null);
  const [stageMessage, setStageMessage]       = useState('');
  const [iteration, setIteration]             = useState(0);
  const [liveScores, setLiveScores]           = useState(null);
  const [result, setResult]                   = useState(null);

  const esRef       = useRef(null);
  const bottomRef   = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    fetchProfiles();
    return () => esRef.current?.close();
  }, [fetchProfiles]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, matchedProfiles, stage, result]);

  const addMsg = useCallback((role, content, isError = false) => {
    setMessages((prev) => [...prev, { role, content, isError, id: Date.now() + Math.random() }]);
  }, []);

  const greeting =
    profiles.length === 0
      ? <>You don't have any profiles yet. <Link to="/profiles/new" className="text-primary font-medium underline underline-offset-2">Create one first</Link>, then come back here.</>
      : "Paste a job URL or job description below to get started. I'll match it to your profiles and run the optimizer.";

  let placeholder = 'Paste a job URL or job description…';
  if (phase === 'running')         placeholder = 'Pipeline running…';
  else if (jdText && !selectedProfile) placeholder = 'Click a profile card above, or type 1/2/3…';
  else if (selectedProfile)        placeholder = 'Add instructions or say "go" to start…';

  async function startPipeline(instruction = '') {
    setPhase('running');
    setStage(null);
    setStageMessage('');
    setIteration(0);
    setLiveScores(null);
    setResult(null);
    setDownloadUrl(null);
    addMsg('assistant', `Starting optimization with your "${selectedProfile.label}" profile…`);

    try {
      const { data: genData } = await client.post('/profile/prepare-job', {
        profile_id: selectedProfile.id,
      });
      const newJobId = genData.job_id;

      const { data: sseData } = await client.post('/user/sse-token');
      const es = new EventSource(
        `${client.defaults.baseURL}/status/${newJobId}?token=${encodeURIComponent(sseData.sse_token)}`
      );
      esRef.current = es;

      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          // agent_step telemetry is intentionally ignored here (admin surface material)
          if (ev.type === 'stage') {
            setStage(ev.stage);
            setStageMessage(ev.message || '');
          }
          if (ev.type === 'average') {
            setIteration(ev.iteration || 0);
            setLiveScores(ev);
          }
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

      await client.post('/run-pipeline', {
        job_id:     newJobId,
        jd_text:    jdText,
        profile_id: selectedProfile.id,
        instruction,
      });
    } catch (err) {
      esRef.current?.close();
      setPhase('error');
      const detail = err?.response?.data?.detail;
      const msg = err?.response?.status === 429
        ? (detail?.upgrade_message || 'Daily limit reached — upgrade your plan to run more optimizations.')
        : 'Failed to start pipeline. Please try again.';
      addMsg('assistant', msg, true);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || phase === 'running') return;

    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    if (!jdText) {
      addMsg('user', text);
      const isUrl = /^https?:\/\//i.test(text);
      let resolvedJd = '';

      if (isUrl) {
        setPhase('scraping');
        addMsg('assistant', 'Fetching job description from that URL…');
        try {
          const { data } = await client.post('/jd/scrape', { url: text });
          resolvedJd = data.jd_text || '';
          if (!resolvedJd) throw new Error('Empty response');
          setJdText(resolvedJd);
          addMsg('assistant', 'Got it. Running profile matching…');
        } catch {
          setPhase('idle');
          addMsg('assistant', "Couldn't fetch that URL — please paste the job description directly.", true);
          return;
        }
      } else {
        resolvedJd = text;
        setJdText(resolvedJd);
        addMsg('assistant', 'Got it. Running profile matching…');
      }

      setPhase('matching');
      try {
        const { data: matches } = await client.post('/profile/match', { jd_text: resolvedJd });
        const list = Array.isArray(matches) ? matches : [];
        if (!list.length) {
          setPhase('idle');
          addMsg('assistant', 'No profiles found. Create one at /profiles/new first.', true);
          return;
        }
        setMatchedProfiles(list);
        setPhase('idle');
        addMsg('assistant', `Found ${list.length} profile match${list.length > 1 ? 'es' : ''}. Click one to select…`);
      } catch {
        setPhase('idle');
        addMsg('assistant', 'Profile matching failed. Please try again.', true);
      }
      return;
    }

    if (!selectedProfile) {
      addMsg('user', text);
      const idx = parseInt(text, 10) - 1;
      if (!isNaN(idx) && matchedProfiles[idx]) {
        const prof = matchedProfiles[idx];
        setSelectedProfile(prof);
        addMsg('assistant', `Selected "${prof.label}". Any special instructions? (or say "go" to start)`);
      } else {
        addMsg('assistant', "Please click a profile card above, or type its number (e.g. '1').");
      }
      return;
    }

    addMsg('user', text);
    await startPipeline(text.toLowerCase() === 'go' ? '' : text);
  }

  function handleProfileSelect(profile) {
    setSelectedProfile(profile);
    addMsg('user', `Use "${profile.label}"`);
    addMsg('assistant', `Selected "${profile.label}". Any special instructions? (or say "go" to start)`);
  }

  const sendDisabled = !input.trim() || phase === 'running';
  const showProfiles = matchedProfiles.length > 0 && phase !== 'running' && phase !== 'done';

  return (
    <AppShell scroll={false}>
      <div className="flex flex-col flex-1 min-h-0">
        <header className="border-b border-line px-6 py-4 shrink-0 bg-surface">
          <h1 className="text-base font-semibold text-ink tracking-tight">Optimize</h1>
          <p className="text-xs text-ink-faint mt-0.5">Paste a job URL or description · select a profile · download your resume</p>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-8">
          <ChatMessage role="assistant" content={greeting} />

          {messages.map((msg) => (
            <ChatMessage key={msg.id} role={msg.role} content={msg.content} isError={msg.isError} />
          ))}

          {showProfiles && (
            <div className="mt-3 mb-2 flex flex-col gap-2 max-w-md">
              {matchedProfiles.map((p) => (
                <ProfileMatchCard
                  key={p.id}
                  profile={p}
                  selected={selectedProfile?.id === p.id}
                  onSelect={handleProfileSelect}
                />
              ))}
            </div>
          )}

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
              disabled={phase === 'running'}
              onChange={(e) => { setInput(e.target.value); autoResize(e.target); }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              placeholder={placeholder}
              className="flex-1 resize-none text-sm text-ink bg-transparent focus:outline-none max-h-32 leading-relaxed placeholder:text-ink-faint py-1 disabled:opacity-60"
            />
            <button
              onClick={handleSend}
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
