/** Composing indicator — wave dots + a soft cue, shown while the agent drafts a reply. */
export default function TypingDots() {
  return (
    <span className="flex items-center gap-2 h-4" aria-label="Composing reply">
      <span className="flex items-center gap-1">
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-primary/70" />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-primary/70" />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-primary/70" />
      </span>
      <span className="typing-label text-[11px] italic text-ink-faint select-none">composing</span>
    </span>
  );
}
