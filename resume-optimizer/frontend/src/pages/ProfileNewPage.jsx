import { useState, useRef, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, UploadCloud, FileText, Loader2, AlertCircle } from 'lucide-react';
import Button from '../components/ui/Button';
import ProfileEditor from '../components/ProfileEditor';
import InterviewChat from '../components/InterviewChat';
import TiltCard from '../components/TiltCard';
import useProfileStore from '../store/profileStore';
import useAuthStore from '../store/authStore';
import client from '../api/client';

const EMPTY_SECTIONS = { contact: {}, summary: '', experience: [], education: [], skills: [], additional_sections: [] };
const EMPTY_LABEL = '';

function UploadZone({ onFileSelect, file, dragActive, onDragOver, onDragLeave, onDrop }) {
  const inputRef = useRef(null);

  return (
    <TiltCard lifted={dragActive}>
    <div
      className={[
        'relative flex flex-col items-center justify-center gap-3 rounded-card border-2 border-dashed px-8 py-12 transition-colors cursor-pointer select-none',
        dragActive
          ? 'border-primary/60 bg-primary/5 shadow-lifted'
          : 'border-line hover:border-primary/40 hover:bg-surface-2',
      ].join(' ')}
      onClick={() => inputRef.current?.click()}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
      aria-label="Upload resume file"
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx"
        className="sr-only"
        onChange={(e) => onFileSelect(e.target.files?.[0] ?? null)}
      />
      {file ? (
        <>
          <FileText className="h-10 w-10 text-primary" />
          <span className="text-sm font-medium text-ink">{file.name}</span>
          <span className="text-xs text-ink-mute">Click to change file</span>
        </>
      ) : (
        <>
          <UploadCloud className="h-10 w-10 text-ink-faint" />
          <p className="text-sm font-medium text-ink">
            Drag &amp; drop your resume here
          </p>
          <p className="text-xs text-ink-mute">PDF or DOCX · click to browse</p>
        </>
      )}
    </div>
    </TiltCard>
  );
}

export default function ProfileNewPage() {
  const navigate = useNavigate();
  const { createProfile } = useProfileStore();
  const fetchMe = useAuthStore((s) => s.fetchMe);

  const [view, setView] = useState('upload');
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const [initialLabel, setInitialLabel] = useState(EMPTY_LABEL);
  const [initialSections, setInitialSections] = useState(EMPTY_SECTIONS);
  const [rawText, setRawText] = useState('');

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  }, []);

  const handleFileSelect = useCallback((selected) => {
    setFile(selected);
    setError(null);
  }, []);

  const handleParseResume = useCallback(async () => {
    if (!file) {
      setError('Please select a file to upload.');
      return;
    }

    setError(null);
    setParsing(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      // Backend extracts text from PDF/DOCX and returns parsed sections + raw_text
      const { data } = await client.post('/profile/parse', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      setRawText(data.raw_text ?? '');
      setInitialLabel(data.label ?? '');
      setInitialSections({
        contact: data.contact ?? {},
        summary: data.summary ?? '',
        experience: data.experience ?? [],
        education: data.education ?? [],
        skills: data.skills ?? [],
        additional_sections: data.additional_sections ?? [],
      });
      setView('editor');
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Failed to parse resume. Please try again.';
      setError(msg);
    } finally {
      setParsing(false);
    }
  }, [file]);

  const handleBuildFromScratch = useCallback(() => {
    setInitialLabel(EMPTY_LABEL);
    setInitialSections(EMPTY_SECTIONS);
    setRawText('');
    setError(null);
    setView('interview');
  }, []);

  const handleSave = useCallback(
    async ({ label, labelConfirmed, sections }) => {
      setError(null);
      setSaving(true);
      try {
        await createProfile({ label, label_confirmed: labelConfirmed, raw_text: rawText, sections });
        // Refresh auth state so user.profile_status flips to 'complete'; without
        // this the stale 'incomplete' status makes RequireProfile bounce the user
        // off /optimize back to /profiles/new.
        await fetchMe();
        navigate('/profiles');
      } catch (err) {
        const msg =
          err?.response?.data?.detail ||
          err?.message ||
          'Failed to save profile. Please try again.';
        setError(msg);
      } finally {
        setSaving(false);
      }
    },
    [createProfile, fetchMe, navigate, rawText]
  );

  return (
    <div className="min-h-screen bg-surface flex flex-col items-center py-10 px-4">
      <div className="w-full max-w-2xl">
        <Link
          to="/profiles"
          className="inline-flex items-center gap-1.5 text-sm text-ink-mute hover:text-ink transition-colors mb-6 group"
        >
          <ArrowLeft className="h-4 w-4 group-hover:-translate-x-0.5 transition-transform" />
          Back to Profiles
        </Link>

        <div className="bg-card border border-line shadow-card rounded-card p-8">
          {view === 'upload' && (
            <>
              <div className="mb-6">
                <h1 className="font-display text-2xl font-semibold text-ink">Create Profile</h1>
                <p className="mt-1 text-sm text-ink-mute">
                  Upload your resume to get started
                </p>
              </div>

              <UploadZone
                file={file}
                dragActive={dragActive}
                onFileSelect={handleFileSelect}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              />

              {error && (
                <div className="mt-4 flex items-start gap-2 rounded-lg bg-err-soft border border-err/30 px-4 py-3 text-sm text-err">
                  <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div className="mt-5 flex flex-col gap-3">
                <Button
                  variant="primary"
                  size="lg"
                  className="w-full justify-center"
                  onClick={handleParseResume}
                  disabled={!file || parsing}
                >
                  {parsing ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Parsing…
                    </>
                  ) : (
                    'Parse Resume'
                  )}
                </Button>

                <button
                  type="button"
                  onClick={handleBuildFromScratch}
                  className="text-sm text-ink-mute hover:text-primary transition-colors underline underline-offset-2 self-center"
                >
                  Build with AI Interview
                </button>
              </div>
            </>
          )}

          {view === 'interview' && (
            <>
              <div className="mb-6">
                <h1 className="font-display text-2xl font-semibold text-ink">Create Profile</h1>
                <p className="mt-1 text-sm text-ink-mute">
                  Answer a few questions and we'll build your profile
                </p>
              </div>

              <InterviewChat
                onComplete={(sections) => {
                  setInitialLabel(sections.label || '');
                  setInitialSections({
                    contact: sections.contact || {},
                    summary: sections.summary || '',
                    experience: sections.experience || [],
                    education: sections.education || [],
                    skills: sections.skills || [],
                    additional_sections: sections.additional_sections || [],
                  });
                  setView('editor');
                }}
              />
            </>
          )}

          {view === 'editor' && (
            <>
              <div className="mb-6">
                <h1 className="font-display text-2xl font-semibold text-ink">Create Profile</h1>
              </div>

              {error && (
                <div className="mb-4 flex items-start gap-2 rounded-lg bg-err-soft border border-err/30 px-4 py-3 text-sm text-err">
                  <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <ProfileEditor
                initialLabel={initialLabel}
                initialSections={initialSections}
                onSave={handleSave}
                saving={saving}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
