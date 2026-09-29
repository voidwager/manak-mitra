import React, { useEffect, useState } from 'react';
import { ImageOff, Loader2 } from 'lucide-react';
import { api } from '../../services/api';

/**
 * Render an attachment's image.
 *
 * Fetched rather than pointed at with a plain `src`. Identity travels in the
 * `X-User-Id` header, and an `<img>` tag cannot set one - the browser issues
 * its own bare GET, which arrives unauthenticated and 401s. The result was a
 * broken image that renders as an empty black box against the dark theme,
 * which looks like the picture failed to upload rather than like an auth
 * problem.
 *
 * So the bytes come back through the normal client and are handed to the
 * browser as an object URL, which is revoked when the message scrolls away.
 */
export const AttachmentImage = ({ attachmentId, alt }) => {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;

    api
      .fetchAttachmentBlob(attachmentId)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      // Without this every rendered message leaks a blob for the life of
      // the tab.
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachmentId]);

  if (failed) {
    return (
      <div className="msg-att-image-missing">
        <ImageOff size={14} />
        <span>Image unavailable</span>
      </div>
    );
  }

  if (!url) {
    return (
      <div className="msg-att-image-missing">
        <Loader2 size={14} className="spin" />
        <span>Loading image…</span>
      </div>
    );
  }

  return <img className="msg-att-image" src={url} alt={alt} />;
};

export default AttachmentImage;
