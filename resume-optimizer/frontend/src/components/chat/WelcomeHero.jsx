import { Sparkles, Link2, FileText, Target } from 'lucide-react';

const STARTERS = [
  { icon: Link2,    text: 'Paste a job posting URL and tailor my resume to it' },
  { icon: Target,   text: 'Which of my profiles fits a Senior Data Engineer role?' },
  { icon: FileText, text: 'What makes a resume bullet point strong?' },
];

/** First-load editorial welcome — serif headline + clickable starter prompts. */
export default function WelcomeHero({ onPick }) {
  return (
    <div className="max-w-lg mx-auto text-center pt-12 pb-8 px-4">
      <div className="reveal inline-flex items-center justify-center w-12 h-12 rounded-full bg-accent-soft mb-5">
        <Sparkles className="w-5 h-5 text-primary" />
      </div>

      <h2 className="reveal reveal-1 font-display text-[26px] leading-tight text-ink mb-2.5">
        Let's tailor your resume.
      </h2>
      <p className="reveal reveal-2 text-sm text-ink-mute mb-8 leading-relaxed">
        Drop a job link or description and I'll match it to your best profile,
        then sharpen it line by line.
      </p>

      <div className="flex flex-col gap-2">
        {STARTERS.map((s, i) => (
          <button
            key={s.text}
            onClick={() => onPick(s.text)}
            style={{ animationDelay: `${280 + i * 90}ms` }}
            className="reveal group flex items-center gap-3 text-left rounded-card border border-line bg-card px-4 py-3 text-sm text-ink-mute hover:text-ink hover:border-primary/40 hover:bg-surface-2 hover:shadow-card transition-all duration-200 active:scale-[0.99]"
          >
            <s.icon className="w-4 h-4 shrink-0 text-ink-faint group-hover:text-primary transition-colors" strokeWidth={1.75} />
            <span className="flex-1">{s.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
