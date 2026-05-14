import { useRef, useState } from "react";
import { fileUrl } from "../api";
import type { StemInfo } from "../types";

type Props = {
  stems: StemInfo[];
};

const VOLUME_MUTE_THRESHOLD = 0.03;

export function StemMixer({ stems }: Props) {
  const refs = useRef<Record<string, HTMLAudioElement | null>>({});
  const [volumes, setVolumes] = useState<Record<string, number>>({});
  const [muted, setMuted] = useState<Record<string, boolean>>({});
  const [solo, setSolo] = useState<string | null>(null);

  function setVolume(name: string, value: number) {
    setVolumes((current) => ({ ...current, [name]: value }));
    setMuted((current) => ({ ...current, [name]: value < VOLUME_MUTE_THRESHOLD }));
    const audio = refs.current[name];
    if (audio) {
      audio.volume = value;
      audio.muted = value < VOLUME_MUTE_THRESHOLD;
    }
  }

  function playAll() {
    const currentTime = Math.min(...stems.map((stem) => refs.current[stem.name]?.currentTime ?? 0));
    for (const stem of stems) {
      const audio = refs.current[stem.name];
      if (!audio) continue;
      audio.currentTime = Number.isFinite(currentTime) ? currentTime : 0;
      const volume = volumes[stem.name] ?? 1;
      if (solo && stem.name !== solo) {
        audio.pause();
      } else if (!muted[stem.name] && volume >= VOLUME_MUTE_THRESHOLD) {
        audio.play();
      }
    }
  }

  function pauseAll() {
    for (const stem of stems) refs.current[stem.name]?.pause();
  }

  return (
    <section className="mixer">
      <div className="section-heading">
        <h2 className="sr-only">Mixer</h2>
        <div className="transport">
          <button type="button" onClick={playAll}>Play</button>
          <button type="button" onClick={pauseAll}>Pause</button>
        </div>
      </div>
      <div className="stem-list">
        {stems.map((stem) => {
          const volume = volumes[stem.name] ?? 1;
          const isMuted = Boolean(muted[stem.name]);
          const isSolo = solo === stem.name;
          return (
            <div className="stem-row" key={stem.name}>
              <div className="stem-name">
                <strong>{stem.label}</strong>
                <span>{stem.name}</span>
              </div>
              <audio
                ref={(node) => {
                  refs.current[stem.name] = node;
                  if (node) {
                    node.volume = volume;
                    node.muted = isMuted || volume < VOLUME_MUTE_THRESHOLD;
                  }
                }}
                src={fileUrl(stem.url)}
                controls
              />
              <label className="volume">
                <span>{Math.round(volume * 100)}</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={volume}
                  draggable={false}
                  onChange={(event) => setVolume(stem.name, Number(event.target.value))}
                />
              </label>
              <button
                className={isMuted ? "toggle active" : "toggle"}
                type="button"
                onClick={() => setMuted((current) => ({ ...current, [stem.name]: !current[stem.name] }))}
              >
                {isMuted || volume < VOLUME_MUTE_THRESHOLD ? "🔇" : "🔈"}
              </button>
              <button
                className={isSolo ? "toggle active" : "toggle"}
                type="button"
                onClick={() => setSolo(isSolo ? null : stem.name)}
              >
                Solo
              </button>
              <button className="toggle" type="button" disabled>
                탭 추출
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
