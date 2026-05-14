import { fileUrl } from "../api";
import type { ArtifactInfo } from "../types";

type Props = {
  instrument: string;
  artifacts: ArtifactInfo[];
};

const order = ["gp5", "musicxml", "mid", "json", "svg", "png", "pdf"];

export function ArtifactPanel({ instrument, artifacts }: Props) {
  const sorted = [...artifacts].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  const svg = artifacts.find((artifact) => artifact.kind === "svg");

  return (
    <section className="artifact-panel">
      <div className="section-heading">
        <h2>{instrument}</h2>
      </div>
      {svg && (
        <div className="score-preview">
          <img src={fileUrl(svg.url)} alt={`${instrument} tab preview`} />
        </div>
      )}
      <div className="download-list">
        {sorted.map((artifact) => (
          <a key={artifact.url} href={fileUrl(artifact.url)} target="_blank" rel="noreferrer">
            <span>{artifact.kind.toUpperCase()}</span>
            <small>{artifact.name}</small>
          </a>
        ))}
      </div>
    </section>
  );
}
