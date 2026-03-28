import { clsx } from 'clsx';

export default function Card({ children, className, header, footer }) {
  return (
    <div className={clsx(
      'bg-white rounded-2xl shadow-card border border-[#ebebeb]',
      'hover:-translate-y-0.5 hover:shadow-lifted transition-all duration-200',
      className
    )}>
      {header && (
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          {typeof header === 'string'
            ? <span className="font-bold text-sm text-gray-900">{header}</span>
            : header}
        </div>
      )}
      <div className="p-6">{children}</div>
      {footer && (
        <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 rounded-b-2xl">{footer}</div>
      )}
    </div>
  );
}
