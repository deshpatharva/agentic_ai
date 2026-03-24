import React, { useState, useRef, useCallback } from 'react';
import UploadZone from './components/UploadZone.jsx';
import JDInput from './components/JDInput.jsx';
import PipelineProgress from './components/PipelineProgress.jsx';
import AgentLog from './components/AgentLog.jsx';
import ScoreDashboard from './components/ScoreDashboard.jsx';

const API_BASE = 'http://localhost:8000';

// Stage mapping from SSE event stage values to pipeline stage IDs
const STAGE_MAP = {
  jd_analysis: 'jd_analysis',
  rewrite: 'rewrite',
  humanize: 'humanize',
  score: 'score',
  consolidate: 'consolidate',
  finalize: 'generate',
  generate: 'generate',
};

const styles = {
  app: {
    minHeight: '100vh',
    background: '#0f172a',
    color: '#e2e8f0',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  header: {
    padding: '16px 32px',
    borderBottom: '1px solid #1e293b',
    background: '#0b1120',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerTitle: {
    fontSize: '1.1rem',
    fontWeight: '800',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6, #ec4899)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
    letterSpacing: '-0.02em',
  },
  headerSubtitle: {
    fontSize: '0.75rem',
    color: '#475569',
    marginTop: '2px',
  },
  statusBadge: {
    padding: '4px 12px',
    borderRadius: '20px',
    fontSize: '0.75rem',
    fontWeight: '600',
  },
  layout: {
    display: 'grid',
    gridTemplateColumns: '380px 1fr',
    gap: '0',
    height: 'calc(100vh - 57px)',
    overflow: 'hidden',
  },
  leftPanel: {
    borderRight: '1px solid #1e293b',
    padding: '20px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
    background: '#0b1120',
  },
  rightPanel: {
    padding: '20px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  sectionTitle: {
    fontSize: '0.75rem',
    fontWeight: '700',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    paddingBottom: '6px',
    borderBottom: '1px solid #1e293b',
  },
  startBtn: {
    width: '100%',
    padding: '12px',
    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
    color: '#fff',
    border: 'none',
    borderRadius: '10px',
    fontSize: '0.9rem',
    fontWeight: '700',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
    letterSpacing: '0.02em',
    transition: 'opacity 0.2s, transform 0.1s',
    boxShadow: '0 4px 15px rgba(99,102,241,0.35)',
  },
  startBtnDisabled: {
    opacity: 0.45,
    cursor: 'not-allowed',
    boxShadow: 'none',
  },
  errorBanner: {
    padding: '10px 14px',
    background: '#1f0f0f',
    border: '1px solid #dc2626',
    borderRadius: '8px',
    color: '#f87171',
    fontSize: '0.82rem',
  },
  rightGrid: {
    display: 'grid',
    gridTemplateColumns: '220px 1fr',
    gap: '20px',
    alignItems: 'start',
  },
  spinner: {
    display: 'inline-block',
    width: '14px',
    height: '14px',
    border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff',
    borderRadius: '50%',
    animation: 'spin 0.6s linear infinite',
  },
};

const STATUS_BADGE_STYLES = {
  idle:     { background: '#1e293b', color: '#64748b' },
  uploading:{ background: '#1e3a5f', color: '#93c5fd' },
  running:  { background: '#1e3a2f', color: '#4ade80' },
  done:     { background: '#16350a', color: '#86efac' },
  error:    { background: '#1f0f0f', color: '#f87171' },
};

export default function App() {
  // ── State ──────────────────────────────────────────────────────────────
  const [uploadedFile, setUploadedFile]       = useState(null);
  const [resumeText, setResumeText]           = useState('');
  const [jdText, setJdText]                   = useState('');
  const [jobId, setJobId]                     = useState(null);
  const [pipelineStatus, setPipelineStatus]   = useState('idle'); // idle|uploading|running|done|error
  const [logs, setLogs]                       = useState([]);
  const [scores, setScores]                   = useState({});
  const [iteration, setIteration]             = useState(0);
  const [downloadUrl, setDownloadUrl]         = useState(null);
  const [keywords, setKeywords]               = useState([]);
  const [analyzing, setAnalyzing]             = useState(false);
  const [error, setError]                     = useState(null);
  const [currentStage, setCurrentStage]       = useState(null);
  const [completedStages, setCompletedStages] = useState([]);
  const [uploading, setUploading]             = useState(false);

  const eventSourceRef = useRef(null);
  const currentJobIdRef = useRef(null);

  // ── Upload handler ─────────────────────────────────────────────────────
  const handleFileSelect = useCallback(async (file) => {
    if (!file) {
      setUploadedFile(null);
      setResumeText('');
      setJobId(null);
      return;
    }

    setUploadedFile(file);
    setUploading(true);
    setError(null);
    setPipelineStatus('uploading');

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Upload failed');
      }

      const data = await res.json();
      setJobId(data.job_id);
      setResumeText(data.text);
      currentJobIdRef.current = data.job_id;
      setPipelineStatus('idle');
      setCompletedStages(['upload']);
      setCurrentStage(null);
    } catch (err) {
      setError(`Upload error: ${err.message}`);
      setPipelineStatus('error');
    } finally {
      setUploading(false);
    }
  }, []);

  // ── JD Analysis ────────────────────────────────────────────────────────
  const handleAnalyzeJD = useCallback(async () => {
    if (!jdText.trim()) return;
    setAnalyzing(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/analyze-jd`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jd_text: jdText }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'JD analysis failed');
      }

      const data = await res.json();
      setKeywords(data.keywords || []);
    } catch (err) {
      setError(`JD analysis error: ${err.message}`);
    } finally {
      setAnalyzing(false);
    }
  }, [jdText]);

  // ── SSE event handler ──────────────────────────────────────────────────
  const handleSSEEvent = useCallback((rawData) => {
    let event;
    try {
      event = JSON.parse(rawData);
    } catch {
      return;
    }

    const timestampedEvent = { ...event, timestamp: Date.now() };
    setLogs((prev) => [...prev, timestampedEvent]);

    switch (event.type) {
      case 'stage': {
        const stageId = STAGE_MAP[event.stage] || event.stage;
        if (stageId) {
          setCurrentStage(stageId);
          // Mark previous stage as completed when moving to a new one
          setCompletedStages((prev) => {
            if (stageId && !prev.includes(stageId)) {
              // Find index of current stage and complete everything before it
              const stageOrder = ['upload', 'jd_analysis', 'rewrite', 'humanize', 'score', 'consolidate', 'generate'];
              const stageIdx = stageOrder.indexOf(stageId);
              const toComplete = stageOrder.slice(0, stageIdx).filter((s) => !prev.includes(s));
              return [...prev, ...toComplete];
            }
            return prev;
          });
        }
        break;
      }

      case 'score': {
        const platformKey = {
          'ATS Match': 'ats',
          'Impact Score': 'impact',
          'Skills Gap': 'skills_gap',
          'Readability': 'readability',
        }[event.platform] || event.platform;

        setScores((prev) => ({
          ...prev,
          [platformKey]: {
            score: event.score,
            ...(event.feedback && { [getScoreFeedbackKey(platformKey)]: event.feedback }),
            ...(event.matched && { [getScoreMatchedKey(platformKey)]: event.matched }),
            ...(event.weak_bullets && { weak_bullets: event.weak_bullets }),
            ...(event.strengths && { strengths: event.strengths }),
          },
        }));
        break;
      }

      case 'average': {
        setIteration(event.iteration || 0);
        setScores((prev) => ({ ...prev, average: event.score }));
        break;
      }

      case 'iterate': {
        setIteration(event.iteration || 0);
        // Reset stage for new iteration
        setCurrentStage('rewrite');
        setCompletedStages((prev) => {
          // Keep upload and jd_analysis completed
          return prev.filter((s) => ['upload', 'jd_analysis'].includes(s));
        });
        break;
      }

      case 'done': {
        setDownloadUrl(event.download_url);
        setPipelineStatus('done');
        setCurrentStage(null);
        setCompletedStages(['upload', 'jd_analysis', 'rewrite', 'humanize', 'score', 'consolidate', 'generate']);
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
        break;
      }

      case 'error': {
        setPipelineStatus('error');
        setError(event.message);
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
        break;
      }

      default:
        break;
    }
  }, []);

  // ── Start pipeline ─────────────────────────────────────────────────────
  const handleStartPipeline = useCallback(async () => {
    if (!jobId || !jdText.trim()) return;

    setError(null);
    setPipelineStatus('running');
    setLogs([]);
    setScores({});
    setIteration(0);
    setDownloadUrl(null);
    setCurrentStage('jd_analysis');
    setCompletedStages(['upload']);

    // Close existing SSE connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    try {
      // Start pipeline
      const res = await fetch(`${API_BASE}/run-pipeline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, jd_text: jdText }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to start pipeline');
      }

      // Open SSE connection
      const es = new EventSource(`${API_BASE}/status/${jobId}`);
      eventSourceRef.current = es;

      es.onmessage = (e) => {
        handleSSEEvent(e.data);
      };

      es.onerror = (e) => {
        // SSE connection closed normally after done/sentinel
        if (pipelineStatus !== 'done') {
          es.close();
        }
      };
    } catch (err) {
      setError(`Pipeline error: ${err.message}`);
      setPipelineStatus('error');
    }
  }, [jobId, jdText, handleSSEEvent, pipelineStatus]);

  // ── Helpers ────────────────────────────────────────────────────────────
  const canStart = jobId && jdText.trim().length >= 50 && pipelineStatus !== 'running';

  const statusBadgeStyle = {
    ...styles.statusBadge,
    ...(STATUS_BADGE_STYLES[pipelineStatus] || STATUS_BADGE_STYLES.idle),
  };

  const statusLabels = {
    idle: 'Ready',
    uploading: 'Uploading...',
    running: 'Running Pipeline',
    done: 'Complete',
    error: 'Error',
  };

  return (
    <div style={styles.app}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: #0b1120; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
      `}</style>

      {/* Header */}
      <div style={styles.header}>
        <div>
          <div style={styles.headerTitle}>⚡ Resume Optimizer AI</div>
          <div style={styles.headerSubtitle}>Multi-agent optimization pipeline powered by Claude</div>
        </div>
        <div style={statusBadgeStyle}>
          {pipelineStatus === 'running' && <span style={{ ...styles.spinner, marginRight: '6px' }} />}
          {statusLabels[pipelineStatus] || 'Ready'}
        </div>
      </div>

      {/* Main Layout */}
      <div style={styles.layout}>
        {/* ── Left Panel ── */}
        <div style={styles.leftPanel}>
          {/* Upload */}
          <div style={styles.section}>
            <div style={styles.sectionTitle}>1. Upload Resume</div>
            <UploadZone
              onFileSelect={handleFileSelect}
              uploadedFile={uploadedFile}
            />
            {uploading && (
              <div style={{ fontSize: '0.78rem', color: '#93c5fd', textAlign: 'center' }}>
                <span style={styles.spinner} /> Parsing resume...
              </div>
            )}
            {resumeText && (
              <div style={{
                fontSize: '0.72rem',
                color: '#4ade80',
                padding: '6px 10px',
                background: '#0f2318',
                borderRadius: '6px',
                border: '1px solid #166534',
              }}>
                ✓ Parsed {resumeText.length.toLocaleString()} characters
              </div>
            )}
          </div>

          {/* JD Input */}
          <div style={styles.section}>
            <div style={styles.sectionTitle}>2. Job Description</div>
            <JDInput
              jdText={jdText}
              setJdText={setJdText}
              keywords={keywords}
              onAnalyze={handleAnalyzeJD}
              analyzing={analyzing}
            />
          </div>

          {/* Error */}
          {error && (
            <div style={styles.errorBanner}>
              ⚠️ {error}
            </div>
          )}

          {/* Start Button */}
          <button
            style={{
              ...styles.startBtn,
              ...(!canStart ? styles.startBtnDisabled : {}),
            }}
            onClick={handleStartPipeline}
            disabled={!canStart}
          >
            {pipelineStatus === 'running' ? (
              <>
                <span style={styles.spinner} />
                Optimizing Resume...
              </>
            ) : pipelineStatus === 'done' ? (
              <>🔁 Run Again</>
            ) : (
              <>🚀 Start Optimization Pipeline</>
            )}
          </button>

          {!jobId && (
            <div style={{ fontSize: '0.72rem', color: '#475569', textAlign: 'center' }}>
              Upload a resume to enable the pipeline
            </div>
          )}
          {jobId && jdText.trim().length < 50 && (
            <div style={{ fontSize: '0.72rem', color: '#475569', textAlign: 'center' }}>
              Add a job description (min 50 chars) to start
            </div>
          )}
        </div>

        {/* ── Right Panel ── */}
        <div style={styles.rightPanel}>
          <div style={styles.rightGrid}>
            {/* Pipeline Progress */}
            <div style={styles.section}>
              <PipelineProgress
                currentStage={currentStage}
                completedStages={completedStages}
                iteration={iteration}
                pipelineStatus={pipelineStatus}
              />
            </div>

            {/* Agent Log */}
            <div style={{ ...styles.section, flex: 1 }}>
              <AgentLog logs={logs} />
            </div>
          </div>

          {/* Score Dashboard */}
          <div style={styles.section}>
            <ScoreDashboard
              scores={scores}
              iteration={iteration}
              downloadUrl={downloadUrl}
              pipelineStatus={pipelineStatus}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Score key helpers ────────────────────────────────────────────────────────
function getScoreFeedbackKey(platform) {
  const map = {
    ats: 'missing_keywords',
    impact: 'suggestions',
    skills_gap: 'missing_skills',
    readability: 'issues',
  };
  return map[platform] || 'feedback';
}

function getScoreMatchedKey(platform) {
  const map = {
    ats: 'matched_keywords',
    skills_gap: 'matched_skills',
  };
  return map[platform] || 'matched';
}
