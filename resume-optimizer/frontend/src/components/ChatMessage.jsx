import { Link } from 'react-router-dom';
import { Download } from 'lucide-react';
import { clsx } from 'clsx';
import TypingDots from './chat/TypingDots';

export default function ChatMessage({ role, content, isError = false, action = null, loading = false, download = null }) {
  const isUser = role === 'user';

  if (isUser) {
    return (
      <div className="msg-in flex justify-end mb-3">
        <div
          className="bg-primary text-white dark:text-surface rounded-card rounded-br-sm px-4 py-2.5 text-sm max-w-[75%] shadow-primary"
          style={{ whiteSpace: 'pre-wrap' }}
        >
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="msg-in flex items-start gap-2 mb-3">
      <div className={clsx(
        'flex-shrink-0 w-7 h-7 rounded-full bg-surface-2 flex items-center justify-center mt-0.5 transition-all duration-300',
        loading && 'ring-2 ring-primary/40 ring-offset-1 ring-offset-surface stage-pulse'
      )}>
        <span className="text-[10px] font-semibold text-ink-faint select-none">AI</span>
      </div>
      <div
        className={clsx(
          'rounded-card rounded-bl-sm px-4 py-2.5 text-sm max-w-[75%] min-h-[38px]',
          isError
            ? 'bg-err-soft text-err border border-err/30'
            : 'bg-card border border-line text-ink shadow-card'
        )}
        style={{ whiteSpace: 'pre-wrap' }}
      >
        {loading && !content ? <TypingDots /> : content}
        {action && (
          <div className="mt-2">
            <Link
              to={action.href}
              className="inline-block text-xs font-medium text-primary underline underline-offset-2"
            >
              {action.label} →
            </Link>
          </div>
        )}
        {download && (
          <div className="mt-2.5">
            <a
              href={download.href}
              download
              className="inline-flex items-center gap-1.5 bg-primary text-white dark:text-surface text-xs font-semibold px-3 py-1.5 rounded-lg shadow-primary hover:bg-primary-dark transition-colors active:scale-95"
            >
              <Download className="w-3.5 h-3.5" />
              {download.label || 'Download .docx'}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
