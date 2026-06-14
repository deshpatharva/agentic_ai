/** Three animated dots — shown while waiting for the first agent token. */
export default function TypingDots() {
  return (
    <span className="flex items-center gap-1 h-4 px-1" aria-label="Thinking…">
      <span className="typing-dot w-1.5 h-1.5 rounded-full bg-ink-faint" />
      <span className="typing-dot w-1.5 h-1.5 rounded-full bg-ink-faint" />
      <span className="typing-dot w-1.5 h-1.5 rounded-full bg-ink-faint" />
    </span>
  );
}
