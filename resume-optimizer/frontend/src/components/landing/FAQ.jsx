const FAQS = [
  { q: 'Does it make up experience I don’t have?', a: 'No. A fabrication guard checks every rewritten claim against your real history, so the draft stays truthful.' },
  { q: 'What file formats can I use?', a: 'Upload a PDF or DOCX. Download your optimized resume as DOCX or PDF.' },
  { q: 'How is the score calculated?', a: 'Five dimensions: ATS match, impact, skills gap, readability, and how well the resume is tailored to the job description.' },
  { q: 'Is my data private?', a: 'Your resume is used only to optimize your own documents.' },
  { q: 'Is there a free tier?', a: 'Yes — start free, no credit card required.' },
];

export default function FAQ() {
  return (
    <section id="faq" className="max-w-3xl mx-auto px-6 py-24">
      <p className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">FAQ</p>
      <h2 className="font-display text-3xl font-semibold text-ink mb-10">Questions, answered.</h2>
      <div className="divide-y divide-line border-y border-line">
        {FAQS.map(({ q, a }) => (
          <details key={q} className="group py-4">
            <summary className="flex items-center justify-between cursor-pointer list-none font-medium text-ink focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none rounded">
              {q}
              <span className="font-mono text-primary text-lg transition-transform group-open:rotate-45">+</span>
            </summary>
            <p className="text-sm text-ink-mute leading-relaxed mt-3">{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
