import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, X } from 'lucide-react';
import useProfileStore from '../store/profileStore';

export default function OnboardingBanner() {
  const profiles = useProfileStore((s) => s.profiles);
  const loading = useProfileStore((s) => s.loading);
  const [dismissed, setDismissed] = useState(false);

  if (loading || profiles.length > 0 || dismissed) {
    return null;
  }

  return (
    <div className="relative bg-primary/5 border border-primary/20 rounded-xl p-5">
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="absolute top-3 right-3 p-1 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
        aria-label="Dismiss banner"
      >
        <X className="h-4 w-4" />
      </button>

      <div className="flex items-start gap-4 pr-6">
        <div className="shrink-0 flex items-center justify-center h-10 w-10 rounded-xl bg-primary/10">
          <Sparkles className="h-5 w-5 text-primary" />
        </div>

        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-900">
            Set up your profile to get started
          </h3>
          <p className="mt-1 text-sm text-gray-500">
            Create a profile from your resume so we can tailor every optimization to your background.
          </p>
          <Link
            to="/profiles/new"
            className="mt-3 inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white shadow-sm hover:opacity-90 transition-opacity active:scale-95"
          >
            Create Profile
          </Link>
        </div>
      </div>
    </div>
  );
}
