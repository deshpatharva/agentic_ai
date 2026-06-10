import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import useProfileStore from "../store/profileStore";
import ProfileEditor from "../components/ProfileEditor";
import Button from "../components/ui/Button";

export default function ProfilesPage() {
  const { profiles, loading, fetchProfiles, updateProfile, deleteProfile } =
    useProfileStore();
  const navigate = useNavigate();

  const [expandedId, setExpandedId] = useState(null);
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  function toggleExpand(id) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  async function handleSave(profile, { label, labelConfirmed, sections }) {
    setSavingId(profile.id);
    try {
      await updateProfile(profile.id, { label, labelConfirmed, sections });
      setExpandedId(null);
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(profile) {
    if (!window.confirm("Delete this profile?")) return;
    await deleteProfile(profile.id);
    if (expandedId === profile.id) setExpandedId(null);
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <p className="text-gray-500 text-sm">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface py-10 px-4">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Profiles</h1>
          <Link
            to="/profiles/new"
            className="inline-flex items-center gap-1.5 bg-primary text-white text-sm font-semibold px-4 py-2 rounded-xl hover:opacity-90 transition-opacity"
          >
            <Plus size={16} />
            New Profile
          </Link>
        </div>

        {profiles.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 border-2 border-dashed border-gray-300 rounded-xl bg-white text-center gap-4">
            <p className="text-gray-500 font-medium">No profiles yet</p>
            <Button onClick={() => navigate("/profiles/new")}>
              <Plus size={16} />
              Create your first profile
            </Button>
          </div>
        ) : (
          <div>
            {profiles.map((profile) => {
              const isExpanded = expandedId === profile.id;
              const isSaving = savingId === profile.id;

              return (
                <div
                  key={profile.id}
                  className="bg-white border border-gray-200 rounded-xl shadow-card mb-3 overflow-hidden"
                >
                  <button
                    type="button"
                    onClick={() => toggleExpand(profile.id)}
                    className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="font-semibold text-gray-900 truncate">
                        {profile.label || "Untitled Profile"}
                      </span>
                      {typeof profile.use_count === "number" && (
                        <span className="shrink-0 text-xs text-gray-500 bg-gray-100 rounded-full px-2.5 py-0.5">
                          {profile.use_count}{" "}
                          {profile.use_count === 1 ? "use" : "uses"}
                        </span>
                      )}
                    </div>
                    <span className="text-gray-400 shrink-0 ml-3">
                      {isExpanded ? (
                        <ChevronUp size={18} />
                      ) : (
                        <ChevronDown size={18} />
                      )}
                    </span>
                  </button>

                  {isExpanded && (
                    <div className="px-5 pb-5 border-t border-gray-100">
                      <div className="pt-4">
                        <ProfileEditor
                          initialLabel={profile.label}
                          initialSections={profile.sections}
                          saving={isSaving}
                          onSave={(payload) => handleSave(profile, payload)}
                        />
                      </div>
                      <div className="mt-4 flex justify-end">
                        <button
                          type="button"
                          onClick={() => handleDelete(profile)}
                          className="flex items-center gap-1.5 text-sm text-red-600 hover:text-red-700 hover:bg-red-50 px-3 py-1.5 rounded-lg transition-colors"
                        >
                          <Trash2 size={15} />
                          Delete profile
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
