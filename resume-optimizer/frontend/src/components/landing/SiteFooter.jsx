import { Link } from 'react-router-dom';

const COLUMNS = [
  { title: 'Product', links: [
    { label: 'How it works', href: '#how-it-works', type: 'anchor' },
    { label: 'Pricing',      href: '#pricing',      type: 'anchor' },
    { label: 'Sign in',      href: '/login',        type: 'route' },
    { label: 'Get started',  href: '/register',     type: 'route' },
  ]},
  { title: 'Company', links: [
    { label: 'About', href: '#', type: 'soon' },
    { label: 'Blog',  href: '#', type: 'soon' },
  ]},
  { title: 'Legal', links: [
    { label: 'Privacy', href: '#', type: 'soon' },
    { label: 'Terms',   href: '#', type: 'soon' },
  ]},
];

function FooterLink({ link }) {
  const cls = 'text-sm text-ink-mute hover:text-ink transition-colors';
  if (link.type === 'route') return <Link to={link.href} className={cls}>{link.label}</Link>;
  return <a href={link.href} className={cls}>{link.label}</a>;
}

export default function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="max-w-5xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
        <div className="col-span-2 md:col-span-1">
          <div className="font-display text-lg font-semibold text-ink mb-2">Resume Optimizer</div>
          <p className="text-xs text-ink-faint leading-relaxed">Powered by Gemini · Groq · Anthropic</p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.title}>
            <div className="font-mono text-[10px] uppercase tracking-widest text-ink-faint mb-3">{col.title}</div>
            <ul className="space-y-2">
              {col.links.map((link) => (
                <li key={link.label}><FooterLink link={link} /></li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-line">
        <div className="max-w-5xl mx-auto px-6 py-4 text-xs text-ink-faint">
          © {new Date().getFullYear()} Resume Optimizer. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
