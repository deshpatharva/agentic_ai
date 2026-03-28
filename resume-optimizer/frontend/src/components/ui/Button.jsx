import { clsx } from 'clsx';

const variants = {
  primary:   '[background:linear-gradient(135deg,#8b84e0,#7F77DD)] hover:opacity-90 text-white shadow-primary',
  secondary: 'bg-white hover:bg-gray-50 text-gray-700 border border-gray-200 shadow-card',
  ghost:     'bg-transparent hover:bg-gray-100 text-gray-600',
  danger:    'bg-red-600 hover:bg-red-700 text-white shadow-sm',
};
const sizes = {
  sm: 'px-3 py-1.5 text-sm rounded-xl',
  md: 'px-4 py-2 text-sm rounded-xl',
  lg: 'px-6 py-3 text-base rounded-xl',
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
