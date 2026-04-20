/**
 * TAIA OCR Document Viewer
 * Handles document loading, rendering, translation progress, and synchronized scrolling
 */

class DocumentViewer {
    constructor() {
        this.docId = this.extractDocId();
        this.currentPage = 1;
        this.totalPages = 0;
        this.ocrProgress = 0;
        this.translationProgress = 0;
        this.zoomLevel = 15;
        this.pollingInterval = null;
        this.pages = [];
        this.isLoading = true;
        this.syncScrollEnabled = true;

        this.init();
    }

    /**
     * Extract document ID from URL
     */
    extractDocId() {
        const path = window.location.pathname;
        const match = path.match(/\/view\/([a-f0-9]+)/);
        return match ? match[1] : null;
    }

    /**
     * Initialize viewer
     */
    async init() {
        if (!this.docId) {
            this.showError('Invalid document ID');
            return;
        }

        this.showLoading();
        
        try {
            await this.loadDocument();
            this.hideLoading();
            this.setupImageLightbox();
            this.setupSyncScroll();
            this.startPolling();
        } catch (error) {
            this.hideLoading();
            this.showError(`Failed to load document: ${error.message}`);
            console.error('Initialization error:', error);
        }
    }

    /**
     * Load document metadata and initial pages
     */
    async loadDocument() {
        const status = await this.fetchStatus();
        this.totalPages = status.total_pages;
        this.ocrProgress = status.ocr_progress;
        this.translationProgress = status.translation_progress;
        
        this.updateProgress();
        document.getElementById('totalPagesDisplay').textContent = `of ${this.totalPages}`;
        document.getElementById('pageNumber').max = this.totalPages;
        
        await this.loadPages();
    }

    /**
     * Fetch document status
     */
    async fetchStatus() {
        const response = await fetch(`/view/${this.docId}/status`);
        if (!response.ok) throw new Error('Failed to fetch status');
        return await response.json();
    }

    /**
     * Load all pages
     */
    async loadPages() {
        const response = await fetch(`/view/${this.docId}/pages`);
        if (!response.ok) throw new Error('Failed to load pages');
        
        const data = await response.json();
        this.pages = data.pages;
        this.renderAllPages();
    }

    /**
     * Render all pages to DOM
     */
    renderAllPages() {
        const jaContent = document.getElementById('japaneseContent');
        const enContent = document.getElementById('englishContent');
        const originalContent = document.getElementById('originalContent');
        
        jaContent.innerHTML = '';
        enContent.innerHTML = '';
        originalContent.innerHTML = '';

        this.pages.forEach((page, index) => {
            // Original image panel
            const imgCard = this.createImageCard(index);
            originalContent.appendChild(imgCard);

            // Japanese panel
            const jaCard = this.createPageCard(page, 'ja', index);
            jaContent.appendChild(jaCard);

            // English panel
            const enCard = this.createPageCard(page, 'en', index);
            enContent.appendChild(enCard);
        });

        this.isLoading = false;
    }

    /**
     * Create page card element
     */
    createPageCard(page, lang, index) {
        const card = document.createElement('div');
        card.className = 'page-card';
        card.id = `${lang}-page-${index}`;
        card.dataset.pageNum = index + 1;

        const content = lang === 'ja' ? page.ja : page.en;
        const isDone = lang === 'ja' ? page.ocr_done : page.translation_done;

        card.innerHTML = `
            <div class="page-header">
                <span class="page-number">Page ${index + 1}</span>
                <div class="page-status">
                    <span class="status-indicator ${page.ocr_done ? 'ocr-done' : ''}">OCR</span>
                    ${lang === 'en' ? `<span class="status-indicator ${page.translation_done ? 'translation-done' : ''}">Translation</span>` : ''}
                </div>
            </div>
            <div class="page-content" style="font-size: ${this.zoomLevel}px; line-height: 1.6;" data-page-idx="${index}">
                ${this.renderContent(content, page, lang)}
            </div>
        `;

        return card;
    }

