import { clsx } from 'clsx';

export default function ProfilePicker({ profiles, onSelect, disabled = false }) {
  if (!profiles?.length) return null;
  return (
    <div className="ml-9 my-3 animate-fade-in">
      <p className="text-xs text-ink-faint mb-2 font-medium tracking-wide">
        Choose a profile to optimize:
      </p>
      <div className="flex flex-wrap gap-2">
        {profiles.map((p) => (
          <button
            key={p.id}
            disabled={disabled}
            onClick={() => onSelect(p)}
            className={clsx(
              'px-3.5 py-1.5 rounded-lg text-sm font-medium border transition-all duration-150 active:scale-95',
              disabled
                ? 'text-ink-faint border-line bg-surface-2 cursor-not-allowed'
                : 'text-primary border-primary/30 bg-accent-soft hover:bg-primary hover:text-white dark:hover:text-ink hover:border-primary shadow-sm'
            )}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
