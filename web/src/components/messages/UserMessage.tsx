import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { UserMessageItem } from "../../types/message";
import { buildFileApiUrl } from "../../api/client";
import { HighlightText } from "./HighlightText";

const USER_MESSAGE_LINE_LIMIT = 4;

interface UserMessageProps {
  item: UserMessageItem;
  compact?: boolean;
}

export function UserMessage({ item, compact = false }: UserMessageProps): JSX.Element {
  const normalizedContent = useMemo(
    () =>
      item.content
        .split("\n")
        .filter((line) => line.trim().length > 0)
        .join("\n"),
    [item.content],
  );
  const hasText = normalizedContent.length > 0;
  const miniTextClass = compact ? "text-[11px]" : "text-xs";
  const textRef = useRef<HTMLParagraphElement>(null);
  const [showMore, setShowMore] = useState(false);
  const [canExpandText, setCanExpandText] = useState(false);
  const [collapsedTextMaxHeight, setCollapsedTextMaxHeight] = useState<number | null>(null);
  const [expandedImageIndex, setExpandedImageIndex] = useState<number | null>(null);

  useEffect(() => {
    const node = textRef.current;
    if (!hasText || !node) return;

    const updateMetrics = (): void => {
      const lineHeight = Number.parseFloat(window.getComputedStyle(node).lineHeight);
      if (!Number.isFinite(lineHeight) || lineHeight <= 0) {
        setCanExpandText(false);
        setCollapsedTextMaxHeight(null);
        return;
      }

      const maxHeight = lineHeight * USER_MESSAGE_LINE_LIMIT;
      setCollapsedTextMaxHeight(maxHeight);
      setCanExpandText(node.scrollHeight > maxHeight + 1);
    };

    const frameId = window.requestAnimationFrame(updateMetrics);

    const observer = new ResizeObserver(updateMetrics);
    observer.observe(node);
    return () => {
      window.cancelAnimationFrame(frameId);
      observer.disconnect();
    };
  }, [hasText, normalizedContent, compact]);

  const expandedImage =
    expandedImageIndex === null ? null : (item.images[expandedImageIndex] ?? null);
  const expandedImageSrc = expandedImage
    ? expandedImage.type === "image_file"
      ? buildFileApiUrl(expandedImage.file_path)
      : expandedImage.url
    : null;
  const expandedImageAlt = expandedImage
    ? expandedImage.type === "image_file"
      ? expandedImage.file_path
      : `image-${expandedImageIndex! + 1}`
    : null;

  useEffect(() => {
    if (!showMore && expandedImageIndex === null) return;

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      if (expandedImageIndex !== null) {
        setExpandedImageIndex(null);
        return;
      }
      setShowMore(false);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showMore, expandedImageIndex]);

  const renderImages = (): JSX.Element | null => {
    if (item.images.length === 0) return null;

    return (
      <div className="mb-2 space-y-2">
        {item.images.map((image, idx) => {
          const src = image.type === "image_file" ? buildFileApiUrl(image.file_path) : image.url;
          const alt = image.type === "image_file" ? image.file_path : `image-${idx + 1}`;
          return (
            <button
              key={`${image.type}-${idx}`}
              type="button"
              onClick={() => setExpandedImageIndex(idx)}
              className="block w-fit cursor-zoom-in rounded-md border-0 bg-transparent p-0"
            >
              <img
                src={src}
                alt={alt}
                className="block h-auto max-h-[180px] w-auto max-w-[260px] rounded-md border border-neutral-200/70 bg-white object-contain"
                loading="lazy"
              />
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <>
      <div className="rounded-[22px] bg-[rgb(229,243,255)] px-5 py-2.5 transition-colors hover:bg-[rgb(219,238,255)]">
        {renderImages()}
        {hasText ? (
          <div>
            <p
              ref={textRef}
              style={
                collapsedTextMaxHeight !== null
                  ? { maxHeight: `${collapsedTextMaxHeight}px`, overflow: "hidden" }
                  : undefined
              }
              className={`${compact ? "text-[13px]" : "text-[14px]"} m-0 whitespace-pre-wrap break-words leading-relaxed text-[rgb(0,40,77)]`}
            >
              <HighlightText>{normalizedContent}</HighlightText>
            </p>
            {canExpandText ? (
              <button
                type="button"
                onClick={() => setShowMore(true)}
                className={`mt-0.5 ${miniTextClass} cursor-pointer font-sans text-neutral-400 transition-colors hover:text-neutral-600`}
              >
                Show more
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {showMore && hasText
        ? createPortal(
            <div
              className="fixed inset-0 z-40 flex items-center justify-center bg-black/45 p-4"
              onClick={() => setShowMore(false)}
              role="dialog"
              aria-modal="true"
            >
              <div
                className="w-full max-w-3xl overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-2xl"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="max-h-[calc(100vh-8rem)] overflow-y-auto px-4 py-3">
                  {renderImages()}
                  <p
                    className={`${compact ? "text-[13px]" : "text-[14px]"} m-0 whitespace-pre-wrap break-words leading-relaxed text-[rgb(0,40,77)]`}
                  >
                    <HighlightText>{normalizedContent}</HighlightText>
                  </p>
                </div>
                <div className="border-t border-neutral-200/70 px-4 py-2.5">
                  <button
                    type="button"
                    onClick={() => setShowMore(false)}
                    className={`${miniTextClass} cursor-pointer font-sans text-neutral-400 transition-colors hover:text-neutral-600`}
                  >
                    Show less
                  </button>
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}

      {expandedImageSrc && expandedImageAlt
        ? createPortal(
            <div
              className="fixed inset-0 z-50 flex cursor-zoom-out items-center justify-center bg-black/75 p-4"
              onClick={() => setExpandedImageIndex(null)}
              role="dialog"
              aria-modal="true"
            >
              <img
                src={expandedImageSrc}
                alt={expandedImageAlt}
                onClick={(event) => event.stopPropagation()}
                className="block h-auto max-h-[calc(100vh-2rem)] w-auto max-w-[calc(100vw-2rem)] rounded-lg bg-white shadow-2xl"
              />
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
