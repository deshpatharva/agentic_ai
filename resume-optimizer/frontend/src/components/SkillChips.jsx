import { useState } from 'react';
import { X, Plus } from 'lucide-react';

export default function SkillChips({ skills, onChange }) {
  const [adding, setAdding] = useState(false);
  const [newSkill, setNewSkill] = useState('');

  const addSkill = () => {
    const s = newSkill.trim();
    if (s && !skills.includes(s)) onChange([...skills, s]);
    setNewSkill('');
    setAdding(false);
  };

  return (
    <div className="flex flex-wrap gap-2">
      {skills.map((skill) => (
        <span
          key={skill}
          className="flex items-center gap-1 bg-primary/10 text-primary text-xs px-2.5 py-1 rounded-full font-medium"
        >
          {skill}
          <button
            onClick={() => onChange(skills.filter((s) => s !== skill))}
            aria-label={`Remove ${skill}`}
            className="hover:text-red-500 transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      {adding ? (
        <input
          className="text-xs bg-card border border-primary/40 rounded-full px-2.5 py-1 text-ink w-28 focus:outline-none focus:border-primary"
          placeholder="Add skill…"
          value={newSkill}
          onChange={(e) => setNewSkill(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addSkill();
            if (e.key === 'Escape') { setAdding(false); setNewSkill(''); }
          }}
          onBlur={addSkill}
          autoFocus
        />
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="flex items-center gap-1 text-xs text-ink-mute hover:text-primary border border-dashed border-line hover:border-primary/50 px-2.5 py-1 rounded-full transition-colors"
        >
          <Plus className="w-3 h-3" /> Add skill
        </button>
      )}
    </div>
  );
}
