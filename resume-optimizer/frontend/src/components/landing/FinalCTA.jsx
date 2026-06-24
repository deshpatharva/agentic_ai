import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';

export default function FinalCTA() {
  return (
    <section className="border-y border-line bg-accent-soft/40">
      <div className="max-w-3xl mx-auto px-6 py-20 text-center">
        <h2 className="font-display text-3xl lg:text-4xl font-semibold text-ink mb-4">
          Send a sharper resume on your next application.
        </h2>
        <p className="text-ink-mute mb-8">Upload once, score on five dimensions, and download a verified draft.</p>
        <Link
          to="/register"
          className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg font-semibold text-lg text-white dark:text-surface bg-primary hover:bg-primary-dark shadow-primary transition-all active:scale-95 focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none"
        >
          Get started free <ArrowRight className="w-5 h-5" />
        </Link>
      </div>
    </section>
  );
}
