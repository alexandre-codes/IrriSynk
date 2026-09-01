(function () {
  'use strict';

  const DRAG_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24">
    <path fill="currentColor"
      d="M9 3h2v2H9V3m4 0h2v2h-2V3M9 7h2v2H9V7m4 0h2v2h-2V7
         M9 11h2v2H9v-2m4 0h2v2h-2v-2M9 15h2v2H9v-2m4 0h2v2h-2v-2
         M9 19h2v2H9v-2m4 0h2v2h-2v-2z"/>
  </svg>`;

  const REMOVE_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24">
    <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
  </svg>`;

  const STYLES = `
    :host { display: block; }
    .card {
      background: var(--card-background-color, white);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow,
        0 2px 2px 0 rgba(0,0,0,.14),
        0 1px 5px 0 rgba(0,0,0,.12),
        0 3px 1px -2px rgba(0,0,0,.2));
      overflow: hidden;
    }
    .card-header {
      padding: 16px 16px 8px;
      font-size: 1.1rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    ul {
      list-style: none;
      margin: 0;
      padding: 4px 0 8px;
    }
    li {
      display: flex;
      align-items: center;
      padding: 12px 16px;
      cursor: grab;
      touch-action: none;
      border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
      user-select: none;
      -webkit-user-select: none;
      transition: background-color 0.1s;
    }
    li:last-child { border-bottom: none; }
    li.dragging { opacity: 0.3; }
    li.over { background: rgba(var(--rgb-primary-color, 33, 150, 243), 0.12); }
    .drag-icon { margin-right: 14px; color: var(--secondary-text-color); display: flex; flex-shrink: 0; }
    .name { flex: 1; font-size: 1rem; color: var(--primary-text-color); }
    .remove-btn {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--error-color, #B00020);
      display: flex;
      align-items: center;
      padding: 4px;
      border-radius: 50%;
      opacity: 0.7;
      transition: opacity 0.15s, background 0.15s;
      flex-shrink: 0;
      touch-action: auto;
    }
    .remove-btn:hover { opacity: 1; background: rgba(var(--rgb-error-color, 176, 0, 32), 0.1); }
    .remove-btn * { pointer-events: none; }
  `;

  class IrriSynkZoneOrderCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass = null;
      this._config = {};
      this._dragIdx = null;
    }

    set hass(hass) { this._hass = hass; }

    setConfig(config) {
      this._config = config;
      this._render();
    }

    _isCascadeMode() {
      return !!this._config.cascade_id;
    }

    _render() {
      const zoneIds = this._config.zone_ids || [];
      const zoneNames = this._config.zone_names || {};
      const title = this._config.title || '';
      const cascadeMode = this._isCascadeMode();

      const items = zoneIds.map((id, i) => {
        const removeBtn = cascadeMode
          ? `<button class="remove-btn" data-remove="${id}" title="Retirer" aria-label="Retirer">${REMOVE_ICON}</button>`
          : '';
        return `<li data-idx="${i}" data-id="${id}">
          <span class="drag-icon">${DRAG_ICON}</span>
          <span class="name">${zoneNames[id] || id}</span>
          ${removeBtn}
        </li>`;
      }).join('');

      this.shadowRoot.innerHTML = `
        <style>${STYLES}</style>
        <div class="card">
          ${title ? `<div class="card-header">${title}</div>` : ''}
          <ul id="list">${items}</ul>
        </div>`;

      this._attachDragEvents();
    }

    _attachDragEvents() {
      const ul = this.shadowRoot.getElementById('list');
      if (!ul) return;

      ul.addEventListener('pointerdown', e => {
        // Handle × remove button — call service immediately on press, skip drag
        const removeBtn = e.target.closest('.remove-btn');
        if (removeBtn) {
          const zoneId = removeBtn.dataset.remove;
          const cascadeId = this._config.cascade_id;
          if (zoneId && cascadeId && this._hass) {
            this._hass.callService('irrisynk', 'remove_zone_from_cascade', {
              cascade_id: cascadeId,
              zone_id: zoneId,
            });
          }
          return;
        }
        const li = e.target.closest('li');
        if (!li) return;
        li.setPointerCapture(e.pointerId);
        this._dragIdx = +li.dataset.idx;
        li.classList.add('dragging');
      });

      ul.addEventListener('pointermove', e => {
        if (this._dragIdx === null) return;
        const lis = [...this.shadowRoot.querySelectorAll('li')];
        lis.forEach(l => l.classList.remove('over'));
        const over = lis.find(l => {
          const r = l.getBoundingClientRect();
          return e.clientY >= r.top && e.clientY <= r.bottom && +l.dataset.idx !== this._dragIdx;
        });
        if (over) over.classList.add('over');
      });

      ul.addEventListener('pointerup', e => {
        if (this._dragIdx === null) return;
        if (e.target.closest('.remove-btn')) { this._dragIdx = null; return; }
        const lis = [...this.shadowRoot.querySelectorAll('li')];
        const dest = lis.find(l => {
          const r = l.getBoundingClientRect();
          return e.clientY >= r.top && e.clientY <= r.bottom;
        });
        const destIdx = dest ? +dest.dataset.idx : null;

        lis.forEach(l => l.classList.remove('dragging', 'over'));

        if (destIdx !== null && destIdx !== this._dragIdx && this._hass) {
          const newOrder = [...(this._config.zone_ids || [])];
          const [moved] = newOrder.splice(this._dragIdx, 1);
          newOrder.splice(destIdx, 0, moved);
          if (this._isCascadeMode()) {
            this._hass.callService('irrisynk', 'reorder_cascade_zones', {
              cascade_id: this._config.cascade_id,
              zone_ids: newOrder,
            });
          } else {
            this._hass.callService('irrisynk', 'reorder_zones', { zone_ids: newOrder });
          }
        }

        this._dragIdx = null;
      });

      ul.addEventListener('pointercancel', () => {
        this.shadowRoot.querySelectorAll('li').forEach(l => l.classList.remove('dragging', 'over'));
        this._dragIdx = null;
      });
    }

    getCardSize() { return Math.max(1, (this._config.zone_ids || []).length); }
  }

  if (!customElements.get('irrisynk-zone-order-card')) {
    customElements.define('irrisynk-zone-order-card', IrriSynkZoneOrderCard);
    console.info(
      '%c irrisynk-zone-order-card %c loaded',
      'color:#4CAF50;font-weight:bold;background:#000;padding:2px 4px;border-radius:3px',
      ''
    );
  }
})();
