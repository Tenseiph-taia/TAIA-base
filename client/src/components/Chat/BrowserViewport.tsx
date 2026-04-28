import { useState } from 'react';
import styles from './BrowserViewport.module.css';

interface Props {
  url: string;
  viewportWidth?: number;
  viewportHeight?: number;
}

export default function BrowserViewport({ url, viewportWidth = 1280, viewportHeight = 900 }: Props) {
  const [error, setError] = useState(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null);

  const handleImageClick = (e: React.MouseEvent<HTMLImageElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const scaleX = viewportWidth / rect.width;
    const scaleY = viewportHeight / rect.height;
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);
    const text = `Click at (${x}, ${y})`;

    setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, text });
    setTimeout(() => setTooltip(null), 1200);

    window.dispatchEvent(new CustomEvent('browser-coordinate-click', { detail: { text } }));
  };

  if (error) {
    return (
      <div className={styles.errorContainer}>
        Browser session inactive
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Live badge */}
      <div className={styles.liveBadge}>
        <span className={styles.liveIndicator} />
        LIVE
      </div>

      {/* Pop-out button */}
      <button
        onClick={() => window.open(url, '_blank', 'width=1280,height=900')}
        className={styles.popOutButton}
      >
        ↗ Pop out
      </button>

      {/* MJPEG stream — browser renders multipart/x-mixed-replace natively */}
      <img
        src={url}
        alt="Live browser viewport"
        onClick={handleImageClick}
        onError={() => setError(true)}
        className={styles.browserImage}
      />

      {tooltip && (
        <div 
          className={styles.tooltip}
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 28,
          }}
        >
          {tooltip.text}
        </div>
      )}
    </div>
  );
}