    /**
     * Create image card for original document.
     * The image is clickable and opens the lightbox for free-form pan/zoom.
     */
    createImageCard(pageNum) {
        const card = document.createElement('div');
        card.className    = 'page-card';
        card.id           = `image-page-${pageNum}`;
        card.dataset.pageNum = pageNum + 1;

        const imgSrc = `/view/${this.docId}/pages/${pageNum}/image`;
        const imgAlt = `Page ${pageNum + 1}`;

        card.innerHTML = `
            <div class="page-header">
                <span class="page-number">Page ${pageNum + 1}</span>
                <span style="font-size:0.72rem;color:#64748b;">🔍 click to enlarge</span>
            </div>
            <div class="page-content">
                <img src="${imgSrc}"
                     alt="${imgAlt}"
                     loading="lazy"
                     style="max-width:100%;height:auto;display:block;"
                     onerror="this.parentElement.innerHTML='<div class=\\'error-message\\'>Image not available</div>'">
            </div>
        `;

        // Wire click via addEventListener — keeps lightbox reference clean
        card.querySelector('img').addEventListener('click', () => {
            this.openLightbox(imgSrc, imgAlt);
        });

        return card;
    }

    /**
     * Render content based on state
     */
    renderContent(content, page, lang) {
        if (!content || content.trim() === '') {
            if (lang === 'en' && !page.translation_done) {
                return `<div class="translation-status translating">
                            <div class="loading-spinner"></div>
                            <span>Translating...</span>
                        </div>`;
            }
            return '<div class="error-message">No content available</div>';
        }

        // Escape HTML to prevent XSS
        return this.escapeHtml(content);
    }

    /**
     * Escape HTML special characters
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Update progress bar
     */
    updateProgress() {
        const ocrPercent = this.totalPages > 0 ? (this.ocrProgress / this.totalPages * 100) : 0;
        const transPercent = this.totalPages > 0 ? (this.translationProgress / this.totalPages * 100) : 0;

        const ocrBar = document.getElementById('ocrProgress');
        if (ocrBar) ocrBar.style.width = `${ocrPercent}%`;
        
        const transBar = document.getElementById('translationProgress');
        if (transBar) transBar.style.width = `${transPercent}%`;
        
        const ocrText = document.getElementById('ocrText');
        if (ocrText) ocrText.textContent = `OCR: ${this.ocrProgress}/${this.totalPages}`;
        
        const transText = document.getElementById('translationText');
        if (transText) transText.textContent = `Translation: ${this.translationProgress}/${this.totalPages}`;
    }

