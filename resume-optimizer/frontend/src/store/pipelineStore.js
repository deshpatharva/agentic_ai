import { create } from 'zustand';

const usePipelineStore = create((set) => ({
  status:    'idle',   // idle | running | done | error
  stages:    {},
  logs:      [],
  scores:    null,
  jobId:     null,
  iteration: 0,
  downloadUrl: null,

  setJobId:      (jobId)    => set({ jobId }),
  setStatus:     (status)   => set({ status }),
  setScores:     (scores)   => set({ scores }),
  setDownload:   (url)      => set({ downloadUrl: url }),
  setIteration:  (n)        => set({ iteration: n }),
  addLog:        (entry)    => set((s) => ({ logs: [...s.logs, entry] })),
  setStage:      (stage, st) => set((s) => ({ stages: { ...s.stages, [stage]: st } })),

  reset: () => set({
    status: 'idle', stages: {}, logs: [], scores: null,
    jobId: null, iteration: 0, downloadUrl: null,
  }),
}));

export default usePipelineStore;
