import { useState } from 'react';
import { Pencil, X, Check } from 'lucide-react';

export default function BulletEditor({ bullet, onUpdate, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(bullet);

  const commit = () => {
    if (value.trim()) onUpdate(value.trim());
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="flex items-start gap-2 py-1">
        <textarea
          className="flex-1 text-sm bg-gray-100 border border-primary/40 rounded px-2 py-1 text-gray-900 resize-none focus:outline-none focus:border-primary"
          rows={2}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commit(); } }}
          autoFocus
        />
        <button onClick={commit} className="text-green-600 hover:text-green-700 mt-1 shrink-0">
          <Check className="w-4 h-4" />
        </button>
        <button onClick={() => { setValue(bullet); setEditing(false); }} className="text-gray-400 hover:text-gray-600 mt-1 shrink-0">
          <X className="w-4 h-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2 py-1 group">
      <span className="text-gray-400 mt-0.5 shrink-0">•</span>
      <span className="flex-1 text-sm text-gray-700">{bullet}</span>
      <button
        onClick={() => setEditing(true)}
        className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-primary transition-opacity shrink-0"
      >
        <Pencil className="w-3.5 h-3.5" />
      </button>
      <button
        onClick={onRemove}
        className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-opacity shrink-0"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
