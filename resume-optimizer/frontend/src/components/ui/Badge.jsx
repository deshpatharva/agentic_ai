import { clsx } from 'clsx';

const styles = {
  free:       'bg-gray-100 text-gray-600',
  pro:        'bg-violet-100 text-violet-700',
  enterprise: 'bg-amber-100 text-amber-700',
  admin:      'bg-rose-100 text-rose-700',
  green:      'bg-green-100 text-green-700',
  amber:      'bg-amber-100 text-amber-700',
  red:        'bg-red-100 text-red-700',
  blue:       'bg-blue-100 text-blue-700',
  teal:       'bg-teal-100 text-teal-700',
};

export default function Badge({ variant = 'free', children, className }) {
  return (
    <span className={clsx(
      'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold',
      styles[variant],
      className
    )}>
      {children}
    </span>
  );
}
