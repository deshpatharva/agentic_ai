import { useState } from 'react';
import { Plus, Pencil, Trash2, Check, X, MessageSquare } from 'lucide-react';
import { clsx } from 'clsx';
import useChatSessionStore from '../../store/chatSessionStore';

function timeAgo(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function SessionItem({ sess, active, onSelect, onRename, onDelete }) {
  const [editing, setEditing]   = useState(false);
  const [draft, setDraft]       = useState('');
  const [confirming, setConf]   = useState(false);

  function startEdit(e) {
    e.stopPropagation();
    setDraft(sess.title);
    setEditing(true);
  }

  async function commitRename(e) {
    e?.stopPropagation();
    if (draft.trim()) await onRename(sess.id, draft.trim());
    setEditing(false);
  }

  function cancelEdit(e) {
    e.stopPropagation();
    setEditing(false);
  }

  async function confirmDelete(e) {
    e.stopPropagation();
    if (confirming) {
      await onDelete(sess.id);
    } else {
      setConf(true);
      setTimeout(() => setConf(false), 3000);
    }
  }

  return (
    <div
      onClick={() => !editing && onSelect(sess)}
      className={clsx(
        'group flex items-start gap-2 px-3 py-2.5 rounded-lg cursor-pointer transition-colors',
        active
          ? 'bg-primary/10 border border-primary/20'
          : 'hover:bg-surface-2 border border-transparent',
      )}
    >
      <MessageSquare className="w-3.5 h-3.5 mt-0.5 shrink-0 text-ink-faint" />

      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename();
                if (e.key === 'Escape') cancelEdit(e);
              }}
              className="flex-1 text-xs bg-card border border-line rounded px-1.5 py-0.5 text-ink focus:outline-none focus:border-primary/50"
            />
            <button onClick={commitRename} className="text-primary hover:text-primary-dark p-0.5">
              <Check className="w-3 h-3" />
            </button>
            <button onClick={cancelEdit} className="text-ink-faint hover:text-ink p-0.5">
              <X className="w-3 h-3" />
            </button>
          </div>
        ) : (
          <>
            <p className="text-xs font-medium text-ink truncate leading-snug">{sess.title}</p>
            <p className="text-[10px] text-ink-faint mt-0.5">{timeAgo(sess.updated_at)}</p>
          </>
        )}
      </div>

      {!editing && (
        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <button
            onClick={startEdit}
            className="p-1 rounded text-ink-faint hover:text-ink hover:bg-surface-2 transition-colors"
            title="Rename"
          >
            <Pencil className="w-3 h-3" />
          </button>
          <button
            onClick={confirmDelete}
            className={clsx(
              'p-1 rounded transition-colors',
              confirming
                ? 'text-red-500 bg-red-500/10'
                : 'text-ink-faint hover:text-red-500 hover:bg-surface-2',
            )}
            title={confirming ? 'Click again to confirm' : 'Delete'}
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}

export default function SessionRail({ activeSessionId, onSelect, onNewChat }) {
  const { sessions, loading, renameSession, removeSession } = useChatSessionStore();

  return (
    <aside className="flex flex-col w-56 shrink-0 border-r border-line bg-surface h-full overflow-hidden">
      <div className="px-3 py-3 shrink-0 border-b border-line">
        <button
          onClick={onNewChat}
          className="flex items-center gap-2 w-full px-3 py-2 text-xs font-medium rounded-lg bg-primary text-white dark:text-ink hover:bg-primary-dark shadow-primary transition-all active:scale-95"
        >
          <Plus className="w-3.5 h-3.5" />
          New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {loading && sessions.length === 0 && (
          <p className="text-[11px] text-ink-faint px-2 py-2">Loading…</p>
        )}
        {!loading && sessions.length === 0 && (
          <p className="text-[11px] text-ink-faint px-2 py-3 text-center">No conversations yet.</p>
        )}
        {sessions.map((sess) => (
          <SessionItem
            key={sess.id}
            sess={sess}
            active={sess.id === activeSessionId}
            onSelect={onSelect}
            onRename={renameSession}
            onDelete={removeSession}
          />
        ))}
      </div>
    </aside>
  );
}
