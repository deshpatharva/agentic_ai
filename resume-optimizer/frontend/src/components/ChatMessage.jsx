import { clsx } from 'clsx';

export default function ChatMessage({ role, content, isError = false }) {
  const isUser = role === 'user';

  if (isUser) {
    return (
      <div className="flex justify-end mb-3">
        <div
          className="bg-primary text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm max-w-[75%]"
          style={{ whiteSpace: 'pre-wrap' }}
        >
          {content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2 mb-3">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center mt-0.5">
        <span className="text-[10px] font-semibold text-gray-500 select-none">AI</span>
      </div>
      <div
        className={clsx(
          'rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm max-w-[75%]',
          isError
            ? 'bg-red-50 text-red-700 border border-red-200'
            : 'bg-white border border-gray-200 text-gray-800 shadow-card'
        )}
        style={{ whiteSpace: 'pre-wrap' }}
      >
        {content}
      </div>
    </div>
  );
}
