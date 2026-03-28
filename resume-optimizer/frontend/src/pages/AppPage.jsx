import { useState, useRef, useCallback } from 'react';
import { Upload, FileText, X, Loader2, Download, ChevronRight } from 'lucide-react';
import toast from 'react-hot-toast';
import TopNav from '../components/layout/TopNav';
import Button from '../components/ui/Button';
import ScoreCard from '../components/ui/ScoreCard';
import PipelineStep from '../components/ui/PipelineStep';
import CircularProgress from '../components/ui/CircularProgress';
import client from '../api/client';
import useAuthStore from '../store/authStore';
import usePipelineStore from '../store/pipelineStore';

const STAGES = [
  { key: 'upload',       label: 'Resume uploaded' },
  { key: 'jd_analysis',  label: 'JD analyzed' },
  { key: 'rewrite',      label: 'Rewriting resume' },
  { key: 'humanize',     label: 'Humanizing language' },
  { key: 'score',        label: 'Scoring (4 agents)' },
  { key: 'generate',     label: 'Generating .docx' },
];

export default function AppPage() {
  const { user } = useAuthStore();
  const { status, stages, logs, scores, iteration, downloadUrl, setStatus, setStage, addLog, setScores, setDownload, setIteration, reset, setJobId, jobId } = usePipelineStore();

  const [file, setFile]       = useState(null);
  const [jobIdLocal, setJobIdLocal] = useState(null);
  const [jdText, setJdText]   = useState('');
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [keywords, setKeywords] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);
  const logRef = useRef(null);
  const esRef = useRef(null);

  const handleDrop = useCallback(async (e) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer?.files?.[0] || e.target.files?.[0];
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['pdf','docx'].includes(ext)) { toast.error('Only .pdf and .docx files supported'); return; }
    setFile(f);
    setUploading(true);
    try {
      const fd = new FormData(); fd.append('file', f);
      const { data } = await client.post('/upload', fd);
      setJobIdLocal(data.job_id);
      setJobId(data.job_id);
      setStage('upload', 'done');
      toast.success('Resume uploaded');
    } catch { toast.error('Upload failed'); setFile(null); }
    finally { setUploading(false); }
  }, []);

  const analyzeJD = async () => {
    if (!jdText.trim()) return;
    setAnalyzing(true);
    try {
      const { data } = await client.post('/analyze-jd', { jd_text: jdText });
      setKeywords(data.keywords?.slice(0, 20) || []);
    } catch { toast.error('JD analysis failed'); }
    finally { setAnalyzing(false); }
  };

  const handleSSE = (e) => {
    try {
      const ev = JSON.parse(e.data);
      addLog(ev);
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;

      if (ev.stage) setStage(ev.stage, ev.type === 'stage' && stages[ev.stage] !== 'done' ? 'running' : stages[ev.stage]);
      if (ev.type === 'stage' && ev.stage) {
        const prev = STAGES.findIndex(s => s.key === ev.stage);
        if (prev > 0) setStage(STAGES[prev - 1].key, 'done');
      }
      if (ev.type === 'iterate') setIteration(ev.iteration);
      if (ev.type === 'average') setScores(ev);
      if (ev.type === 'done') {
        setStatus('done');
        setDownload(ev.download_url);
        STAGES.forEach(s => setStage(s.key, 'done'));
      }
      if (ev.type === 'error') { setStatus('error'); toast.error(ev.message); }
    } catch {}
  };

  const runPipeline = async () => {
    if (!jobIdLocal || !jdText.trim()) return;
    reset();
    setJobIdLocal(jobIdLocal);
    setStatus('running');
    setStage('upload', 'done');

    try {
      await client.post('/run-pipeline', { job_id: jobIdLocal, jd_text: jdText, user_id: user?.id || '' });
      const es = new EventSource(`${client.defaults.baseURL}/status/${jobIdLocal}`);
      esRef.current = es;
      es.onmessage = handleSSE;
      es.onerror = () => { es.close(); if (status !== 'done') setStatus('error'); };
    } catch (err) {
      setStatus('error');
      toast.error(err.response?.data?.detail?.upgrade_message || 'Pipeline failed');
    }
  };

  const avg = scores?.score || 0;

  return (
    <div className="min-h-screen bg-surface">
      <TopNav />
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Optimize Resume</h1>
          <p className="text-gray-500 mt-1">Upload your resume and paste a job description to get started</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left — inputs */}
          <div className="space-y-5">
            {/* Upload */}
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              className={`rounded-2xl border-2 border-dashed p-8 text-center cursor-pointer transition-all ${dragging ? 'border-primary bg-purple-50' : file ? 'border-green-400 bg-green-50' : 'border-gray-200 hover:border-primary/50'}`}
            >
              {uploading ? (
                <div className="flex flex-col items-center gap-3 text-gray-500">
                  <Loader2 className="w-8 h-8 animate-spin text-primary" />
                  <span className="text-sm">Uploading & parsing…</span>
                </div>
              ) : file ? (
                <div className="flex flex-col items-center gap-3">
                  <FileText className="w-8 h-8 text-green-500" />
                  <span className="text-sm font-medium text-gray-700">{file.name}</span>
                  <button onClick={() => { setFile(null); setJobIdLocal(null); }} className="text-xs text-red-400 hover:text-red-600 flex items-center gap-1"><X className="w-3 h-3" />Remove</button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <Upload className="w-8 h-8 text-gray-300" />
                  <div>
                    <p className="text-sm font-medium text-gray-700">Drop your resume here</p>
                    <p className="text-xs text-gray-400 mt-1">or click to browse · PDF, DOCX</p>
                  </div>
                  <input type="file" accept=".pdf,.docx" className="hidden" onChange={handleDrop} id="file-in" />
                  <label htmlFor="file-in" className="text-xs text-primary cursor-pointer underline">Browse file</label>
                </div>
              )}
            </div>

            {/* JD Input */}
            <div className="bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <label className="text-sm font-medium text-gray-700">Job Description</label>
                <span className="text-xs text-gray-400">{jdText.length} chars</span>
              </div>
              <textarea value={jdText} onChange={e => setJdText(e.target.value)}
                className="w-full h-40 text-sm resize-none border-0 focus:outline-none text-gray-700 placeholder-gray-300"
                placeholder="Paste the full job description here…" />
              <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-100">
                <div className="flex flex-wrap gap-1.5">
                  {keywords.map(k => <span key={k} className="text-xs bg-purple-50 text-primary px-2 py-0.5 rounded-full">{k}</span>)}
                </div>
                <Button variant="ghost" size="sm" onClick={analyzeJD} disabled={analyzing || jdText.length < 50}>
                  {analyzing ? <Loader2 className="w-3 h-3 animate-spin" /> : <ChevronRight className="w-3 h-3" />}
                  Extract keywords
                </Button>
              </div>
            </div>

            {/* Run button */}
            <Button size="lg" className="w-full justify-center"
              disabled={!file || !jdText.trim() || status === 'running'}
              onClick={runPipeline}>
              {status === 'running' ? <><Loader2 className="w-4 h-4 animate-spin" />Optimizing…</> : 'Optimize Resume'}
            </Button>
            {user && <p className="text-xs text-center text-gray-400">Signed in as {user.email} · {user.plan} plan</p>}
          </div>

          {/* Right — progress + results */}
          <div className="space-y-5">
            {/* Pipeline steps */}
            {status !== 'idle' && (
              <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm">
                <div className="flex items-center justify-between mb-5">
                  <h3 className="font-semibold text-gray-800">Pipeline Progress</h3>
                  {iteration > 0 && <span className="text-xs bg-purple-50 text-primary px-2.5 py-1 rounded-full">Iteration {iteration} / {4}</span>}
                </div>
                <div className="space-y-4">
                  {STAGES.map(s => (
                    <PipelineStep key={s.key} label={s.label}
                      status={stages[s.key] || 'pending'}
                      sublabel={s.key === 'jd_analysis' && keywords.length ? `${keywords.length} keywords` : undefined} />
                  ))}
                </div>
              </div>
            )}

            {/* Scores */}
            {scores && (
              <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-sm">
                <div className="flex items-center justify-between mb-5">
                  <h3 className="font-semibold text-gray-800">Scores</h3>
                  <div className="flex items-center gap-3">
                    <CircularProgress score={avg} size={64} strokeWidth={6} />
                    <div>
                      <div className="text-xs text-gray-500">Average</div>
                      <div className="font-bold text-lg text-gray-800">{avg} / 100</div>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <ScoreCard label="ATS Match"   score={scores.scores?.ats || 0} />
                  <ScoreCard label="Impact"      score={scores.scores?.impact || 0} />
                  <ScoreCard label="Skills Gap"  score={scores.scores?.skills_gap || 0} />
                  <ScoreCard label="Readability" score={scores.scores?.readability || 0} />
                </div>
                {downloadUrl && (
                  <a href={`${client.defaults.baseURL}${downloadUrl}`} download
                    className="mt-5 flex items-center justify-center gap-2 w-full bg-primary hover:bg-primary-dark text-white py-3 rounded-xl font-medium transition-colors">
                    <Download className="w-4 h-4" /> Download Optimized Resume
                  </a>
                )}
              </div>
            )}

            {/* Live log */}
            {logs.length > 0 && (
              <div className="bg-gray-900 rounded-2xl p-4 shadow-sm">
                <div className="text-xs text-gray-400 mb-2 font-mono">Live log</div>
                <div ref={logRef} className="h-48 overflow-y-auto space-y-1 font-mono text-xs">
                  {logs.map((l, i) => (
                    <div key={i} className={`${l.type === 'error' ? 'text-red-400' : l.type === 'done' ? 'text-green-400' : l.type === 'score' ? 'text-teal-400' : 'text-gray-300'}`}>
                      → {l.message || JSON.stringify(l).slice(0, 120)}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
