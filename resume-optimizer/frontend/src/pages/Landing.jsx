import { Link } from 'react-router-dom';
import { Zap, Target, Briefcase, ArrowRight, Check } from 'lucide-react';
import TopNav from '../components/layout/TopNav';

const features = [
  { icon: Zap,      color: 'text-primary bg-purple-50',  title: 'AI Rewriter',    desc: 'Gemini 2.5 Flash rewrites your resume to align with every JD keyword.' },
  { icon: Target,   color: 'text-teal bg-teal-50',       title: 'Smart Scoring',  desc: '4 scorers: ATS match, impact, skills gap, and readability — all in one call.' },
  { icon: Briefcase,color: 'text-amber bg-amber-50',     title: 'Job Matching',   desc: 'Nightly scrape of matched roles from Adzuna, RemoteOK, and The Muse.' },
];

const plans = [
  { name: 'Free',       price: '$0',   period: '/mo', features: ['2 uploads / day','1 resume stored','4 AI scorers','PDF + DOCX export'],    highlight: false, plan: 'free' },
  { name: 'Pro',        price: '$9',   period: '/mo', features: ['20 uploads / day','10 resumes stored','Job matching','Usage history'],      highlight: true,  plan: 'pro' },
  { name: 'Enterprise', price: '$29',  period: '/mo', features: ['Unlimited uploads','Unlimited storage','API access','Priority queue'],      highlight: false, plan: 'enterprise' },
];

export default function Landing() {
  return (
    <div className="min-h-screen bg-surface">
      <TopNav />

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-6 py-24 text-center">
        <div className="inline-flex items-center gap-2 bg-purple-50 text-primary px-4 py-1.5 rounded-full text-sm font-medium mb-6">
          <Zap className="w-3.5 h-3.5" /> Powered by Gemini 2.5 + Claude
        </div>
        <h1 className="text-5xl lg:text-6xl font-bold text-gray-900 leading-tight mb-6">
          Your resume,<br /><span className="text-primary">optimized by AI</span>
        </h1>
        <p className="text-xl text-gray-500 mb-10 max-w-2xl mx-auto">
          Upload once. Score on 4 dimensions. Iterate until perfect. Get more interviews.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link to="/register" className="bg-primary hover:bg-primary-dark text-white px-8 py-3.5 rounded-xl font-semibold text-lg flex items-center gap-2 transition-colors shadow-lg shadow-purple-200">
            Get started free <ArrowRight className="w-5 h-5" />
          </Link>
          <Link to="/app" className="text-gray-600 hover:text-gray-900 px-6 py-3.5 font-medium transition-colors">
            Try without account →
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {features.map(({ icon: Icon, color, title, desc }) => (
            <div key={title} className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-4 ${color}`}>
                <Icon className="w-5 h-5" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">{title}</h3>
              <p className="text-gray-500 text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="bg-gray-900 py-24">
        <div className="max-w-5xl mx-auto px-6">
          <h2 className="text-3xl font-bold text-white text-center mb-4">Simple, transparent pricing</h2>
          <p className="text-gray-400 text-center mb-12">Start free. Upgrade when you need more.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map(({ name, price, period, features, highlight }) => (
              <div key={name} className="flex flex-col">
                <div className="h-7 flex items-center justify-center mb-1">
                  {highlight && <span className="bg-amber-400 text-gray-900 text-xs font-bold px-3 py-1 rounded-full whitespace-nowrap">Most popular</span>}
                </div>
              <div className={`rounded-2xl p-8 ${highlight ? 'bg-primary ring-2 ring-primary/50 text-white' : 'bg-gray-800 text-gray-200'}`}>
                <div className="font-semibold text-lg mb-1">{name}</div>
                <div className="flex items-end gap-1 mb-6">
                  <span className="text-4xl font-bold">{price}</span>
                  <span className={`text-sm mb-1 ${highlight ? 'text-purple-200' : 'text-gray-400'}`}>{period}</span>
                </div>
                <ul className="space-y-3 mb-8">
                  {features.map(f => (
                    <li key={f} className="flex items-center gap-2 text-sm">
                      <Check className={`w-4 h-4 shrink-0 ${highlight ? 'text-white' : 'text-teal'}`} />{f}
                    </li>
                  ))}
                </ul>
                <Link to="/register" className={`block text-center py-2.5 rounded-xl font-medium text-sm transition-colors ${highlight ? 'bg-white text-primary hover:bg-purple-50' : 'bg-gray-700 hover:bg-gray-600 text-white'}`}>
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
