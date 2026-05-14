import type { JobStatus } from "./types";

export const API_BASE = "http://127.0.0.1:8000";

export function fileUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export async function createJob(file: File): Promise<{ id: string; status_url: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/jobs`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export async function getJob(id: string): Promise<JobStatus> {
  const response = await fetch(`${API_BASE}/api/jobs/${id}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}
