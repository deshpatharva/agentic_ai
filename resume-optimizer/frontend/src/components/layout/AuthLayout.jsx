import { Feather, ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function AuthLayout({ children, title, subtitle }) {
  return (
    <div className="min-h-screen flex">
      {/* Brand panel — fixed deep-green "cover board", identical in both themes */}
      <div
        className="hidden lg:flex w-1/2 flex-col justify-center px-16 text-[#F2EFE6] relative overflow-hidden"
        style={{ background: 'linear-gradient(165deg, #11523E 0%, #1A6B52 70%, #1F7A5E 100%)' }}
      >
        {/* Dot-grid texture overlay */}
        <div
          className="absolute inset-0 opacity-10 pointer-events-none"
          style={{
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.8) 1px, transparent 1px)',
            backgroundSize: '20px 20px',
          }}
        />
        <div className="relative z-10">
          <Link to="/" className="flex items-center gap-3 mb-8 hover:opacity-80 transition-opacity">
            <Feather className="w-8 h-8" />
            <span className="font-display text-2xl font-semibold tracking-tight">ResumeAI</span>
          </Link>
          <h2 className="font-display text-4xl font-semibold leading-tight mb-4">Your resume, set in type that gets you read.</h2>
          <p className="text-[#CFE8DD] text-lg">Upload once. Score on 4 dimensions. Iterate until perfect. Get hired faster.</p>
          <div className="mt-12 grid grid-cols-2 gap-4">
            {[['4 AI Scorers','ATS, Impact, Skills, Readability'],['Smart Rewriter','Aligned to your exact JD'],['Job Matching','Nightly scrape of matched roles'],['Real-time Progress','Live pipeline status']].map(([t,d]) => (
              <div key={t} className="bg-white/10 backdrop-blur-sm rounded-xl p-4 hover:bg-white/15 transition-colors">
                <div className="font-semibold mb-1">{t}</div>
                <div className="text-[#CFE8DD] text-sm">{d}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="flex-1 flex flex-col justify-center px-8 lg:px-16 bg-card">
        <div className="max-w-md w-full mx-auto">
          <div className="flex items-center justify-between mb-8 lg:hidden">
            <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
              <Feather className="w-6 h-6 text-primary" />
              <span className="font-display text-xl font-semibold text-ink">ResumeAI</span>
            </Link>
            <Link to="/" className="flex items-center gap-1 text-sm text-ink-mute hover:text-ink transition-colors">
              <ArrowLeft className="w-4 h-4" />
              Back to home
            </Link>
          </div>
          <Link to="/" className="hidden lg:flex items-center gap-1 text-sm text-ink-mute hover:text-ink transition-colors mb-6">
            <ArrowLeft className="w-4 h-4" />
            Back to home
          </Link>
          <h1 className="font-display text-2xl font-semibold text-ink mb-2">{title}</h1>
          <p className="text-ink-mute mb-8">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
