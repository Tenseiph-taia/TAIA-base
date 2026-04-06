import React, { useState } from 'react';
import { Download, CircleCheckBig } from 'lucide-react';
import type { Artifact } from '~/common';
import { Button } from '@librechat/client';
import useArtifactProps from '~/hooks/Artifacts/useArtifactProps';
import { useCodeState } from '~/Providers/EditorContext';
import { useLocalize } from '~/hooks';

const DownloadArtifact = ({ artifact }: { artifact: Artifact }) => {
  const localize = useLocalize();
  const { currentCode } = useCodeState();
  const [isDownloaded, setIsDownloaded] = useState(false);
  const { fileKey: fileName } = useArtifactProps({ artifact });

  const handleDownload = () => {
    try {
      const content = currentCode ?? artifact.content ?? '';
      if (!content) {
        return;
      }

      const isHTML = artifact.type === 'application/vnd.ant.html' ||
        artifact.type === 'text/html' ||
        content.trimStart().toLowerCase().startsWith('<!doctype html') ||
        content.trimStart().toLowerCase().startsWith('<html');

      if (isHTML) {
        // Open in new window and trigger print-to-PDF
        const printWindow = window.open('', '_blank');
        if (!printWindow) {
          return;
        }
        const printCSS = `
          <style>
            @media print {
              @page { margin: 20mm; size: A4; }
              body { font-family: Arial, sans-serif; }
              button { display: none !important; }
              table { page-break-inside: avoid; }
              h2 { page-break-after: avoid; }
            }
          </style>
        `;
        // Inject print CSS into the HTML content
        const contentWithPrintCSS = content.includes('</head>')
          ? content.replace('</head>', `${printCSS}</head>`)
          : `${printCSS}${content}`;

        printWindow.document.write(contentWithPrintCSS);
        printWindow.document.close();
        printWindow.focus();
        setTimeout(() => {
          printWindow.print();
        }, 500);

        setIsDownloaded(true);
        setTimeout(() => setIsDownloaded(false), 3000);
        return;
      }

      // Default download for non-HTML artifacts
      const blob = new Blob([content], { type: 'text/plain' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      setIsDownloaded(true);
      setTimeout(() => setIsDownloaded(false), 3000);
    } catch (error) {
      console.error('Download failed:', error);
    }
  };

  return (
    <Button
      size="icon"
      variant="ghost"
      className="h-9 w-9"
      onClick={handleDownload}
      aria-label={localize('com_ui_download_artifact')}
      title={
        artifact.type === 'application/vnd.ant.html'
          ? 'Download as PDF'
          : localize('com_ui_download_artifact')
      }
    >
      {isDownloaded ? (
        <CircleCheckBig size={16} aria-hidden="true" />
      ) : (
        <Download size={16} aria-hidden="true" />
      )}
    </Button>
  );
};

export default DownloadArtifact;