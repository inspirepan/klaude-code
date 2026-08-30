/**
 * The image render slot (UX spec D5).
 *
 * Upstream leaves image rendering to a host plugin and shows nothing when none
 * is registered. klaude resolves every image to a plain URL in the adapter
 * (`/api/web/file?...` for a recorded local path, the original URL otherwise)
 * and carries it in `ImageAttachmentRef.attachmentId`, so this slot is a thin
 * `<img>` gallery.
 */

import type { ReactNode } from 'react'
import type { MessageImagesOwnerProps } from '../contract/index.ts'
import css from './render-images.module.css'

/**
 * Render one group of record images.
 * @param owner - Images and their horizontal placement.
 * @returns The gallery, or null when the group is empty.
 */
export function renderImages({ images, align }: MessageImagesOwnerProps): ReactNode {
  if (images.length === 0) return null
  return (
    <div className={css.gallery} data-align={align}>
      {images.map((image, index) => {
        const source = 'attachment' in image ? image.attachment.attachmentId : image.preview.url
        const name = 'attachment' in image ? image.attachment.name : image.preview.name
        return (
          <a
            key={`${index}:${source}`}
            className={css.item}
            href={source}
            target="_blank"
            rel="noreferrer"
            title={name}
          >
            <img className={css.image} src={source} alt={name ?? ''} loading="lazy" />
          </a>
        )
      })}
    </div>
  )
}
