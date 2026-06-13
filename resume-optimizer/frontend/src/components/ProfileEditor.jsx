import { useState } from 'react';
import { Plus } from 'lucide-react';
import BulletEditor from './BulletEditor';
import SkillChips from './SkillChips';
import Button from './ui/Button';

export default function ProfileEditor({ initialLabel = '', initialSections = {}, onSave, saving = false }) {
  const [label, setLabel] = useState(initialLabel);
  const [labelConfirmed, setLabelConfirmed] = useState(false);
  const [summary, setSummary] = useState(initialSections.summary || '');
  const [experience, setExperience] = useState(initialSections.experience || []);
  const [education, setEducation] = useState(initialSections.education || []);
  const [skills, setSkills] = useState(initialSections.skills || []);
  const [contact, setContact] = useState({
    full_name: '', location: '', email: '', phone: '', linkedin: '', website: '',
    ...(initialSections.contact || {}),
  });

  const updateContact = (patch) => setContact((prev) => ({ ...prev, ...patch }));

  const updateExp = (idx, patch) =>
    setExperience((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)));

  const updateEdu = (idx, patch) =>
    setEducation((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)));

  const handleSave = () => {
    onSave({ label, labelConfirmed, sections: { contact, summary, experience, education, skills } });
  };

  const fieldClass = 'w-full bg-card border border-line rounded-lg px-3 py-2 text-ink text-sm placeholder:text-ink-faint focus:border-primary focus:outline-none transition-colors';
  const sectionLabel = 'block text-xs font-semibold text-ink-faint uppercase tracking-wider mb-2';

  return (
    <div className="space-y-6">
      {/* Contact */}
      <div>
        <label className={sectionLabel}>Contact</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input className={fieldClass} placeholder="Full name"
            value={contact.full_name}
            onChange={(e) => updateContact({ full_name: e.target.value })} />
          <input className={fieldClass} placeholder="Location (e.g. Cincinnati, OH)"
            value={contact.location}
            onChange={(e) => updateContact({ location: e.target.value })} />
          <input className={fieldClass} placeholder="Email" type="email"
            value={contact.email}
            onChange={(e) => updateContact({ email: e.target.value })} />
          <input className={fieldClass} placeholder="Phone"
            value={contact.phone}
            onChange={(e) => updateContact({ phone: e.target.value })} />
          <input className={fieldClass} placeholder="LinkedIn URL"
            value={contact.linkedin}
            onChange={(e) => updateContact({ linkedin: e.target.value })} />
          <input className={fieldClass} placeholder="Website / GitHub URL"
            value={contact.website}
            onChange={(e) => updateContact({ website: e.target.value })} />
        </div>
      </div>

      {/* Label */}
      <div>
        <label className={sectionLabel}>Role / Profile Label</label>
        <div className="flex items-center gap-3">
          <input
            className={fieldClass}
            value={label}
            onChange={(e) => { setLabel(e.target.value); setLabelConfirmed(true); }}
            placeholder="e.g. Senior Software Engineer"
          />
          {!labelConfirmed && (
            <span className="shrink-0 text-[10px] bg-hilite-soft text-hilite px-2 py-0.5 rounded-full border border-hilite/30">
              AI suggested
            </span>
          )}
        </div>
      </div>

      {/* Summary */}
      <div>
        <label className={sectionLabel}>Summary</label>
        <textarea
          className={`${fieldClass} resize-none`}
          rows={3}
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="Professional summary…"
        />
      </div>

      {/* Experience */}
      <div>
        <label className={sectionLabel}>Experience</label>
        <div className="space-y-3">
          {experience.map((exp, idx) => (
            <div key={idx} className="bg-surface-2/60 border border-line rounded-card p-4">
              <div className="grid grid-cols-2 gap-3 mb-3">
                <input
                  className="bg-card border border-line rounded-lg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none"
                  placeholder="Company"
                  value={exp.company}
                  onChange={(e) => updateExp(idx, { company: e.target.value })}
                />
                <input
                  className="bg-card border border-line rounded-lg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none"
                  placeholder="Title"
                  value={exp.title}
                  onChange={(e) => updateExp(idx, { title: e.target.value })}
                />
                <input
                  className="col-span-2 bg-card border border-line rounded-lg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none"
                  placeholder="Dates (e.g. 2020–2024)"
                  value={exp.dates}
                  onChange={(e) => updateExp(idx, { dates: e.target.value })}
                />
              </div>
              <div className="space-y-0.5">
                {exp.bullets.map((b, bIdx) => (
                  <BulletEditor
                    key={bIdx}
                    bullet={b}
                    onUpdate={(val) =>
                      updateExp(idx, { bullets: exp.bullets.map((x, i) => (i === bIdx ? val : x)) })
                    }
                    onRemove={() =>
                      updateExp(idx, { bullets: exp.bullets.filter((_, i) => i !== bIdx) })
                    }
                  />
                ))}
              </div>
              <button
                onClick={() => updateExp(idx, { bullets: [...exp.bullets, 'Click pencil to edit this bullet'] })}
                className="mt-2 text-xs text-ink-faint hover:text-primary flex items-center gap-1 transition-colors"
              >
                <Plus className="w-3 h-3" /> Add bullet
              </button>
            </div>
          ))}
          <button
            onClick={() => setExperience([...experience, { company: '', title: '', dates: '', bullets: [] }])}
            className="text-xs text-ink-faint hover:text-primary flex items-center gap-1 border border-dashed border-line hover:border-primary/50 rounded-xl px-3 py-2.5 w-full justify-center transition-colors"
          >
            <Plus className="w-3 h-3" /> Add job
          </button>
        </div>
      </div>

      {/* Education */}
      <div>
        <label className={sectionLabel}>Education</label>
        <div className="space-y-3">
          {education.map((edu, idx) => (
            <div key={idx} className="bg-surface-2/60 border border-line rounded-card p-4">
              <div className="grid grid-cols-2 gap-3">
                <input
                  className="bg-card border border-line rounded-lg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none"
                  placeholder="Institution"
                  value={edu.institution}
                  onChange={(e) => updateEdu(idx, { institution: e.target.value })}
                />
                <input
                  className="bg-card border border-line rounded-lg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none"
                  placeholder="Degree"
                  value={edu.degree}
                  onChange={(e) => updateEdu(idx, { degree: e.target.value })}
                />
                <input
                  className="col-span-2 bg-card border border-line rounded-lg px-2 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-primary focus:outline-none"
                  placeholder="Dates"
                  value={edu.dates}
                  onChange={(e) => updateEdu(idx, { dates: e.target.value })}
                />
              </div>
            </div>
          ))}
          <button
            onClick={() => setEducation([...education, { institution: '', degree: '', dates: '' }])}
            className="text-xs text-ink-faint hover:text-primary flex items-center gap-1 border border-dashed border-line hover:border-primary/50 rounded-xl px-3 py-2.5 w-full justify-center transition-colors"
          >
            <Plus className="w-3 h-3" /> Add education
          </button>
        </div>
      </div>

      {/* Skills */}
      <div>
        <label className={sectionLabel}>Skills</label>
        <SkillChips skills={skills} onChange={setSkills} />
      </div>

      {/* Save */}
      <div className="pt-2 border-t border-line">
        <Button onClick={handleSave} disabled={saving} className="w-full justify-center">
          {saving ? 'Saving…' : 'Save Profile'}
        </Button>
      </div>
    </div>
  );
}
