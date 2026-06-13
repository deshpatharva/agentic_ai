import { clsx } from 'clsx';

const styles = {
  free:       'bg-surface-2 text-ink-mute',
  pro:        'bg-accent-soft text-primary',
  enterprise: 'bg-hilite-soft text-hilite',
  admin:      'bg-err-soft text-err',
  green:      'bg-accent-soft text-primary',
  amber:      'bg-hilite-soft text-hilite',
  red:        'bg-err-soft text-err',
  blue:       'bg-accent-soft text-primary',
  teal:       'bg-accent-soft text-primary',
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
