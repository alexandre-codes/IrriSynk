(function () {
  'use strict';

  const DIALOG_TAG = 'irrisynk-zone-dialog';

  const CLOSE_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24">
    <path fill="currentColor" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
  </svg>`;

  const STYLES = `
    :host { display: block; }
    .overlay {
      position: fixed;
      inset: 0;
      z-index: 100000;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 64px 16px 16px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s ease;
    }
    .overlay.open { opacity: 1; pointer-events: auto; }
    .panel {
      width: min(92vw, 480px);
      max-height: min(86vh, 720px);
      display: flex;
      flex-direction: column;
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow,
        0 11px 15px -7px rgba(0,0,0,.2),
        0 24px 38px 3px rgba(0,0,0,.14),
        0 9px 46px 8px rgba(0,0,0,.12));
      overflow: hidden;
      transform: translateY(8px) scale(0.98);
      transition: transform 0.15s ease;
    }
    .overlay.open .panel { transform: translateY(0) scale(1); }

    /* Mobile: full-height sheet flush with the top, sliding up from the
       bottom — matches Home Assistant's own more-info dialog on narrow
       screens (Material's mobile-dialog breakpoint is 600px). */
    @media (max-width: 600px) {
      .overlay { align-items: flex-start; padding: 0; }
      .panel {
        width: 100%;
        max-width: 100%;
        height: 100%;
        max-height: 100%;
        border-radius: 0;
        padding-top: env(safe-area-inset-top, 0px);
        padding-bottom: env(safe-area-inset-bottom, 0px);
        transform: translateY(100%);
      }
      .overlay.open .panel { transform: translateY(0); }
    }

    .header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 16px 8px 12px 20px;
      flex: none;
    }
    .title { font-size: 1.5rem; font-weight: 500; flex: 1; }
    .close {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color);
      display: flex;
      align-items: center;
      padding: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .close:hover { background: rgba(var(--rgb-primary-text-color, 0, 0, 0), 0.08); }
    .tabs {
      display: flex;
      justify-content: center;
      overflow-x: auto;
      border-bottom: 1px solid var(--divider-color, rgba(0,0,0,.12));
      flex: none;
      padding: 0 8px;
    }
    .tab {
      background: none;
      border: none;
      cursor: pointer;
      color: var(--secondary-text-color);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 10px 16px;
      border-bottom: 2px solid transparent;
      transition: color 0.1s, border-color 0.1s;
    }
    .tab ha-icon { --mdc-icon-size: 22px; }
    .tab.active {
      color: var(--primary-color, #03a9f4);
      border-bottom-color: var(--primary-color, #03a9f4);
    }
    .content {
      overflow-y: auto;
      padding: 4px 0 12px;
    }
    .pane ha-card { box-shadow: none; border: none; background: transparent; }
    /* 24px matches HA's own gap *between* sections (hui-sections-view's
       --ha-view-sections-row-gap) — headings only get the smaller 8px
       card-to-card gap when they're stuck inside one section's card list. */
    .pane hui-heading-card { display: block; margin: 18px 4px 4px; }
    .error { padding: 16px 20px; color: var(--secondary-text-color); font-size: 0.9rem; }
  `;

  // A HassDialog (legacy showDialog() pattern, see home-assistant/frontend
  // src/dialogs/make-dialog-manager.ts). Home Assistant's own dialog manager
  // creates this element, calls provideHass() on it (so `hass` keeps updating
  // for free, no polling needed) and mounts it inside <home-assistant>'s own
  // shadowRoot — the only placement that both actually paints (no light-DOM
  // slot exists on that element) and sits inside the real app tree, which is
  // what lets Lit's Context API (used internally by statistics-graph's chart
  // for theme info) resolve correctly.
  class IrriSynkZoneDialog extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this._hass = null;
      this._payload = null;
      this._activeTabId = null;
      this._tabCards = {};
      this._prevBodyOverflow = '';
      this._open = false;
      this._onKeydown = (e) => { if (e.key === 'Escape') this.closeDialog(); };
    }

    set hass(hass) {
      this._hass = hass;
      for (const id in this._tabCards) {
        const elements = this._tabCards[id];
        if (elements) elements.forEach((el) => { el.hass = hass; });
      }
      // The zone was deleted (button press → confirmation → integration
      // reload drops its entities): its anchor entity vanishes from
      // hass.states, so close the now-stale dialog automatically.
      const anchor = this._payload && this._payload.anchor_entity;
      if (this._open && anchor && hass && hass.states && !(anchor in hass.states)) {
        this.closeDialog();
      }
    }

    get hass() {
      return this._hass;
    }

    showDialog(payload) {
      this._payload = payload;
      const requested = payload.initial_tab;
      const hasRequested = requested && payload.tabs.some((t) => t.id === requested);
      this._activeTabId = hasRequested ? requested : ((payload.tabs[0] && payload.tabs[0].id) || null);
      this._tabCards = {};
      this._open = true;
      this._render();

      this._prevBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      document.addEventListener('keydown', this._onKeydown);

      requestAnimationFrame(() => {
        const overlay = this.shadowRoot.querySelector('.overlay');
        if (overlay) overlay.classList.add('open');
      });
    }

    closeDialog() {
      if (!this._open) return true;
      this._open = false;
      document.removeEventListener('keydown', this._onKeydown);
      document.body.style.overflow = this._prevBodyOverflow;
      const overlay = this.shadowRoot.querySelector('.overlay');
      if (overlay) overlay.classList.remove('open');
      this.dispatchEvent(new CustomEvent('dialog-closed', {
        bubbles: true,
        composed: true,
        detail: { dialog: DIALOG_TAG },
      }));
      return true;
    }

    _render() {
      const payload = this._payload;
      const tabsHtml = payload.tabs.map(
        (t) => `<button class="tab" data-id="${t.id}" title="${t.label}" aria-label="${t.label}">
          <ha-icon icon="${t.icon}"></ha-icon>
        </button>`
      ).join('');

      this.shadowRoot.innerHTML = `
        <style>${STYLES}</style>
        <div class="overlay">
          <div class="panel">
            <div class="header">
              <div class="title">${payload.zone_name}</div>
              <button class="close" aria-label="Fermer">${CLOSE_ICON}</button>
            </div>
            <div class="tabs">${tabsHtml}</div>
            <div class="content"></div>
          </div>
        </div>`;

      const overlay = this.shadowRoot.querySelector('.overlay');
      overlay.addEventListener('pointerdown', (e) => {
        if (e.target === overlay) this.closeDialog();
      });
      this.shadowRoot.querySelector('.close').addEventListener('click', () => this.closeDialog());
      this.shadowRoot.querySelectorAll('.tab').forEach((btn) => {
        btn.addEventListener('click', () => this._selectTab(btn.dataset.id));
      });

      this._selectTab(this._activeTabId);
    }

    async _selectTab(tabId) {
      if (!tabId) return;
      this._activeTabId = tabId;

      this.shadowRoot.querySelectorAll('.tab').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.id === tabId);
      });

      const content = this.shadowRoot.querySelector('.content');
      content.querySelectorAll('.pane').forEach((pane) => {
        pane.hidden = pane.dataset.tab !== tabId;
      });

      if (this._tabCards[tabId]) return;

      const tabConfig = this._payload.tabs.find((t) => t.id === tabId);
      if (!tabConfig) return;

      const pane = document.createElement('div');
      pane.className = 'pane';
      pane.dataset.tab = tabId;
      content.appendChild(pane);

      try {
        if (!window.loadCardHelpers) throw new Error('loadCardHelpers unavailable');
        const helpers = await window.loadCardHelpers();
        // tabConfig.card is a flat list of card configs (heading + content, not
        // wrapped in a vertical-stack) so each becomes its own direct child here —
        // that's what lets our CSS reach the heading card to style its margin.
        const cardConfigs = Array.isArray(tabConfig.card) ? tabConfig.card : [tabConfig.card];
        const elements = cardConfigs.map((cfg) => helpers.createCardElement(cfg));
        elements.forEach((el) => {
          el.hass = this._hass;
          pane.appendChild(el);
        });
        this._tabCards[tabId] = elements;
      } catch (err) {
        pane.insertAdjacentHTML('beforeend', '<div class="error">Impossible de charger cet onglet.</div>');
        console.error('irrisynk-zone-dialog: failed to build tab card', err);
      }
    }
  }

  if (!customElements.get(DIALOG_TAG)) {
    customElements.define(DIALOG_TAG, IrriSynkZoneDialog);
    console.info(
      '%c irrisynk-zone-dialog %c loaded',
      'color:#4CAF50;font-weight:bold;background:#000;padding:2px 4px;border-radius:3px',
      ''
    );
  }

  // Same "show-dialog" event Home Assistant's own dialogs (more-info, settings, ...)
  // and browser_mod use — makeDialogManager() on <home-assistant> creates/reuses the
  // element, wires up hass, and mounts it in the right place.
  function _openZoneDialog(payload) {
    const haRoot = document.querySelector('home-assistant');
    if (!haRoot) return;
    haRoot.dispatchEvent(new CustomEvent('show-dialog', {
      bubbles: true,
      composed: true,
      detail: {
        dialogTag: DIALOG_TAG,
        dialogImport: () => Promise.resolve(),
        dialogParams: payload,
        addHistory: false,
      },
    }));
  }

  if (!window.__irrisynkZoneDialogListenerAttached) {
    window.__irrisynkZoneDialogListenerAttached = true;
    window.addEventListener('ll-custom', (ev) => {
      const detail = ev.detail;
      if (!detail || !detail.irrisynk_dialog) return;
      _openZoneDialog(detail.irrisynk_dialog);
    });
  }

  // Opens automatically once a just-created zone (AddZoneButton → integration
  // reload) is ready — the backend fires this event with the same payload shape
  // used for tap-to-open, once async_update_dashboard() confirms the zone exists.
  if (!window.__irrisynkZoneCreatedSubscribed) {
    window.__irrisynkZoneCreatedSubscribed = true;
    (function subscribeZoneCreated() {
      const haRoot = document.querySelector('home-assistant');
      const connection = haRoot && haRoot.hass && haRoot.hass.connection;
      if (!connection) {
        setTimeout(subscribeZoneCreated, 500);
        return;
      }
      connection.subscribeEvents((event) => {
        const payload = event.data && event.data.irrisynk_dialog;
        const urlPath = event.data && event.data.dashboard_url_path;
        if (!payload) return;
        // hass.bus events reach every connected session, not just the one that
        // pressed "Add zone" — only pop the modal open on tabs that are actually
        // looking at this dashboard right now, so it doesn't interrupt someone
        // on an unrelated page or another person's session.
        if (urlPath && window.location.pathname.indexOf('/' + urlPath) === -1) return;
        _openZoneDialog(payload);
      }, 'irrisynk_zone_created');
    })();
  }
})();
