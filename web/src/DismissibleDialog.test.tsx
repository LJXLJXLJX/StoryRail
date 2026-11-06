import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { expect, it, vi } from "vitest";
import { DismissibleDialog } from "./DismissibleDialog";

it("焦点在窗外或输入框内时都可用 Esc 关闭，且不触发保存", () => {
  const close = vi.fn();
  const save = vi.fn();
  render(<DismissibleDialog onClose={close} aria-label="编辑">
    <form onSubmit={save}>
      <textarea aria-label="正文" onKeyDown={(event) => event.stopPropagation()} />
    </form>
  </DismissibleDialog>);
  fireEvent.keyDown(document, { key: "Enter" });
  expect(close).not.toHaveBeenCalled();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(1);
  const input = screen.getByRole("textbox");
  input.focus();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(2);
  expect(save).not.toHaveBeenCalled();
});

it("嵌套窗口逐层关闭，长按和输入法事件不会连带关闭父窗口", () => {
  function Nested() {
    const [parent, setParent] = useState(true);
    const [child, setChild] = useState(true);
    return parent ? <DismissibleDialog onClose={() => setParent(false)} aria-label="父窗">
      {child ? <DismissibleDialog onClose={() => setChild(false)} aria-label="子窗" /> : null}
    </DismissibleDialog> : null;
  }
  render(<Nested />);
  fireEvent.keyDown(document, { key: "Escape", isComposing: true });
  expect(screen.getByRole("dialog", { name: "子窗" })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "子窗" })).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "父窗" })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape", repeat: true });
  expect(screen.getByRole("dialog", { name: "父窗" })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("portal 全图按实际层级优先关闭，底层窗口中的高 z-index 不越过父层级", () => {
  const previewClose = vi.fn();
  const editorClose = vi.fn();
  const panelClose = vi.fn();
  render(<>
    {createPortal(<div style={{ position: "fixed", zIndex: 1300 }}>
      <DismissibleDialog aria-label="全图" onClose={previewClose} />
    </div>, document.body)}
    <div style={{ position: "fixed", zIndex: 80 }}>
      <DismissibleDialog aria-label="编辑器" onClose={editorClose} />
    </div>
    <div style={{ position: "fixed", zIndex: 10 }}>
      <DismissibleDialog style={{ position: "absolute", zIndex: 9999 }}
        aria-label="顶栏" onClose={panelClose} />
    </div>
  </>);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(previewClose).toHaveBeenCalledTimes(1);
  expect(editorClose).not.toHaveBeenCalled();
  expect(panelClose).not.toHaveBeenCalled();
});

it("重渲染使用当前关闭回调，转发 ref，卸载后移除键盘监听", () => {
  const first = vi.fn();
  const latest = vi.fn();
  function Editor({ close }: { close: () => void }) {
    const ref = useRef<HTMLElement>(null);
    return <DismissibleDialog ref={ref} onClose={close} aria-label="编辑器" />;
  }
  const view = render(<Editor close={first} />);
  view.rerender(<Editor close={latest} />);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(first).not.toHaveBeenCalled();
  expect(latest).toHaveBeenCalledTimes(1);
  view.unmount();
  const event = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
  document.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);
  expect(latest).toHaveBeenCalledTimes(1);
});
