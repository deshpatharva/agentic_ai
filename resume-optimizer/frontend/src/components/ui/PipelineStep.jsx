import { CheckCircle, Loader2, Circle, XCircle } from 'lucide-react';
import { clsx } from 'clsx';

const icons = {
  done:    <CheckCircle className="w-5 h-5 text-green-500" />,
  running: <Loader2 className="w-5 h-5 text-primary animate-spin" />,
  pending: <Circle className="w-5 h-5 text-gray-300" />,
  error:   <XCircle className="w-5 h-5 text-red-500" />,
};

export default function PipelineStep({ label, status = 'pending', sublabel }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 shrink-0">{icons[status] || icons.pending}</div>
      <div>
        <div className={clsx('text-sm font-medium', status === 'pending' ? 'text-gray-400' : 'text-gray-800')}>{label}</div>
        {sublabel && <div className="text-xs text-gray-400 mt-0.5">{sublabel}</div>}
      </div>
    </div>
  );
}
