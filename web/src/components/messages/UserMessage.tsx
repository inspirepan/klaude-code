import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { UserMessageItem } from "../../types/message";
import { buildFileApiUrl } from "../../api/client";
import { HighlightText } from "./HighlightText";

const USER_MESSAGE_LINE_LIMIT = 4;
const MENTION_PATTERN = /(@[\w./-]+)/;

function ContentWithMentions({ children }: { children: string }): JSX.Element {
  const parts = children.split(MENTION_PATTERN);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("@") && MENTION_PATTERN.test(part) ? (
          <span key={i} className="text-blue-500">
            <HighlightText>{part}</HighlightText>
          </span>
        ) : (
          <HighlightText key={i}>{part}</HighlightText>
        ),
      )}
    </>
  );
}

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
  const miniTextClass = "text-xs leading-none";
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
      const hasVerticalOverflow = node.scrollHeight > maxHeight + 1;
      setCanExpandText(hasVerticalOverflow);
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
      ? buildFileApiUrl(expandedImage.file_path, item.sessionId)
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
          const src =
            image.type === "image_file"
              ? buildFileApiUrl(image.file_path, item.sessionId)
              : image.url;
          const alt = image.type === "image_file" ? image.file_path : `image-${idx + 1}`;
          return (
            <button
              key={`${image.type}-${idx}`}
              type="button"
              onClick={() => setExpandedImageIndex(idx)}
              className="block w-fit max-w-full cursor-zoom-in rounded-md border-0 bg-transparent p-0"
            >
              <img
                src={src}
                alt={alt}
                className="block h-auto max-h-[180px] w-auto max-w-[min(260px,100%)] rounded-md border border-neutral-200/70 bg-white object-contain"
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
      <div className="hover:bg-slate-150 dark:hover:bg-slate-750 ml-auto w-fit max-w-[50%] rounded-2xl border border-slate-200/50 bg-slate-100 px-2.5 py-1.5 transition-colors dark:border-slate-700/50 dark:bg-slate-800">
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
              className="m-0 whitespace-pre-wrap break-words text-base leading-relaxed text-foreground"
            >
              <ContentWithMentions>{normalizedContent}</ContentWithMentions>
            </p>
            {canExpandText ? (
              <button
                type="button"
                onClick={() => setShowMore(true)}
                className={`mt-0 ${miniTextClass} cursor-pointer py-0 font-sans text-neutral-500 transition-colors hover:text-neutral-700`}
              >
                Show more
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {item.timestamp !== null ? (
        <div className="mr-1 mt-1 text-right text-xs text-neutral-500">
          {new Date(item.timestamp * 1000).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </div>
      ) : null}

      {showMore && hasText
        ? createPortal(
            <div
              className="fixed inset-0 z-40 flex items-center justify-center p-4"
              role="dialog"
              aria-modal="true"
            >
              <div
                className="bg-white/72 absolute inset-0 backdrop-blur-[3px]"
                onClick={() => setShowMore(false)}
              />
              <div
                className="relative w-full max-w-3xl overflow-hidden rounded-2xl border border-slate-200/50 bg-slate-100 dark:border-slate-700/50 dark:bg-slate-800"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="max-h-[calc(100vh-8rem)] overflow-y-auto px-4 py-3">
                  {renderImages()}
                  <p className="m-0 whitespace-pre-wrap break-words text-base leading-relaxed text-foreground">
                    <ContentWithMentions>{normalizedContent}</ContentWithMentions>
                  </p>
                </div>
                <div className="border-t border-slate-200/50 px-4 py-2.5 dark:border-slate-700/50">
                  <button
                    type="button"
                    onClick={() => setShowMore(false)}
                    className={`${miniTextClass} cursor-pointer py-0 font-sans text-neutral-500 transition-colors hover:text-neutral-700`}
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
