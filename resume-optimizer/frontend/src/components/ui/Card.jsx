import { clsx } from 'clsx';

export default function Card({ children, className, header, footer }) {
  return (
    <div className={clsx(
      'bg-card rounded-card shadow-card border border-line',
      'hover:border-ink-faint/40 hover:shadow-lifted transition-all duration-200',
      className
    )}>
      {header && (
        <div className="px-6 py-4 border-b border-line flex items-center justify-between">
          {typeof header === 'string'
            ? <span className="font-bold text-sm text-ink">{header}</span>
            : header}
        </div>
      )}
      <div className="p-6">{children}</div>
      {footer && (
        <div className="px-6 py-4 border-t border-line bg-surface-2 rounded-b-card">{footer}</div>
      )}
    </div>
  );
}
