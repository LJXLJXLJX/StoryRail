import { useEffect, useRef, useState } from "react";
import "pannellum";
import "pannellum/build/pannellum.css";

export type CameraView = {
  yawDeg: number;
  pitchDeg: number;
  hfovDeg: number;
};

export function normalizeAzimuth(value: number) {
  const normalized = ((value % 360) + 360) % 360;
  return normalized === 360 ? 0 : normalized;
}

export function relativeYawOffset(yaw: number, origin: number) {
  const offset = ((yaw - origin + 540) % 360) - 180;
  return Object.is(offset, -0) ? 0 : offset;
}

function displayAngle(value: number) {
  const rounded = Math.round(value * 10) / 10;
  return Object.is(rounded, -0) ? 0 : rounded;
}

function signedYaw(value: number) {
  const normalized = normalizeAzimuth(value);
  return normalized >= 180 ? normalized - 360 : normalized;
}

function sameView(a: CameraView | null, b: CameraView) {
  return (
    a !== null &&
    a.yawDeg === b.yawDeg &&
    a.pitchDeg === b.pitchDeg &&
    a.hfovDeg === b.hfovDeg
  );
}

export function PanoramaCameraEditor({
  panoramaUrl,
  aspectRatio,
  view,
  onChange,
}: {
  panoramaUrl: string;
  aspectRatio: "16:9" | "9:16" | "2:1";
  view: CameraView;
  onChange: (view: CameraView) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<PannellumViewer | null>(null);
  const onChangeRef = useRef(onChange);
  const lastReportedRef = useRef<CameraView | null>(null);
  const [error, setError] = useState("");
  onChangeRef.current = onChange;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !window.pannellum) {
      setError("浏览器无法启动全景机位预览。");
      return;
    }
    setError("");
    lastReportedRef.current = {
      yawDeg: displayAngle(normalizeAzimuth(view.yawDeg)),
      pitchDeg: displayAngle(view.pitchDeg),
      hfovDeg: displayAngle(view.hfovDeg),
    };
    let animationFrame = 0;
    let previousFrame = 0;
    const viewer = window.pannellum.viewer(container, {
      type: "equirectangular",
      panorama: panoramaUrl,
      autoLoad: true,
      yaw: signedYaw(view.yawDeg),
      pitch: view.pitchDeg,
      hfov: view.hfovDeg,
      minPitch: -60,
      maxPitch: 60,
      minHfov: 20,
      maxHfov: 120,
      mouseZoom: true,
      keyboardZoom: true,
      showControls: false,
      showFullscreenCtrl: false,
      orientationOnByDefault: false,
      ignoreGPanoXMP: true,
      escapeHTML: true,
      friction: 0.9,
      strings: {
        loadingLabel: "正在载入全景…",
        genericWebGLError: "浏览器无法使用 WebGL 渲染全景。",
        textureSizeError: "这张全景图超过了当前设备的纹理尺寸上限。",
        unknownError: "全景载入失败。",
      },
    });
    viewerRef.current = viewer;
    const report = () => {
      const next = {
        yawDeg: displayAngle(normalizeAzimuth(viewer.getYaw())),
        pitchDeg: displayAngle(viewer.getPitch()),
        hfovDeg: displayAngle(viewer.getHfov()),
      };
      if (!sameView(lastReportedRef.current, next)) {
        lastReportedRef.current = next;
        onChangeRef.current(next);
      }
    };
    const watch = (time: number) => {
      if (time - previousFrame >= 32) {
        previousFrame = time;
        report();
      }
      animationFrame = window.requestAnimationFrame(watch);
    };
    const showError = (message: unknown) =>
      setError(typeof message === "string" ? message : "全景载入失败。");
    viewer.on("error", showError);
    animationFrame = window.requestAnimationFrame(watch);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      viewer.off("error", showError);
      viewer.destroy();
      viewerRef.current = null;
    };
    // Recreate only when the immutable source panorama changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panoramaUrl]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const current = {
      yawDeg: displayAngle(normalizeAzimuth(viewer.getYaw())),
      pitchDeg: displayAngle(viewer.getPitch()),
      hfovDeg: displayAngle(viewer.getHfov()),
    };
    const next = {
      yawDeg: displayAngle(normalizeAzimuth(view.yawDeg)),
      pitchDeg: displayAngle(view.pitchDeg),
      hfovDeg: displayAngle(view.hfovDeg),
    };
    if (!sameView(current, next)) {
      lastReportedRef.current = next;
      viewer.lookAt(next.pitchDeg, signedYaw(next.yawDeg), next.hfovDeg, false);
    }
  }, [view.hfovDeg, view.pitchDeg, view.yawDeg]);

  const ratio = aspectRatio.replace(":", " / ");
  return (
    <div className="location-camera-editor">
      <div
        className={`location-camera-viewport${aspectRatio === "9:16" ? " is-portrait" : ""}`}
        style={{ aspectRatio: ratio }}
      >
        <div
          ref={containerRef}
          className="location-camera-panorama"
          aria-label="实时机位预览"
        />
        <span className="location-camera-reticle" aria-hidden="true" />
        <div className="location-camera-readout" aria-hidden="true">
          <span>方位 {displayAngle(view.yawDeg)}°</span>
          <span>俯仰 {displayAngle(view.pitchDeg)}°</span>
          <span>视场 {displayAngle(view.hfovDeg)}°</span>
        </div>
      </div>
      {error ? <p className="location-camera-error" role="alert">{error}</p> : null}
      <p className="location-camera-help">
        拖动画面转动机位，滚轮或触控板调整视场角；中央十字就是最终裁切画面中心。
      </p>
    </div>
  );
}