    /**
     * Setup synchronized scrolling — proportional within-page model.
     *
     * Problem with page-snap: at a page boundary, the "centred page" calculation
     * flickers between N and N+1 as the viewport straddles both cards, causing
     * the peer to snap back and forth.
     *
     * Problem with ratio-based: JA and EN have different content heights per
     * page, so the same scroll ratio lands on completely different pages.
     *
     * Solution — proportional within-page sync:
     *   1. Find which page card's bounds contain scrollTop (top of viewport).
     *   2. Compute progress = (scrollTop - cardTop) / cardHeight  → 0..1
     *   3. In the peer panel, write scrollTop = peerCardTop + progress * peerCardHeight
     *
     *   This means "30% through page 2 in JA" always maps to "30% through page 2
     *   in EN", regardless of how much content each page has. No snapping, no
     *   boundary oscillation.
     *
     * Image panel: still page-snap only (output-only, no listener).
     */
    setupSyncScroll() {
        const jaPanel  = document.getElementById('japaneseContent');
        const enPanel  = document.getElementById('englishContent');
        const imgPanel = document.getElementById('originalContent');

        if (!jaPanel || !enPanel) return;

        let activePanel   = null;
        let resetTimer    = null;
        let lastImagePage = -1;

        /**
         * Returns { pageIndex, progress } where progress is 0–1 through the card
         * that currently contains scrollTop. Uses scrollTop (top of viewport) as
         * the reference — not the centre — so the sync is anchored to what is
         * visually at the top of the panel, which is what the user reads first.
         */
        const getScrollState = (panel) => {
            const cards     = panel.querySelectorAll('.page-card');
            const scrollTop = panel.scrollTop;
            for (let i = 0; i < cards.length; i++) {
                const top    = cards[i].offsetTop;
                const height = cards[i].offsetHeight;
                if (scrollTop < top + height) {
                    const progress = height > 0
                        ? Math.max(0, Math.min(1, (scrollTop - top) / height))
                        : 0;
                    return { pageIndex: i, progress };
                }
            }
            return { pageIndex: Math.max(0, cards.length - 1), progress: 1 };
        };

        /**
         * Set panel scrollTop such that `progress` (0–1) through card `pageIndex`
         * sits at the top of the visible area.
         */
        const applyScrollState = (panel, pageIndex, progress) => {
            const cards = panel.querySelectorAll('.page-card');
            const card  = cards[pageIndex];
            if (!card) return;
            panel.scrollTop = card.offsetTop + progress * card.offsetHeight;
        };

        const handleScroll = (sourcePanel) => {
            if (!this.syncScrollEnabled) return;
            if (activePanel !== null && activePanel !== sourcePanel) return;

            activePanel = sourcePanel;

            const { pageIndex, progress } = getScrollState(sourcePanel);

            // Tier 1: proportional within-page sync for the peer text panel.
            const peer = sourcePanel === jaPanel ? enPanel : jaPanel;
            applyScrollState(peer, pageIndex, progress);

            // Tier 2: snap image panel to matching page (output-only).
            if (imgPanel && pageIndex !== lastImagePage) {
                const cards = imgPanel.querySelectorAll('.page-card');
                if (cards[pageIndex]) {
                    imgPanel.scrollTop = cards[pageIndex].offsetTop;
                    lastImagePage = pageIndex;
                }
            }

            if (resetTimer) clearTimeout(resetTimer);
            resetTimer = setTimeout(() => {
                activePanel = null;
                resetTimer  = null;
            }, 50);
        };

        jaPanel.addEventListener('scroll', () => handleScroll(jaPanel), { passive: true });
        enPanel.addEventListener('scroll', () => handleScroll(enPanel), { passive: true });
        // imgPanel has no scroll listener — it is output-only.
    }

    /**
     * Toggle sync scroll
     */
    toggleSyncScroll(enabled) {
        this.syncScrollEnabled = enabled;
    }

    // ─── Image Lightbox ───────────────────────────────────────────────────────
    //
    // A free-form pan + zoom viewer for the original document images.
    //
    // Architecture:
    //   - A full-screen overlay (.lb-overlay) contains a stage div (.lb-stage)
    //     that fills the entire viewport and catches all pointer/wheel events.
    //   - The image sits inside the stage with transform-origin: 0 0. Its
    //     position is controlled entirely by a single CSS transform:
    //       translate(panX px, panY px) scale(scale)
    //     This keeps the math simple and avoids fighting the browser layout.
    //   - Cursor-centred wheel zoom: the image point under the cursor stays
    //     fixed as scale changes. Formula:
    //       newPanX = cursorX + (panX - cursorX) * (newScale / oldScale)
    //   - Drag pan: on mousedown record startXY and origin panXY; on mousemove
    //     write panX/Y = originX/Y + (currentXY - startXY). Released on mouseup
    //     anywhere on window so fast drags don't "lose" the cursor.

