import { useState, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import ChatMessage from './ChatMessage';
import client from '../api/client';

const GREETING = "Hi! I'll help you build your resume profile. First, what's your full name, the city you're based in, and the best email, phone, and LinkedIn (or portfolio URL) to put on your resume?";

export default function InterviewChat({ onComplete }) {
  const [messages, setMessages] = useState([{ role: 'assistant', content: GREETING }]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || loading || done) return;

    const nextMessages = [...messages, { role: 'user', content: trimmed }];
    setMessages(nextMessages);
    setInput('');
    setLoading(true);

    try {
      const { data } = await client.post('/profile/ai-interview/message', {
        history: nextMessages,
        user_message: trimmed,
      });

      const assistantMessage = { role: 'assistant', content: data.reply ?? '' };
      const updatedMessages = [...nextMessages, assistantMessage];
      setMessages(updatedMessages);

      if (data.done === true) {
        setDone(true);
        try {
          const { data: sections } = await client.post('/profile/ai-interview/finish', {
            history: updatedMessages,
          });
          if (onComplete) onComplete(sections);
        } catch {
          // finish failed — onComplete not called, user can retry
        }
      }
    } catch (err) {
      const msg = err?.response?.data?.detail ?? 'Something went wrong. Please try again.';
      setMessages((prev) => [...prev, { role: 'assistant', content: msg, isError: true }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col bg-white border border-gray-200 shadow-card rounded-xl overflow-hidden">
      <div ref={scrollRef} className="h-96 overflow-y-auto px-4 py-4 flex flex-col">
        {messages.map((msg, i) => (
          <ChatMessage key={i} role={msg.role} content={msg.content} isError={msg.isError ?? false} />
        ))}

        {loading && (
          <div className="flex items-start gap-2 mb-3">
            <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center mt-0.5">
              <span className="text-[10px] font-semibold text-gray-500 select-none">AI</span>
            </div>
            <div className="bg-white border border-gray-200 shadow-card rounded-2xl rounded-bl-sm px-4 py-2.5">
              <div className="flex items-center gap-1.5">
                {[0, 150, 300].map((delay) => (
                  <span key={delay} className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-pulse" style={{ animationDelay: `${delay}ms` }} />
                ))}
              </div>
            </div>
          </div>
        )}

        {done && (
          <p className="text-center text-xs text-gray-400 mt-2">Interview complete — generating your profile…</p>
        )}
      </div>

      {!done && (
        <div className="border-t border-gray-100 px-3 py-2.5 flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
            placeholder="Type your answer…"
            rows={1}
            disabled={loading}
            className="flex-1 resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary/30 transition-colors"
            style={{ maxHeight: '120px', overflowY: 'auto' }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 w-9 h-9 rounded-lg bg-primary text-white flex items-center justify-center hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
