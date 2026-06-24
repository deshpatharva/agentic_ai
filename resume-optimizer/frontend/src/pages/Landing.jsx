import { Link } from 'react-router-dom';
import { Zap, ArrowRight, Check } from 'lucide-react';
import TopNav from '../components/layout/TopNav';
import HeroPreview from '../components/landing/HeroPreview';
import StatsRow from '../components/landing/StatsRow';
import HowItWorks from '../components/landing/HowItWorks';
import FAQ from '../components/landing/FAQ';
import FinalCTA from '../components/landing/FinalCTA';
import SiteFooter from '../components/landing/SiteFooter';

const plans = [
  { name: 'Free',       price: '$0',  period: '/mo', features: ['2 uploads / day','1 resume stored','5 AI scorers','PDF + DOCX export'],   highlight: false },
  { name: 'Pro',        price: '$9',  period: '/mo', features: ['20 uploads / day','10 resumes stored','Job matching','Usage history'],     highlight: true  },
  { name: 'Enterprise', price: '$29', period: '/mo', features: ['Unlimited uploads','Unlimited storage','API access','Priority queue'],     highlight: false },
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
            Tailored, scored,<br /><span className="text-primary">and verified — never faked.</span>
          </h1>
          <p className="reveal reveal-3 text-xl text-ink-mute mb-10 max-w-xl mx-auto lg:mx-0">
            Upload once. Score on five dimensions. Iterate until it peaks — with a guard that keeps every claim true.
          </p>
          <div className="reveal reveal-4 flex items-center justify-center lg:justify-start gap-4">
            <Link to="/register" className="inline-flex items-center gap-2 px-8 py-3.5 rounded-lg font-semibold text-lg text-white dark:text-surface bg-primary hover:bg-primary-dark shadow-primary transition-all active:scale-95 focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none">
              Get started free <ArrowRight className="w-5 h-5" />
            </Link>
            <Link to="/login" className="text-ink-mute hover:text-ink px-6 py-3.5 font-medium transition-colors">
              Sign in →
            </Link>
          </div>
        </div>
        <div className="reveal reveal-3 hidden sm:block">
          <HeroPreview />
        </div>
      </section>

      <StatsRow />

      <HowItWorks />

      {/* Pricing */}
      <section id="pricing" className="bg-surface-2 dark:bg-card py-24 border-y border-line">
        <div className="max-w-5xl mx-auto px-6">
          <h2 className="font-display text-3xl font-semibold text-ink text-center mb-4">Simple, transparent pricing</h2>
          <p className="text-ink-mute text-center mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map(({ name, price, period, features, highlight }) => (
              <div key={name} className="flex flex-col">
                <div className="h-7 flex items-center justify-center mb-1">
                  {highlight && <span className="bg-hilite text-surface text-xs font-bold px-3 py-1 rounded-full whitespace-nowrap">Most popular</span>}
                </div>
                <div className={`rounded-card p-8 border ${highlight ? 'bg-accent-soft border-primary/40 text-ink' : 'bg-card border-line text-ink'}`}>
                  <div className="font-semibold text-lg mb-1">{name}</div>
                  <div className="flex items-end gap-1 mb-6">
                    <span className="font-display text-4xl font-semibold">{price}</span>
                    <span className="text-sm mb-1 text-ink-faint">{period}</span>
                  </div>
                  <ul className="space-y-3 mb-8">
                    {features.map(f => (
                      <li key={f} className="flex items-center gap-2 text-sm">
                        <Check className="w-4 h-4 shrink-0 text-primary" />{f}
                      </li>
                    ))}
                  </ul>
                  <Link to="/register" className={`block text-center py-2.5 rounded-lg font-medium text-sm transition-colors ${highlight ? 'bg-primary hover:bg-primary-dark text-white dark:text-surface' : 'bg-surface-2 hover:bg-line text-ink'}`}>
                    Get started
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <FAQ />

      <FinalCTA />

      <SiteFooter />
    </div>
  );
}