    injectLightboxStyles() {
        if (document.getElementById('lightbox-styles')) return;
        const style = document.createElement('style');
        style.id = 'lightbox-styles';
        style.textContent = `
            .lb-overlay {
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.92);
                z-index: 9000;
                animation: lb-fade-in 0.15s ease;
            }
            .lb-overlay.hidden { display: none; }
            @keyframes lb-fade-in { from { opacity:0 } to { opacity:1 } }

            /* Stage fills the entire overlay; handles all input */
            .lb-stage {
                position: absolute;
                inset: 0;
                overflow: hidden;
                cursor: grab;
            }
            .lb-stage.dragging { cursor: grabbing; }

            /* Image is absolutely positioned; all movement via transform */
            .lb-stage img {
                position: absolute;
                top: 0;
                left: 0;
                transform-origin: 0 0;
                user-select: none;
                -webkit-user-drag: none;
                pointer-events: none; /* stage handles events, not the image */
                max-width: none;
            }

            /* Toolbar floats above the stage */
            .lb-toolbar {
                position: absolute;
                top: 1rem;
                right: 1rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
                z-index: 9001;
                background: rgba(15,23,42,0.88);
                padding: 0.5rem 0.75rem;
                border-radius: 0.5rem;
                border: 1px solid #475569;
                pointer-events: all;
            }
            .lb-zoom-label {
                font-family: 'Fira Code', monospace;
                font-size: 0.8rem;
                color: #94a3b8;
                min-width: 52px;
                text-align: center;
            }
            .lb-btn {
                width: 2rem;
                height: 2rem;
                border: 1px solid #475569;
                background: #334155;
                color: #f1f5f9;
                border-radius: 0.375rem;
                cursor: pointer;
                font-size: 1.1rem;
                line-height: 1;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: background 0.15s;
                flex-shrink: 0;
            }
            .lb-btn:hover { background: #475569; }
            .lb-btn-close {
                background: #7f1d1d;
                border-color: #ef4444;
                margin-left: 0.25rem;
            }
            .lb-btn-close:hover { background: #991b1b; }

            /* Hint bar at the bottom */
            .lb-hint {
                position: absolute;
                bottom: 1rem;
                left: 50%;
                transform: translateX(-50%);
                font-size: 0.72rem;
                color: #475569;
                pointer-events: none;
                white-space: nowrap;
                letter-spacing: 0.03em;
            }

            /* Thumbnail images in original panel become clickable */
            #originalContent .page-content img {
                cursor: zoom-in;
                transition: opacity 0.15s;
            }
            #originalContent .page-content img:hover { opacity: 0.82; }
        `;
        document.head.appendChild(style);
    }

