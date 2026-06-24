import { clsx } from 'clsx';

const variants = {
  primary:   'bg-primary hover:bg-primary-dark text-white dark:text-surface shadow-primary',
  secondary: 'bg-card hover:bg-surface-2 text-ink border border-line shadow-card',
  ghost:     'bg-transparent hover:bg-surface-2 text-ink-mute',
  danger:    'bg-err hover:opacity-90 text-white shadow-sm',
};
const sizes = {
  sm: 'px-3 py-1.5 text-sm rounded-lg',
  md: 'px-4 py-2 text-sm rounded-lg',
  lg: 'px-6 py-3 text-base rounded-lg',
};

export default function Button({ variant = 'primary', size = 'md', className, disabled, children, ...props }) {
  return (
    <button
      className={clsx(
        'font-semibold transition-all duration-150 inline-flex items-center gap-2 cursor-pointer',
        'active:scale-95',
        'focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-1 focus-visible:outline-none',
        variants[variant], sizes[size],
        disabled && 'opacity-50 cursor-not-allowed',
        className
      )}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
