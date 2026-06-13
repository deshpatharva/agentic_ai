import { Link } from 'react-router-dom';
import { Zap, Target, Briefcase, ArrowRight, Check } from 'lucide-react';
import TopNav from '../components/layout/TopNav';
import HeroVisual from '../components/HeroVisual';

const features = [
  { icon: Zap,      title: 'AI Rewriter',    desc: 'AI rewrites your resume to align with every JD keyword.' },
  { icon: Target,   title: 'Smart Scoring',  desc: '4 scorers: ATS match, impact, skills gap, and readability — all in one call.' },
  { icon: Briefcase,title: 'Job Matching',   desc: 'Nightly scrape of matched roles from Adzuna, RemoteOK, and The Muse.' },
];

const plans = [
  { name: 'Free',       price: '$0',  period: '/mo', features: ['2 uploads / day','1 resume stored','4 AI scorers','PDF + DOCX export'],    highlight: false, plan: 'free' },
  { name: 'Pro',        price: '$9',  period: '/mo', features: ['20 uploads / day','10 resumes stored','Job matching','Usage history'],      highlight: true,  plan: 'pro' },
  { name: 'Enterprise', price: '$29', period: '/mo', features: ['Unlimited uploads','Unlimited storage','API access','Priority queue'],      highlight: false, plan: 'enterprise' },
];

const steps = [
  { n: '1', label: 'Upload',   desc: 'Drop PDF or DOCX' },
  { n: '2', label: 'Optimize', desc: 'AI rewrites resume', active: true },
  { n: '3', label: 'Download', desc: 'Get your .docx' },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-surface page-fade">
      <TopNav />

      {/* Hero */}
      <section className="max-w-6xl mx-auto px-6 pt-20 pb-16 grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
        <div className="text-center lg:text-left">
          <div className="reveal reveal-1 inline-flex items-center gap-2 bg-accent-soft text-primary px-4 py-1.5 rounded-full text-sm font-medium mb-6">
            <Zap className="w-3.5 h-3.5" /> Powered by Gemini · Groq · Anthropic
          </div>
          <h1 className="reveal reveal-2 font-display text-5xl lg:text-6xl font-semibold text-ink leading-[1.1] mb-6">
            Your resume,<br /><span className="text-primary italic">set in type that gets you read.</span>
          </h1>
          <p className="reveal reveal-3 text-xl text-ink-mute mb-10 max-w-xl mx-auto lg:mx-0">
            Upload once. Score on 4 dimensions. Iterate until perfect. Get more interviews.
          </p>
          <div className="reveal reveal-4 flex items-center justify-center lg:justify-start gap-4">
            <Link to="/register" className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg font-semibold text-lg text-white dark:text-ink bg-primary hover:bg-primary-dark shadow-primary transition-all active:scale-95">
              Get started free <ArrowRight className="w-5 h-5" />
            </Link>
            <Link to="/login" className="text-ink-mute hover:text-ink px-6 py-3.5 font-medium transition-colors">
              Sign in →
            </Link>
          </div>
        </div>
        <div className="reveal reveal-3 h-[380px] lg:h-[460px] hidden sm:block">
          <HeroVisual />
        </div>
      </section>

      <section className="max-w-5xl mx-auto px-6 pb-8">
        {/* How it works */}
        <div className="bg-card rounded-card shadow-card border border-line px-8 py-6 max-w-lg mx-auto">
          <p className="text-[10px] font-bold tracking-widest text-ink-faint uppercase mb-5">How it works</p>
          <div className="flex items-center justify-between">
            {steps.map((s, i) => (
              <div key={s.n} className="flex items-center flex-1">
                <div className="flex flex-col items-center flex-1">
                  <div className={`w-9 h-9 rounded-full flex items-center justify-center mb-2 font-bold text-sm border-2 ${
                    s.active
                      ? 'border-primary bg-primary text-white dark:text-ink'
                      : 'border-primary text-primary bg-card'
                  }`}>
                    {s.n}
                  </div>
                  <div className="text-xs font-semibold text-ink">{s.label}</div>
                  <div className="text-[10px] text-ink-faint mt-0.5 text-center">{s.desc}</div>
                </div>
                {i < steps.length - 1 && (
                  <div className="h-px flex-1 mx-2 mb-6 bg-primary/40" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="bg-card rounded-card p-6 shadow-card border border-line hover:-translate-y-0.5 hover:shadow-lifted transition-all duration-200">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center mb-4 bg-accent-soft text-primary">
                <Icon className="w-5 h-5" />
              </div>
              <h3 className="font-semibold text-ink mb-2">{title}</h3>
              <p className="text-ink-mute text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing — fixed ink band in both themes */}
      <section className="bg-[#1E1A15] py-24">
        <div className="max-w-5xl mx-auto px-6">
          <h2 className="font-display text-3xl font-semibold text-[#EDE6DA] text-center mb-4">Simple, transparent pricing</h2>
          <p className="text-[#B2A99B] text-center mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map(({ name, price, period, features, highlight }) => (
              <div key={name} className="flex flex-col">
                <div className="h-7 flex items-center justify-center mb-1">
                  {highlight && <span className="bg-[#D9A03F] text-[#1E1A15] text-xs font-bold px-3 py-1 rounded-full whitespace-nowrap">Most popular</span>}
                </div>
                <div className={`rounded-card p-8 ${highlight ? 'bg-[#1A6B52] ring-2 ring-[#4DB892]/50 text-[#F2EFE6]' : 'bg-[#29231C] text-[#D9D2C5]'}`}>
                  <div className="font-semibold text-lg mb-1">{name}</div>
                  <div className="flex items-end gap-1 mb-6">
                    <span className="font-display text-4xl font-semibold">{price}</span>
                    <span className={`text-sm mb-1 ${highlight ? 'text-[#CFE8DD]' : 'text-[#7E766A]'}`}>{period}</span>
                  </div>
                  <ul className="space-y-3 mb-8">
                    {features.map(f => (
                      <li key={f} className="flex items-center gap-2 text-sm">
                        <Check className={`w-4 h-4 shrink-0 ${highlight ? 'text-[#F2EFE6]' : 'text-[#4DB892]'}`} />{f}
                      </li>
                    ))}
                  </ul>
                  <Link to="/register" className={`block text-center py-2.5 rounded-lg font-medium text-sm transition-colors ${highlight ? 'bg-[#F2EFE6] text-[#1A6B52] hover:bg-white' : 'bg-[#3C342A] hover:bg-[#4a4034] text-[#EDE6DA]'}`}>
                    Get started
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
