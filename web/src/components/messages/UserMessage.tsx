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
    () => item.content.split("\n").filter((line) => line.trim().length > 0).join("\n"),
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
    setShowMore(false);
    setExpandedImageIndex(null);
  }, [item.id]);

  useEffect(() => {
    if (!hasText) {
      setCanExpandText(false);
      setCollapsedTextMaxHeight(null);
      return;
    }

    const node = textRef.current;
    if (!node) return;

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

    updateMetrics();

    const observer = new ResizeObserver(updateMetrics);
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasText, normalizedContent, compact]);

  const expandedImage = expandedImageIndex === null ? null : item.images[expandedImageIndex] ?? null;
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
              className="block w-fit rounded-md border-0 bg-transparent p-0 cursor-zoom-in"
            >
              <img
                src={src}
                alt={alt}
                className="block max-w-[260px] max-h-[180px] w-auto h-auto object-contain rounded-md border border-neutral-200/70 bg-white"
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
      <div className="rounded-lg border border-neutral-200/80 bg-neutral-50 px-3.5 py-2.5 transition-colors hover:bg-neutral-100 hover:border-neutral-300/60">
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
              className={`${compact ? "text-[14px]" : "text-[15px]"} leading-relaxed text-neutral-800 whitespace-pre-wrap break-words m-0`}
            >
              <HighlightText>{normalizedContent}</HighlightText>
            </p>
            {canExpandText ? (
              <button
                type="button"
                onClick={() => setShowMore(true)}
                className={`mt-0.5 ${miniTextClass} text-neutral-400 hover:text-neutral-600 cursor-pointer transition-colors font-sans`}
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
                    className={`${compact ? "text-[14px]" : "text-[15px]"} leading-relaxed text-neutral-800 whitespace-pre-wrap break-words m-0`}
                  >
                    <HighlightText>{normalizedContent}</HighlightText>
                  </p>
                </div>
                <div className="border-t border-neutral-200/70 px-4 py-2.5">
                  <button
                    type="button"
                    onClick={() => setShowMore(false)}
                    className={`${miniTextClass} text-neutral-400 hover:text-neutral-600 cursor-pointer transition-colors font-sans`}
                  >
                    Show less
                  </button>
                </div>
              </div>
            </div>
            ,
            document.body,
          )
        : null}

      {expandedImageSrc && expandedImageAlt
        ? createPortal(
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 cursor-zoom-out"
              onClick={() => setExpandedImageIndex(null)}
              role="dialog"
              aria-modal="true"
            >
              <img
                src={expandedImageSrc}
                alt={expandedImageAlt}
                onClick={(event) => event.stopPropagation()}
                className="block max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] w-auto h-auto rounded-lg bg-white shadow-2xl"
              />
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
