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

  const updateExp = (idx, patch) =>
    setExperience((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)));

  const updateEdu = (idx, patch) =>
    setEducation((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)));

  const handleSave = () => {
    onSave({ label, labelConfirmed, sections: { summary, experience, education, skills } });
  };

  const fieldClass = 'w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-gray-900 text-sm focus:border-primary focus:outline-none transition-colors';
  const sectionLabel = 'block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2';

  return (
    <div className="space-y-6">
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
            <span className="shrink-0 text-[10px] bg-amber-50 text-amber-600 px-2 py-0.5 rounded-full border border-amber-200">
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
            <div key={idx} className="bg-gray-50 border border-gray-200 rounded-xl p-4">
              <div className="grid grid-cols-2 gap-3 mb-3">
                <input
                  className="bg-white border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-gray-900 focus:border-primary focus:outline-none"
                  placeholder="Company"
                  value={exp.company}
                  onChange={(e) => updateExp(idx, { company: e.target.value })}
                />
                <input
                  className="bg-white border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-gray-900 focus:border-primary focus:outline-none"
                  placeholder="Title"
                  value={exp.title}
                  onChange={(e) => updateExp(idx, { title: e.target.value })}
                />
                <input
                  className="col-span-2 bg-white border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-gray-900 focus:border-primary focus:outline-none"
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
                className="mt-2 text-xs text-gray-400 hover:text-primary flex items-center gap-1 transition-colors"
              >
                <Plus className="w-3 h-3" /> Add bullet
              </button>
            </div>
          ))}
          <button
            onClick={() => setExperience([...experience, { company: '', title: '', dates: '', bullets: [] }])}
            className="text-xs text-gray-400 hover:text-primary flex items-center gap-1 border border-dashed border-gray-300 hover:border-primary/50 rounded-xl px-3 py-2.5 w-full justify-center transition-colors"
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
            <div key={idx} className="bg-gray-50 border border-gray-200 rounded-xl p-4">
              <div className="grid grid-cols-2 gap-3">
                <input
                  className="bg-white border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-gray-900 focus:border-primary focus:outline-none"
                  placeholder="Institution"
                  value={edu.institution}
                  onChange={(e) => updateEdu(idx, { institution: e.target.value })}
                />
                <input
                  className="bg-white border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-gray-900 focus:border-primary focus:outline-none"
                  placeholder="Degree"
                  value={edu.degree}
                  onChange={(e) => updateEdu(idx, { degree: e.target.value })}
                />
                <input
                  className="col-span-2 bg-white border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-gray-900 focus:border-primary focus:outline-none"
                  placeholder="Dates"
                  value={edu.dates}
                  onChange={(e) => updateEdu(idx, { dates: e.target.value })}
                />
              </div>
            </div>
          ))}
          <button
            onClick={() => setEducation([...education, { institution: '', degree: '', dates: '' }])}
            className="text-xs text-gray-400 hover:text-primary flex items-center gap-1 border border-dashed border-gray-300 hover:border-primary/50 rounded-xl px-3 py-2.5 w-full justify-center transition-colors"
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
      <div className="pt-2 border-t border-gray-100">
        <Button onClick={handleSave} disabled={saving} className="w-full justify-center">
          {saving ? 'Saving…' : 'Save Profile'}
        </Button>
      </div>
    </div>
  );
}
