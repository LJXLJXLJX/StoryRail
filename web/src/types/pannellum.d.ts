declare module "pannellum";

interface PannellumViewer {
  destroy(): void;
  getHfov(): number;
  getPitch(): number;
  getYaw(): number;
  isLoaded(): boolean;
  lookAt(
    pitch?: number,
    yaw?: number,
    hfov?: number,
    animated?: boolean | number,
  ): PannellumViewer;
  off(event?: string, listener?: (...args: unknown[]) => void): PannellumViewer;
  on(event: string, listener: (...args: unknown[]) => void): PannellumViewer;
  resize(): void;
}

interface Window {
  pannellum?: {
    viewer(
      container: HTMLElement,
      config: Record<string, unknown>,
    ): PannellumViewer;
  };
}
