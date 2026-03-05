import type { UserMessageItem } from "../../types/message";
import { buildFileApiUrl } from "../../api/client";
import { HighlightText } from "./HighlightText";

interface UserMessageProps {
  item: UserMessageItem;
}

export function UserMessage({ item }: UserMessageProps): JSX.Element {
  const hasText = item.content.length > 0;

  return (
    <div className="rounded-xl bg-neutral-100 border border-neutral-200/60 px-4 py-3">
      {item.images.length > 0 ? (
        <div className="space-y-2 mb-2">
          {item.images.map((image, idx) => {
            const src = image.type === "image_file" ? buildFileApiUrl(image.file_path) : image.url;
            const alt = image.type === "image_file" ? image.file_path : `image-${idx + 1}`;
            return (
              <img
                key={`${image.type}-${idx}`}
                src={src}
                alt={alt}
                className="block max-w-full max-h-[360px] w-auto h-auto rounded-md border border-neutral-200/70 bg-white"
                loading="lazy"
              />
            );
          })}
        </div>
      ) : null}
      {hasText ? (
        <p className="text-[15px] leading-relaxed text-neutral-800 whitespace-pre-wrap break-words m-0">
          <HighlightText>{item.content}</HighlightText>
        </p>
      ) : null}
    </div>
  );
}
