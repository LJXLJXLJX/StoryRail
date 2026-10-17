import { useEffect, useRef, useState } from "react";

// 资产卡片里的紧凑音频播放器。原生 <audio controls> 在窄卡片里会溢出，
// 这里只保留播放/暂停、进度与时间，宽度完全跟随卡片。
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

export function AssetAudioPlayer({
  src,
  label,
}: {
  src: string;
  label: string;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    setPlaying(false);
    setDuration(0);
    setCurrent(0);
  }, [src]);

  function toggle() {
    const audio = audioRef.current;
    if (audio === null) return;
    if (audio.paused) {
      const started = audio.play();
      // 浏览器可能拒绝播放；保持暂停态即可，不阻塞卡片其它操作。
      if (started !== undefined) void started.catch(() => undefined);
    } else {
      audio.pause();
    }
  }

  function seek(value: number) {
    const audio = audioRef.current;
    setCurrent(value);
    if (audio !== null && Number.isFinite(value)) audio.currentTime = value;
  }

  return (
    <div className="playground-audio-player">
      <audio
        ref={audioRef}
        preload="metadata"
        src={src}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setCurrent(0);
        }}
        onTimeUpdate={(event) => setCurrent(event.currentTarget.currentTime)}
        onDurationChange={(event) => {
          const value = event.currentTarget.duration;
          setDuration(Number.isFinite(value) ? value : 0);
        }}
      />
      <button
        type="button"
        className="playground-audio-toggle"
        aria-label={`${playing ? "暂停" : "播放"} ${label}`}
        onClick={toggle}
      >
        <span aria-hidden="true">{playing ? "❙❙" : "▶"}</span>
      </button>
      <span className="playground-audio-clock">
        {formatClock(current)} / {formatClock(duration)}
      </span>
      <input
        type="range"
        className="playground-audio-seek"
        aria-label={`${label} 播放进度`}
        min={0}
        max={duration > 0 ? duration : 1}
        step={0.01}
        value={duration > 0 ? Math.min(current, duration) : 0}
        disabled={duration <= 0}
        onChange={(event) => seek(Number(event.target.value))}
      />
    </div>
  );
}