    setupImageLightbox() {
        this.injectLightboxStyles();

        const overlay = document.createElement('div');
        overlay.id        = 'imageLightbox';
        overlay.className = 'lb-overlay hidden';
        overlay.innerHTML = `
            <div class="lb-stage" id="lbStage">
                <img id="lbImage" src="" alt="" draggable="false">
            </div>
            <div class="lb-toolbar">
                <button class="lb-btn" id="lbZoomOut" title="Zoom out">−</button>
                <span class="lb-zoom-label" id="lbZoomLabel">100%</span>
                <button class="lb-btn" id="lbZoomIn"  title="Zoom in">+</button>
                <button class="lb-btn" id="lbReset"   title="Fit to screen (double-click)">⊡</button>
                <button class="lb-btn lb-btn-close" id="lbClose" title="Close  Esc">✕</button>
            </div>
            <div class="lb-hint">Scroll to zoom &nbsp;·&nbsp; Drag to pan &nbsp;·&nbsp; Double-click to fit &nbsp;·&nbsp; Esc to close</div>
        `;
        document.body.appendChild(overlay);

        const lb = {
            overlay,
            stage   : overlay.querySelector('#lbStage'),
            img     : overlay.querySelector('#lbImage'),
            label   : overlay.querySelector('#lbZoomLabel'),
            panX    : 0,
            panY    : 0,
            scale   : 1,
            MIN     : 0.05,
            MAX     : 12,
            STEP    : 0.15,  // factor per wheel tick / button press
            drag    : { active: false, startX: 0, startY: 0, originX: 0, originY: 0 },
        };
        this.lb = lb;

        // ── Core transform writer ─────────────────────────────────────────────
        const applyTransform = (animate = false) => {
            lb.img.style.transition = animate ? 'transform 0.18s ease' : 'none';
            lb.img.style.transform  = `translate(${lb.panX}px,${lb.panY}px) scale(${lb.scale})`;
            lb.label.textContent    = `${Math.round(lb.scale * 100)}%`;
        };

        // ── Fit image inside viewport (initial view + reset) ──────────────────
        const fitView = (animate = false) => {
            const sw = lb.stage.clientWidth;
            const sh = lb.stage.clientHeight;
            const iw = lb.img.naturalWidth  || sw;
            const ih = lb.img.naturalHeight || sh;
            lb.scale = Math.min(sw / iw, sh / ih) * 0.92;   // 8% breathing room
            lb.panX  = (sw - iw * lb.scale) / 2;
            lb.panY  = (sh - ih * lb.scale) / 2;
            applyTransform(animate);
        };
        lb.fitView = fitView;

        // ── Cursor-centred zoom ───────────────────────────────────────────────
        // The image pixel directly under (clientX, clientY) stays fixed.
        const zoomAt = (clientX, clientY, factor) => {
            const rect     = lb.stage.getBoundingClientRect();
            const cx       = clientX - rect.left;   // cursor in stage space
            const cy       = clientY - rect.top;
            const newScale = Math.min(lb.MAX, Math.max(lb.MIN, lb.scale * factor));
            const r        = newScale / lb.scale;
            lb.panX        = cx + (lb.panX - cx) * r;
            lb.panY        = cy + (lb.panY - cy) * r;
            lb.scale       = newScale;
            applyTransform();
        };

        // ── Mouse wheel zoom ──────────────────────────────────────────────────
        lb.stage.addEventListener('wheel', (e) => {
            e.preventDefault();
            const factor = e.deltaY < 0 ? 1 + lb.STEP : 1 / (1 + lb.STEP);
            zoomAt(e.clientX, e.clientY, factor);
        }, { passive: false });

        // ── Drag to pan ───────────────────────────────────────────────────────
        lb.stage.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            lb.drag.active  = true;
            lb.drag.startX  = e.clientX;
            lb.drag.startY  = e.clientY;
            lb.drag.originX = lb.panX;
            lb.drag.originY = lb.panY;
            lb.stage.classList.add('dragging');
        });

        // Listen on window so fast movement can't "escape" the stage element
        window.addEventListener('mousemove', (e) => {
            if (!lb.drag.active) return;
            lb.panX = lb.drag.originX + (e.clientX - lb.drag.startX);
            lb.panY = lb.drag.originY + (e.clientY - lb.drag.startY);
            applyTransform();
        });

        window.addEventListener('mouseup', () => {
            if (!lb.drag.active) return;
            lb.drag.active = false;
            lb.stage.classList.remove('dragging');
        });

        // ── Touch: single-finger pan, two-finger pinch-zoom ───────────────────
        let lastPinchDist = null;

        lb.stage.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                lb.drag.active  = true;
                lb.drag.startX  = e.touches[0].clientX;
                lb.drag.startY  = e.touches[0].clientY;
                lb.drag.originX = lb.panX;
                lb.drag.originY = lb.panY;
                lastPinchDist = null;
            } else if (e.touches.length === 2) {
                lb.drag.active = false;
                lastPinchDist  = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
            }
        }, { passive: true });

        lb.stage.addEventListener('touchmove', (e) => {
            e.preventDefault();
            if (e.touches.length === 1 && lb.drag.active) {
                lb.panX = lb.drag.originX + (e.touches[0].clientX - lb.drag.startX);
                lb.panY = lb.drag.originY + (e.touches[0].clientY - lb.drag.startY);
                applyTransform();
            } else if (e.touches.length === 2 && lastPinchDist !== null) {
                const dist = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
                const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
                zoomAt(midX, midY, dist / lastPinchDist);
                lastPinchDist = dist;
            }
        }, { passive: false });

        lb.stage.addEventListener('touchend', () => {
            lb.drag.active = false;
            lastPinchDist  = null;
        }, { passive: true });

        // ── Toolbar buttons ───────────────────────────────────────────────────
        const centreZoom = (factor) => {
            const r = lb.stage.getBoundingClientRect();
            zoomAt(r.left + r.width / 2, r.top + r.height / 2, factor);
        };

        overlay.querySelector('#lbZoomIn').addEventListener('click',  () => centreZoom(1 + lb.STEP));
        overlay.querySelector('#lbZoomOut').addEventListener('click', () => centreZoom(1 / (1 + lb.STEP)));
        overlay.querySelector('#lbReset').addEventListener('click',   () => fitView(true));
        overlay.querySelector('#lbClose').addEventListener('click',   () => this.closeLightbox());

        // Double-click the stage to reset/fit
        lb.stage.addEventListener('dblclick', () => fitView(true));

        // ── ESC handler (stored so it can be removed on close) ────────────────
        this._lbKeyHandler = (e) => {
            if (e.key === 'Escape') this.closeLightbox();
        };
    }

    /**
     * Open the lightbox for the given image URL.
     * Waits for the image to load before calling fitView so dimensions are known.
     */
    openLightbox(src, alt = '') {
        if (!this.lb) return;
        const lb = this.lb;

        lb.overlay.classList.remove('hidden');
        document.addEventListener('keydown', this._lbKeyHandler);
        document.body.style.overflow = 'hidden';

        // Reset before loading so we never see stale content
        lb.img.style.transition = 'none';
        lb.img.style.transform  = 'translate(0,0) scale(1)';
        lb.img.src              = '';

        lb.img.onload = () => lb.fitView(false);
        lb.img.src    = src;
        lb.img.alt    = alt;
    }

    /**
     * Close the lightbox and release all resources.
     */
    closeLightbox() {
        if (!this.lb) return;
        const lb = this.lb;
        lb.overlay.classList.add('hidden');
        lb.img.src         = '';
        lb.img.onload      = null;
        lb.drag.active     = false;
        lb.stage.classList.remove('dragging');
        document.removeEventListener('keydown', this._lbKeyHandler);
        document.body.style.overflow = '';
    }

    /**
     * Jump to specific page.
     *
     * `scrollIntoView` was the original approach but it fires a native scroll
     * event on each panel independently and simultaneously. When three panels
     * each emit a scroll event at once, the sync scroll handler treats each one
     * as a new "source", producing a three-way conflict and visible jitter.
     *
     * Fix: write `scrollTop` directly on the panel containers. This lets sync
     * scroll remain idle (no scroll event is fired until the user manually
     * scrolls), and the navigation lands cleanly.
     */
    jumpToPage(pageNum) {
        const page = parseInt(pageNum, 10);
        if (isNaN(page) || page < 1 || page > this.totalPages) {
            this.showError(`Invalid page number: ${pageNum}`);
            return;
        }

        this.currentPage = page;
        const index = page - 1;

        const targets = [
            { contentId: 'originalContent', prefix: 'image' },
            { contentId: 'japaneseContent', prefix: 'ja'    },
            { contentId: 'englishContent',  prefix: 'en'    },
        ];

        targets.forEach(({ contentId, prefix }) => {
            const panel    = document.getElementById(contentId);
            const pageCard = document.getElementById(`${prefix}-page-${index}`);
            if (!panel || !pageCard) return;
            // offsetTop is relative to the offsetParent (the panel itself here),
            // so this positions the card flush with the top of the scroll container.
            panel.scrollTop = pageCard.offsetTop;
        });
    }

    /**
     * Zoom controls - increment by 1
     */
    zoomIn() {
        this.zoomLevel = Math.min(this.zoomLevel + 1, 24);
        this.updateZoom();
    }

    zoomOut() {
        this.zoomLevel = Math.max(this.zoomLevel - 1, 10);
        this.updateZoom();
    }

    /**
     * Zoom controls - increment by 1
     * FIX: Preserves scroll position during reflow and prevents sync hijacking
     */
    updateZoom() {
        // 1. Temporarily disable sync to prevent auto-scroll during layout shift
        const wasSyncEnabled = this.syncScrollEnabled;
        this.syncScrollEnabled = false;

        // 2. Remember which page we're currently viewing
        const jaPanel = document.getElementById('japaneseContent');
        let targetIdx = 0;
        if (jaPanel) {
            const cards = jaPanel.querySelectorAll('.page-card');
            const viewCenter = jaPanel.scrollTop + jaPanel.clientHeight / 2;
            for (let i = 0; i < cards.length; i++) {
                if (cards[i].offsetTop <= viewCenter && cards[i].offsetTop + cards[i].offsetHeight >= viewCenter) {
                    targetIdx = i;
                    break;
                }
            }
        }

        // 3. Apply zoom
        document.getElementById('zoomLevel').textContent = `${this.zoomLevel}px`;
        document.querySelectorAll('.page-content').forEach(el => {
            el.style.fontSize = `${this.zoomLevel}px`;
        });

        // 4. Restore position after browser reflow completes
        requestAnimationFrame(() => {
            ['japaneseContent', 'englishContent', 'originalContent'].forEach(id => {
                const panel = document.getElementById(id);
                const card = panel?.querySelector(`.page-card:nth-child(${targetIdx + 1})`);
                if (panel && card) panel.scrollTop = card.offsetTop;
            });
            this.syncScrollEnabled = wasSyncEnabled;
        });
    }

    /**
     * Copy page text to clipboard
     */
    async copyPageText(lang) {
        const pageCard = document.querySelector(`#${lang === 'ja' ? 'ja' : 'en'}-page-${this.currentPage - 1} .page-content`);
        if (!pageCard) {
            this.showError(`No content on page ${this.currentPage}`);
            return;
        }

        const text = pageCard.innerText;
        if (!text || text === 'Translating...') {
            this.showError('No text available to copy');
            return;
        }

        try {
            await navigator.clipboard.writeText(text);
            
            // Visual feedback
            const btn = document.querySelector(`.btn-copy[onclick="viewer.copyPageText('${lang}')"]`);
            if (btn) {
                const originalText = btn.textContent;
                btn.textContent = '✓';
                btn.classList.add('copied');
                
                setTimeout(() => {
                    btn.textContent = originalText;
                    btn.classList.remove('copied');
                }, 1500);
            }
            
            this.showToast('success', `Copied page ${this.currentPage}`);
        } catch (error) {
            this.showError('Failed to copy to clipboard');
            console.error('Copy error:', error);
        }
    }

    /**
     * Start polling for updates
     */
    startPolling() {
        this.pollingInterval = setInterval(async () => {
            try {
                const status = await this.fetchStatus();

                // Check if progress changed
                if (status.ocr_progress !== this.ocrProgress ||
                    status.translation_progress !== this.translationProgress) {

                    // Capture previous translation count BEFORE overwriting —
                    // the old code updated this.translationProgress first and then
                    // compared status.translation_progress > this.translationProgress,
                    // which was always false (they were equal), so pages never reloaded.
                    const prevTranslationProgress = this.translationProgress;

                    this.ocrProgress = status.ocr_progress;
                    this.translationProgress = status.translation_progress;
                    this.updateProgress();

                    if (this.translationProgress > prevTranslationProgress) {
                        await this.loadPages();
                    }
                }

                // Stop polling if complete
                if (status.status === 'complete') {
                    this.stopPolling();
                }
            } catch (error) {
                console.error('Polling error:', error);
            }
        }, 3000); // Poll every 3 seconds
    }

    /**
     * Stop polling
     */
    stopPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }

    /**
     * Show loading overlay
     */
    showLoading() {
        document.getElementById('loadingOverlay').classList.remove('hidden');
    }

    /**
     * Hide loading overlay
     */
    hideLoading() {
        document.getElementById('loadingOverlay').classList.add('hidden');
    }

    /**
     * Show error toast
     */
    showError(message) {
        const toast = document.getElementById('errorToast');
        document.getElementById('errorMessage').textContent = message;
        toast.classList.remove('hidden');
        
        setTimeout(() => this.hideError(), 5000);
    }

    /**
     * Show success toast
     */
    showToast(type, message) {
        const toast = document.getElementById('errorToast');
        toast.className = `toast toast-${type}`;
        document.getElementById('errorMessage').textContent = message;
        toast.classList.remove('hidden');
        
        setTimeout(() => this.hideError(), 3000);
    }

    /**
     * Hide error toast
     */
    hideError() {
        document.getElementById('errorToast').classList.add('hidden');
    }

    /**
     * Cleanup on page unload
     */
    destroy() {
        this.stopPolling();
    }
}

// Initialize viewer when DOM is ready
let viewer;
document.addEventListener('DOMContentLoaded', () => {
    viewer = new DocumentViewer();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (viewer) viewer.destroy();
});