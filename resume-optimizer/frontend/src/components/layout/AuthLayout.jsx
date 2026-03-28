import { Zap } from 'lucide-react';

export default function AuthLayout({ children, title, subtitle }) {
  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-primary to-primary-dark flex-col justify-center px-16 text-white">
        <div className="flex items-center gap-3 mb-8">
          <Zap className="w-8 h-8" />
          <span className="text-2xl font-bold">ResumeAI</span>
        </div>
        <h2 className="text-4xl font-bold leading-tight mb-4">Your resume, optimized by AI</h2>
        <p className="text-purple-200 text-lg">Upload once. Score on 4 dimensions. Iterate until perfect. Get hired faster.</p>
        <div className="mt-12 grid grid-cols-2 gap-4">
          {[['4 AI Scorers','ATS, Impact, Skills, Structure'],['Smart Rewriter','Aligned to your exact JD'],['Job Matching','Nightly scrape of matched roles'],['Real-time Progress','Live pipeline status']].map(([t,d]) => (
            <div key={t} className="bg-white/10 rounded-xl p-4">
              <div className="font-semibold mb-1">{t}</div>
              <div className="text-purple-200 text-sm">{d}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="flex-1 flex flex-col justify-center px-8 lg:px-16 bg-white">
        <div className="max-w-md w-full mx-auto">
          <div className="flex items-center gap-2 mb-8 lg:hidden">
            <Zap className="w-6 h-6 text-primary" />
            <span className="text-xl font-bold">ResumeAI</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">{title}</h1>
          <p className="text-gray-500 mb-8">{subtitle}</p>
          {children}
        </div>
      </div>
    </div>
  );
}
