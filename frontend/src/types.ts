export type StemInfo = {
  name: string;
  label: string;
  url: string;
};

export type ArtifactInfo = {
  name: string;
  instrument: "guitar" | "bass" | string;
  kind: string;
  url: string;
};

export type JobStatus = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  progress: number;
  message: string;
  warnings: string[];
  stems: StemInfo[];
  artifacts: ArtifactInfo[];
  created_at: string;
  completed_at: string | null;
};
