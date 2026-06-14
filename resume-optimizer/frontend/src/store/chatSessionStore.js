import { create } from 'zustand';
import { listSessions, renameSession, deleteSession } from '../api/sessions';

const useChatSessionStore = create((set) => ({
  sessions: [],
  loading: false,

  fetchSessions: async () => {
    set({ loading: true });
    try {
      const { data } = await listSessions();
      set({ sessions: data });
    } finally {
      set({ loading: false });
    }
  },

  addOrUpdateSession: (sess) => {
    set((state) => {
      const exists = state.sessions.some((s) => s.id === sess.id);
      if (exists) {
        return { sessions: state.sessions.map((s) => (s.id === sess.id ? { ...s, ...sess } : s)) };
      }
      return { sessions: [sess, ...state.sessions] };
    });
  },

  renameSession: async (id, title) => {
    const { data } = await renameSession(id, title);
    set((state) => ({
      sessions: state.sessions.map((s) => (s.id === id ? { ...s, title: data.title } : s)),
    }));
  },

  removeSession: async (id) => {
    await deleteSession(id);
    set((state) => ({ sessions: state.sessions.filter((s) => s.id !== id) }));
  },
}));

export default useChatSessionStore;
