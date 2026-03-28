import { clsx } from 'clsx';

export default function Card({ children, className, header, footer }) {
  return (
    <div className={clsx('bg-white rounded-2xl shadow-sm border border-gray-100', className)}>
      {header && <div className="px-6 py-4 border-b border-gray-100 font-semibold text-gray-800">{header}</div>}
      <div className="p-6">{children}</div>
      {footer && <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 rounded-b-2xl">{footer}</div>}
    </div>
  );
}
