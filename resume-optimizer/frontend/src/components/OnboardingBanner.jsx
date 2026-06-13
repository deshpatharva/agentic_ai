import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, X } from 'lucide-react';
import useProfileStore from '../store/profileStore';

export default function OnboardingBanner() {
  const profiles = useProfileStore((s) => s.profiles);
  const loading = useProfileStore((s) => s.loading);
  const fetchProfiles = useProfileStore((s) => s.fetchProfiles);
  const [dismissed, setDismissed] = useState(false);
  const fetched = useRef(false);

  // The banner must know whether profiles exist — don't trust an unfetched store.
  useEffect(() => {
    if (fetched.current) return;
    fetched.current = true;
    if (profiles.length === 0) fetchProfiles();
  }, [profiles.length, fetchProfiles]);

  if (loading || profiles.length > 0 || dismissed) {
    return null;
  }

  return (
    <div className="relative bg-accent-soft/60 border border-primary/20 rounded-card p-5 mb-6">
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="absolute top-3 right-3 p-1 rounded-lg text-ink-faint hover:text-ink hover:bg-surface-2 transition-colors"
        aria-label="Dismiss banner"
      >
        <X className="h-4 w-4" />
      </button>

      <div className="flex items-start gap-4 pr-6">
        <div className="shrink-0 flex items-center justify-center h-10 w-10 rounded-lg bg-primary/10">
          <Sparkles className="h-5 w-5 text-primary" />
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-ink">
            Set up your profile to get started
          </h3>
          <p className="mt-1 text-sm text-ink-mute">
            Create a profile from your resume so we can tailor every optimization to your background.
          </p>
          <Link
            to="/profiles/new"
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white dark:text-ink shadow-sm hover:bg-primary-dark transition-colors active:scale-95"
          >
            Create Profile
          </Link>
        </div>
      </div>
    </div>
  );
}
