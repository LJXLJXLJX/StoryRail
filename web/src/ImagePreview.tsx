import { DismissibleDialog } from "./DismissibleDialog";
import { useRef, useState } from "react";
import { createPortal } from "react-dom";

// 图片放大查看：所有展示图片的地方共用同一个全图浮层，浮层始终挂到 body 并位于所有弹窗之上。
// - ZoomableImage：图片本身就是放大触发器，用于纯展示的图片；
// - ImageZoomButton：图片所在卡片本身是选择按钮或标签时，在角落放一个独立的放大按钮，
//   点击不会触发外层的选择。

function ImagePreviewDialog({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  return createPortal(
    <div
      className="image-preview-backdrop"
      onClick={(event) => {
        event.stopPropagation();
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <DismissibleDialog onClose={onClose}
        className="image-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`${alt}全图`}
        onKeyDown={(event) => {
          if (event.key === "Tab") event.preventDefault();
        }}
      >
        <button autoFocus type="button" className="secondary-button" onClick={onClose}>
          关闭全图
        </button>
        <img src={src} alt={alt} />
      </DismissibleDialog>
    </div>,
    document.body,
  );
}

export function ZoomableImage({
  src,
  alt,
  className,
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="image-preview-trigger"
        aria-label={`查看全图：${alt}`}
        onClick={() => setOpen(true)}
      >
        <img loading="lazy" className={className} src={src} alt={alt} />
      </button>
      {open ? <ImagePreviewDialog src={src} alt={alt} onClose={close} /> : null}
    </>
  );
}

export function ImageZoomButton({ src, alt }: { src: string; alt: string }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  function close() {
    setOpen(false);
    trigger.current?.focus();
  }
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="image-zoom-button"
        aria-label={`查看全图：${alt}`}
        title="查看全图"
        onClick={(event) => {
          // 外层可能是 label 或选择卡片：放大不能顺带改变选择。
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
      >
        ⤢
      </button>
      {open ? <ImagePreviewDialog src={src} alt={alt} onClose={close} /> : null}
    </>
  );
}
