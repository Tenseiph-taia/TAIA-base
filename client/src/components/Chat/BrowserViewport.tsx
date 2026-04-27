import { useState } from 'react';

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
      <div style={{
        width: '100%', height: '60px', background: '#1a1a1a', borderRadius: '8px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#ff5555', fontSize: '12px', border: '1px solid #333',
      }}>
        Browser session inactive
      </div>
    );
  }

  return (
    <div style={{
      position: 'relative', width: '100%', borderRadius: '8px',
      overflow: 'hidden', border: '1px solid #444',
    }}>
      {/* Live badge */}
      <div style={{
        position: 'absolute', top: '8px', left: '8px', zIndex: 2,
        background: 'rgba(0,0,0,0.75)', color: '#fff', padding: '2px 8px',
        borderRadius: '4px', fontSize: '11px', display: 'flex',
        alignItems: 'center', gap: '6px', userSelect: 'none',
      }}>
        <span style={{
          width: '6px', height: '6px', background: '#ff3366',
          borderRadius: '50%', display: 'inline-block',
          animation: 'pulse 1.4s ease-in-out infinite',
        }} />
        LIVE
      </div>

      {/* Pop-out button */}
      <button
        onClick={() => window.open(url, '_blank', 'width=1280,height=900')}
        style={{
          position: 'absolute', top: '8px', right: '8px', zIndex: 2,
          background: 'rgba(0,0,0,0.75)', color: '#fff', border: 'none',
          padding: '2px 8px', borderRadius: '4px', fontSize: '11px',
          cursor: 'pointer',
        }}
      >
        ↗ Pop out
      </button>

      {/* MJPEG stream — browser renders multipart/x-mixed-replace natively */}
      <img
        src={url}
        alt="Live browser viewport"
        onClick={handleImageClick}
        onError={() => setError(true)}
        style={{ width: '100%', display: 'block', background: '#000', cursor: 'crosshair' }}
      />

      {tooltip && (
        <div style={{
          position: 'absolute',
          left: tooltip.x + 12,
          top: tooltip.y - 28,
          zIndex: 3,
          background: 'rgba(0,0,0,0.85)',
          color: '#fff',
          padding: '4px 10px',
          borderRadius: '4px',
          fontSize: '12px',
          pointerEvents: 'none',
          whiteSpace: 'nowrap',
        }}>
          {tooltip.text}
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
