import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  normalizeAzimuth,
  PanoramaCameraEditor,
  relativeYawOffset,
} from "./PanoramaCameraEditor";

const originalPannellum = window.pannellum;

afterEach(() => {
  window.pannellum = originalPannellum;
  vi.restoreAllMocks();
});

describe("panorama camera angles", () => {
  it("uses Core's clockwise 0-360 azimuth and signed fixture offsets", () => {
    expect(normalizeAzimuth(-10)).toBe(350);
    expect(normalizeAzimuth(370)).toBe(10);
    expect(relativeYawOffset(10, 350)).toBe(20);
    expect(relativeYawOffset(350, 10)).toBe(-20);
    expect(relativeYawOffset(180, 0)).toBe(-180);
  });
});

it("maps the live Pannellum camera to StoryRail yaw, pitch, and horizontal FOV", () => {
  let yaw = -10;
  let pitch = 12.24;
  let hfov = 64.96;
  let frame: FrameRequestCallback | null = null;
  const viewer = {
    destroy: vi.fn(),
    getHfov: vi.fn(() => hfov),
    getPitch: vi.fn(() => pitch),
    getYaw: vi.fn(() => yaw),
    isLoaded: vi.fn(() => true),
    lookAt: vi.fn(),
    off: vi.fn(),
    on: vi.fn(),
    resize: vi.fn(),
  };
  const factory = vi.fn(() => viewer);
  window.pannellum = { viewer: factory };
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frame = callback;
    return 1;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  const onChange = vi.fn();
  const rendered = render(
    <PanoramaCameraEditor
      panoramaUrl="/master.png"
      aspectRatio="16:9"
      view={{ yawDeg: 90, pitchDeg: 0, hfovDeg: 75 }}
      onChange={onChange}
    />,
  );

  expect(factory).toHaveBeenCalledWith(
    expect.any(HTMLElement),
    expect.objectContaining({
      panorama: "/master.png",
      yaw: 90,
      pitch: 0,
      hfov: 75,
      minPitch: -60,
      maxPitch: 60,
      minHfov: 20,
      maxHfov: 120,
      ignoreGPanoXMP: true,
    }),
  );
  act(() => frame?.(40));
  expect(onChange).toHaveBeenLastCalledWith({
    yawDeg: 350,
    pitchDeg: 12.2,
    hfovDeg: 65,
  });

  yaw = 45;
  pitch = -5;
  hfov = 35;
  rendered.rerender(
    <PanoramaCameraEditor
      panoramaUrl="/master.png"
      aspectRatio="16:9"
      view={{ yawDeg: 180, pitchDeg: -10, hfovDeg: 35 }}
      onChange={onChange}
    />,
  );
  expect(viewer.lookAt).toHaveBeenLastCalledWith(-10, -180, 35, false);
  rendered.unmount();
  expect(viewer.destroy).toHaveBeenCalledOnce();
});
