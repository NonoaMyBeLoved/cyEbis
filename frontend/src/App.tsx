import { useEffect, useMemo, useState } from "react";
import { createJob, getJob } from "./api";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { StemMixer } from "./components/StemMixer";
import type { JobStatus } from "./types";

export function App() {
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getJob(jobId);
        if (!cancelled) setJob(next);
        if (!cancelled && next.status !== "complete" && next.status !== "failed") {
          window.setTimeout(poll, 1200);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "작업 상태를 가져오지 못했습니다.");
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const groupedArtifacts = useMemo(() => {
    const groups: Record<string, JobStatus["artifacts"]> = {};
    for (const artifact of job?.artifacts ?? []) {
      groups[artifact.instrument] ??= [];
      groups[artifact.instrument].push(artifact);
    }
    return groups;
  }, [job]);

  async function submit() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setJob(null);
    try {
      const created = await createJob(file);
      setJobId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "업로드에 실패했습니다.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <main className="shell">
      <section className="topbar">
        <div>
          <p className="eyebrow">(대충 너무 AI 같아서 바꾼 텍스트)</p>
          <h1>노래 악기 분리기</h1>
        </div>
        <div className="status-pill">{job?.status ?? "ready"}</div>
      </section>

      <section className="upload-band">
        <label className="drop-zone">
          <input
            type="file"
            accept="audio/*,.mp3,.wav,.m4a,.flac,.ogg"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <span className="drop-title">{file ? file.name : "음악 파일을 선택하세요"}</span>
          <span className="drop-meta">
            MP3, WAV, M4A, FLAC, OGG 파일을 업로드하면 stem을 분리하고 기타/베이스 탭 추출을 준비합니다.
          </span>
        </label>
        <button className="primary" type="button" disabled={!file || uploading} onClick={submit}>
          {uploading ? "업로드 중" : "분리 시작"}
        </button>
      </section>

      {error && <section className="error">{error}</section>}

      {job && (
        <section className="progress-band">
          <div className="progress-heading">
            <strong>{job.message}</strong>
            <span>{Math.round(job.progress * 100)}%</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${job.progress * 100}%` }} />
          </div>
        </section>
      )}

      {job?.stems.length ? <StemMixer stems={job.stems} /> : null}

      {Object.keys(groupedArtifacts).length > 0 && (
        <section className="artifact-grid">
          {Object.entries(groupedArtifacts).map(([instrument, artifacts]) => (
            <ArtifactPanel key={instrument} instrument={instrument} artifacts={artifacts} />
          ))}
        </section>
      )}
    </main>
  );
}
