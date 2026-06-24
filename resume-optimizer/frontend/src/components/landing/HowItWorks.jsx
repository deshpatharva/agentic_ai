const STEPS = [
  { n: '01', title: 'Analyze the JD',    desc: 'Pull keywords, must-haves, and signals from the posting.' },
  { n: '02', title: 'Score your resume', desc: 'ATS match, impact, skills gap, readability, and JD tailoring.' },
  { n: '03', title: 'Rewrite & tailor',  desc: 'Align your bullets to what the role actually asks for.' },
  { n: '04', title: 'Humanize',          desc: 'Natural phrasing — not robotic keyword stuffing.' },
  { n: '05', title: 'Verify & guard',    desc: 'Every claim checked against your real history. Never fabricated.' },
  { n: '06', title: 'Generate',          desc: 'A clean .docx or .pdf, ready to send.' },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="max-w-5xl mx-auto px-6 py-24">
      <p className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">How it works</p>
      <h2 className="font-display text-3xl font-semibold text-ink mb-12 max-w-xl">
        Six steps from raw resume to a tailored, verified draft.
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-line border border-line rounded-card overflow-hidden">
        {STEPS.map(({ n, title, desc }) => (
          <div key={n} className="bg-card p-6">
            <span className="font-mono text-xs text-primary font-semibold">{n}</span>
            <h3 className="font-display text-lg font-semibold text-ink mt-2 mb-1.5">{title}</h3>
            <p className="text-sm text-ink-mute leading-relaxed">{desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
