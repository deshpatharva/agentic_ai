import { clsx } from 'clsx';
import { Loader2 } from 'lucide-react';

const rowStyles = {
  done:    'bg-green-50',
  running: 'bg-violet-50',
  pending: '',
  error:   'bg-red-50',
};
const iconStyles = {
  done:    'bg-green-100',
  running: 'bg-violet-100',
  pending: 'bg-gray-100',
  error:   'bg-red-100',
};
const labelStyles = {
  done:    'text-green-700',
  running: 'text-violet-700',
  pending: 'text-gray-400',
  error:   'text-red-700',
};
const badgeStyles = {
  done:    'bg-green-100 text-green-700',
  running: 'bg-violet-100 text-violet-700',
  error:   'bg-red-100 text-red-700',
};
const iconContent = {
  done:    <span className="text-green-600 text-sm font-bold">✓</span>,
  running: <Loader2 className="w-3.5 h-3.5 text-violet-600 animate-spin" />,
  pending: null,
  error:   <span className="text-red-600 text-sm font-bold">✕</span>,
};
const badgeLabel = {
  done:    'Done',
  running: 'Running',
  error:   'Error',
};

export default function PipelineStep({ label, status = 'pending', sublabel }) {
  return (
    <div className={clsx(
      'flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors duration-200',
      rowStyles[status]
    )}>
      <div className={clsx(
        'w-7 h-7 rounded-lg flex items-center justify-center shrink-0',
        iconStyles[status]
      )}>
        {iconContent[status]}
      </div>
      <div className="flex-1 min-w-0">
        <div className={clsx('text-xs font-semibold', labelStyles[status])}>{label}</div>
        {sublabel && <div className="text-[10px] text-gray-400 mt-0.5">{sublabel}</div>}
      </div>
      {badgeLabel[status] && (
        <span className={clsx('text-[10px] font-semibold px-2 py-0.5 rounded-full', badgeStyles[status])}>
          {badgeLabel[status]}
        </span>
      )}
    </div>
  );
}
