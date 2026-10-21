import { useLayoutEffect, useRef, type ComponentPropsWithRef, type RefObject } from "react";

type Layer = { element: HTMLElement; close: () => void };
const layers = new Set<Layer>();

// 按实际浮层层级排序，兼顾 portal、嵌套窗口和高层级的全图预览。
function stackingPath(element: HTMLElement): HTMLElement[] {
  const path: HTMLElement[] = [];
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if ((style.zIndex !== "auto" && style.zIndex !== "") ||
        style.position === "fixed" || style.position === "sticky" ||
        (style.transform && style.transform !== "none") ||
        (style.filter && style.filter !== "none") ||
        (style.opacity !== "" && Number(style.opacity) < 1) ||
        style.isolation === "isolate") path.unshift(node);
  }
  if (path.at(-1) !== element) path.push(element);
  return path;
}

function compareLayers(a: Layer, b: Layer): number {
  const left = stackingPath(a.element);
  const right = stackingPath(b.element);
  let index = 0;
  while (left[index] && left[index] === right[index]) index += 1;
  if (!left[index]) return -1;
  if (!right[index]) return 1;
  const zDifference = (Number.parseInt(getComputedStyle(left[index]).zIndex) || 0) -
    (Number.parseInt(getComputedStyle(right[index]).zIndex) || 0);
  if (zDifference) return zDifference;
  return left[index].compareDocumentPosition(right[index]) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function dismissOnEscape(event: KeyboardEvent) {
  if (event.key !== "Escape" || event.isComposing || event.repeat) return;
  const top = [...layers].filter((layer) => layer.element.isConnected).sort(compareLayers).at(-1);
  if (!top) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  top.close();
}

export function useEscapeDismiss(
  ref: RefObject<HTMLElement | null>,
  onClose: () => void,
  enabled = true,
) {
  const close = useRef(onClose);
  useLayoutEffect(() => { close.current = onClose; });
  useLayoutEffect(() => {
    if (!enabled || !ref.current) return;
    const layer = { element: ref.current, close: () => close.current() };
    if (layers.size === 0) document.addEventListener("keydown", dismissOnEscape, true);
    layers.add(layer);
    return () => {
      layers.delete(layer);
      if (layers.size === 0) document.removeEventListener("keydown", dismissOnEscape, true);
    };
  }, [ref, enabled]);
}

export function DismissibleDialog({ onClose, ref, ...props }: ComponentPropsWithRef<"section"> & {
  onClose: () => void;
}) {
  const element = useRef<HTMLElement>(null);
  useEscapeDismiss(element, onClose);
  return <section {...props} role="dialog" ref={(node) => {
    element.current = node;
    if (typeof ref === "function") return ref(node);
    if (ref) ref.current = node;
  }} />;
}
