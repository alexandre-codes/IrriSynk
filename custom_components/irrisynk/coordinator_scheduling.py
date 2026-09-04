# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Scheduling mixin for IrriSynk coordinator."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ZONE_MODE_MANUAL,
    ZONE_MODE_SCHEDULED,
)

_LOGGER = logging.getLogger(__name__)
_MAX_START_RETRIES = 9  # minutes before giving up and notifying


class SchedulingMixin:
    """Mixin providing irrigation scheduling logic."""

    async def _async_recover_irrigation_state(self) -> None:
        """On startup: stop overdue irrigations, re-arm active ones."""
        now = dt_util.now()
        changed = False
        for zone_id, zone in self.zone_states.items():
            if not zone.irrigation_end_time:
                continue
            try:
                end_time = datetime.fromisoformat(zone.irrigation_end_time)
            except ValueError:
                self.zone_states[zone_id] = replace(zone, irrigation_end_time=None)
                changed = True
                continue

            if now >= end_time:
                _LOGGER.info(f"Zone {zone_id}: irrigation overdue after reboot — turning off")
                if zone.switch_entity_id:
                    await self._async_entity_turn_off(zone.switch_entity_id)
                self.zone_states[zone_id] = replace(zone, irrigation_end_time=None)
                changed = True
            else:
                remaining = (end_time - now).total_seconds() / 60
                _LOGGER.info(
                    "Zone %s: irrigation still active after reboot, %.1f min remaining — "
                    "switch will be re-checked on next tick",
                    zone_id, remaining,
                )
                self._active_irrigations.add(zone_id)

        if changed:
            await self._async_save()

    async def _async_on_switch_state_change(self, event) -> None:
        """React immediately when a monitored switch goes off/unavailable."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state not in ("off", "closed", "unavailable", "unknown"):
            return
        entity_id = event.data.get("entity_id")
        zone_id = next(
            (zid for zid, z in self.zone_states.items() if z.switch_entity_id == entity_id),
            None,
        )
        if zone_id is None:
            return
        zone = self.zone_states[zone_id]
        if zone.zone_mode == ZONE_MODE_MANUAL or not zone.start_time_str:
            return
        if not self._zone_due_today(zone, dt_util.now().date()):
            return
        # Active irrigation: switch went off unexpectedly → stop and advance cascade
        if zone_id in self._active_irrigations:
            _LOGGER.info(
                "Zone %s: switch %s → %s during active irrigation — stopping",
                zone_id, entity_id, new_state.state,
            )
            await self._async_stop_irrigation(zone_id)
            return
        if zone_id in self._pending_start:
            return
        # Only react if we are currently inside the expected irrigation window
        now = dt_util.now()
        if zone.zone_mode == ZONE_MODE_SCHEDULED:
            listener_duration = zone.scheduled_duration_min
        else:
            _computed_z = (self.data or {}).get(zone_id)
            listener_duration = _computed_z.recommended_duration_min if _computed_z else 0.0
        if listener_duration > 0:
            try:
                _h, _m = map(int, zone.start_time_str.split(":"))
            except (ValueError, AttributeError):
                return
            _start_dt = now.replace(hour=_h, minute=_m, second=0, microsecond=0)
            _end_dt = _start_dt + timedelta(minutes=listener_duration)
            if _start_dt <= now < _end_dt:
                _LOGGER.info(
                    "Zone %s: switch %s → %s inside window [%s, %s[ — queued for retry",
                    zone_id, entity_id, new_state.state,
                    zone.start_time_str, _end_dt.strftime("%H:%M"),
                )
                self._pending_start.setdefault(zone_id, _MAX_START_RETRIES)

    async def _async_dispatch(self, now: datetime) -> None:
        """Dispatch minute tick: midnight balance then irrigation schedule."""
        if now.hour == 0 and now.minute == 0:
            await self._async_midnight_balance_update(now)
        await self._async_check_schedule(now)

    async def _async_check_schedule(self, now: datetime) -> None:
        """Fire every minute — stop overdue irrigations then start scheduled ones."""
        # 1. Stop any irrigation whose end time has passed or whose switch is actually off
        for zone_id, zone in list(self.zone_states.items()):
            if zone.irrigation_end_time and zone_id in self._active_irrigations:
                try:
                    end_time = datetime.fromisoformat(zone.irrigation_end_time)
                except ValueError:
                    end_time = None
                if end_time and now >= end_time:
                    await self._async_stop_irrigation(zone_id)
                elif zone.switch_entity_id:
                    sw = self.hass.states.get(zone.switch_entity_id)
                    if sw is not None and sw.state in ("off", "closed"):
                        _LOGGER.info(
                            "Zone %s: tracked as active but switch %s is %s — stopping",
                            zone_id, zone.switch_entity_id, sw.state,
                        )
                        await self._async_stop_irrigation(zone_id)

        current_hm = f"{now.hour:02d}:{now.minute:02d}"

        # 2a/2b. Cascade mode: fire or refresh times for each cascade group
        for _casc in self.cascades:
            if not _casc.enabled or not _casc.start_time:
                continue
            _casc_active = _casc.cascade_id in self._cascade_active
            _casc_zones_running = any(z in self._active_irrigations for z in _casc.zone_ids)
            if _casc_active and not _casc_zones_running:
                # Phantom state: cascade marked active but no zone is running.
                # Check if the first zone's irrigation window has already closed — if so, clear.
                _first_id = next(iter(self._cascade_active.get(_casc.cascade_id, [])), None)
                if _first_id:
                    _fz = self.zone_states.get(_first_id)
                    if _fz and _fz.start_time_str:
                        try:
                            _fh, _fm = map(int, _fz.start_time_str.split(":"))
                            _fstart = now.replace(hour=_fh, minute=_fm, second=0, microsecond=0)
                            if _fz.zone_mode == ZONE_MODE_SCHEDULED:
                                _fdur = _fz.scheduled_duration_min
                            else:
                                _fcomp = (self.data or {}).get(_first_id)
                                _fdur = _fcomp.recommended_duration_min if _fcomp else None
                            if _fdur is not None and _fdur > 0:
                                _fend = _fstart + timedelta(minutes=_fdur)
                                if now >= _fend:
                                    _LOGGER.warning(
                                        "Cascade %s: état fantôme (zone %s, fenêtre fermée à %s) — nettoyage",
                                        _casc.cascade_id, _first_id, _fend.strftime("%H:%M"),
                                    )
                                    self._cascade_active.pop(_casc.cascade_id, None)
                                    _casc_active = False
                        except (ValueError, AttributeError):
                            pass
            if _casc_active or _casc_zones_running:
                continue
            _valid = self._cascade_valid_zones(_casc)
            if _casc.start_time == current_hm:
                await self._async_start_cascade(_casc)
            elif _valid:
                self._write_cascade_times(_valid, _casc.start_time)
            else:
                _LOGGER.warning(
                    "Cascade %s: no valid zones (enabled=%s, start_time=%s, zone_ids=%s)",
                    _casc.cascade_id, _casc.enabled, _casc.start_time, _casc.zone_ids,
                )

        # 3. Window-based start/retry for AUTO and SCHEDULED zones
        for zone_id, zone in self.zone_states.items():
            if zone.zone_mode == ZONE_MODE_MANUAL:
                continue
            if zone_id in self._active_irrigations:
                continue
            if not zone.switch_entity_id or not zone.start_time_str:
                self._pending_start.pop(zone_id, None)
                continue
            if not self._zone_due_today(zone, now.date()):
                self._pending_start.pop(zone_id, None)
                continue

            # Cascade guard: zone belongs to an enabled cascade → only the first zone in
            # the active sequence may start; all others wait for their turn.
            _casc_owner = next(
                (c for c in self.cascades if zone_id in c.zone_ids and c.enabled), None
            )
            if _casc_owner:
                _active_seq = self._cascade_active.get(_casc_owner.cascade_id, [])
                if not _active_seq or _active_seq[0] != zone_id:
                    self._pending_start.pop(zone_id, None)
                    continue

            # Expected duration
            if zone.zone_mode == ZONE_MODE_SCHEDULED:
                duration_min = zone.scheduled_duration_min
            else:
                computed_z = (self.data or {}).get(zone_id)
                if computed_z is None:
                    continue  # no data yet — keep pending state, retry next minute
                duration_min = computed_z.recommended_duration_min

            if duration_min <= 0:
                self._pending_start.pop(zone_id, None)
                # If this zone is first in a cascade sequence, advance past it
                if _casc_owner:
                    _active_seq = self._cascade_active.get(_casc_owner.cascade_id, [])
                    if _active_seq and _active_seq[0] == zone_id:
                        _LOGGER.info(
                            "Cascade %s: zone %s has duration 0 — skipping to next zone",
                            _casc_owner.cascade_id, zone_id,
                        )
                        await self._async_recalculate_cascade_from(zone_id)
                continue

            # Irrigation window [start_dt, end_dt[
            try:
                h, m = map(int, zone.start_time_str.split(":"))
            except (ValueError, AttributeError):
                continue
            start_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            end_dt = start_dt + timedelta(minutes=duration_min)

            if start_dt <= now < end_dt:
                switch_state = self.hass.states.get(zone.switch_entity_id)
                if switch_state is not None and switch_state.state == "on":
                    # Irrigation running (by IrriSynk or manually) — clear pending
                    self._pending_start.pop(zone_id, None)
                else:
                    # In window but switch not ON — should be running
                    retries = self._pending_start.setdefault(zone_id, _MAX_START_RETRIES)
                    if retries <= 0:
                        self._pending_start.pop(zone_id)
                        await self._async_notify_start_failed(zone_id, switch_state)
                    else:
                        self._pending_start[zone_id] = retries - 1
                        await self._async_start_irrigation(zone_id)
            else:
                # Outside window — clear pending without notification
                self._pending_start.pop(zone_id, None)

    async def _async_start_irrigation(self, zone_id: str) -> None:
        zone = self.zone_states[zone_id]
        switch_state = self.hass.states.get(zone.switch_entity_id)
        if switch_state is None or switch_state.state in ("unavailable", "unknown"):
            return
        if zone.zone_mode == ZONE_MODE_SCHEDULED:
            duration_min = zone.scheduled_duration_min
            computed = (self.data or {}).get(zone_id)  # optional — for Telegram only
        else:
            computed = (self.data or {}).get(zone_id)
            if computed is None:
                return
            duration_min = computed.recommended_duration_min
        if duration_min <= 0:
            _LOGGER.info(
                "Zone %s: irrigation skipped — water need is zero "
                "(rain=%.1f mm, balance=%+.1f mm, ET0=%.1f mm)",
                zone_id,
                computed.effective_rain_mm if computed else 0.0,
                computed.soil_water_balance_mm if computed else 0.0,
                self.et0_mm,
            )
            return

        end_time = dt_util.now() + timedelta(minutes=duration_min)
        self.zone_states[zone_id] = replace(
            self.zone_states[zone_id], irrigation_end_time=end_time.isoformat()
        )
        await self._async_save()

        self._active_irrigations.add(zone_id)
        await self._async_entity_turn_on(zone.switch_entity_id)
        _LOGGER.info(
            "Zone %s: irrigation started — %.1f min, ends at %s",
            zone_id, duration_min, end_time.strftime("%H:%M"),
        )
        if self.telegram_enabled and self.telegram_notify_irrigations and self.telegram_chat_id:
            zone_name = self._zone_display_name(zone_id)
            end_hm = end_time.strftime("%H:%M")
            need_str = f"{computed.water_need_mm:.1f} mm" if computed else "?"
            irr_str = f"{computed.irrigation_today_mm:.1f} mm" if computed else "?"
            if self._is_english():
                msg = (
                    f"\U0001f4a7 {zone_name}: irrigation started — {duration_min:.0f} min (ends at {end_hm})\n"
                    f"Need: {need_str} | Irrigated today: {irr_str}"
                )
            else:
                msg = (
                    f"\U0001f4a7 {zone_name} : arrosage démarré — {duration_min:.0f} min (fin à {end_hm})\n"
                    f"Besoin : {need_str} | Arrosé aujourd'hui : {irr_str}"
                )
            self.hass.async_create_task(self._async_send_telegram(msg))

    async def _async_stop_irrigation(self, zone_id: str) -> None:
        zone = self.zone_states[zone_id]
        # Capture switch state and planned end before clearing
        switch_state = self.hass.states.get(zone.switch_entity_id) if zone.switch_entity_id else None
        switch_was_on = switch_state is not None and self._entity_is_on(zone.switch_entity_id)
        planned_end_iso = zone.irrigation_end_time
        if zone.switch_entity_id:
            await self._async_entity_turn_off(zone.switch_entity_id)
        self._active_irrigations.discard(zone_id)
        self.zone_states[zone_id] = replace(zone, irrigation_end_time=None)
        _LOGGER.info(f"Zone {zone_id}: irrigation stopped (switch was {'on' if switch_was_on else 'off/unavailable'})")
        for _c in self.cascades:
            if zone_id in _c.zone_ids and _c.cascade_id in self._cascade_active:
                await self._async_recalculate_cascade_from(zone_id)
                break
        await self._async_save()
        await self._async_recompute_from_cache()
        # Send Telegram after recompute so irrigation_today_mm and water_need_mm are up to date
        if self.telegram_enabled and self.telegram_notify_irrigations and self.telegram_chat_id:
            zone_name = self._zone_display_name(zone_id)
            computed = (self.data or {}).get(zone_id)
            irr_str = f"{computed.irrigation_today_mm:.1f} mm" if computed else "?"
            need_str = f"{computed.water_need_mm:.1f} mm" if computed else "?"
            if switch_was_on:
                if self._is_english():
                    msg = f"✅ {zone_name}: irrigation complete — {irr_str} applied, remaining need: {need_str}"
                else:
                    msg = f"✅ {zone_name} : arrosage terminé — {irr_str} apportés, besoin restant : {need_str}"
            else:
                lost_str = ""
                if switch_state and planned_end_iso:
                    try:
                        planned_end = datetime.fromisoformat(planned_end_iso)
                        lost_sec = (planned_end - switch_state.last_changed).total_seconds()
                        if lost_sec > 60:
                            lost_min = round(lost_sec / 60)
                            lost_str = (
                                f" — {lost_min} min short" if self._is_english()
                                else f" — {lost_min} min manquantes"
                            )
                    except (ValueError, TypeError, AttributeError):
                        pass
                state_label = switch_state.state if switch_state else ("unavailable" if self._is_english() else "indisponible")
                if self._is_english():
                    msg = f"⚠️ {zone_name}: irrigation interrupted{lost_str} ({irr_str} applied, need: {need_str}, valve: {state_label})"
                else:
                    msg = f"⚠️ {zone_name} : arrosage interrompu{lost_str} ({irr_str} apportés, besoin : {need_str}, électrovanne : {state_label})"
            self.hass.async_create_task(self._async_send_telegram(msg))

    async def _async_notify_start_failed(self, zone_id: str, switch_state) -> None:
        """Alert when a zone could not start after the full retry window."""
        from homeassistant.components.persistent_notification import async_create as pn_create  # type: ignore[import]
        zone = self.zone_states.get(zone_id)
        switch_id = zone.switch_entity_id if zone else zone_id
        zone_name = self._zone_display_name(zone_id)
        if switch_state is None:
            reason = "not found" if self._is_english() else "introuvable"
        else:
            reason = switch_state.state
        notif_id = f"{DOMAIN}_start_failed_{zone_id}"
        if self._is_english():
            title = "IrriSynk – Irrigation not triggered"
            msg = (
                f"Zone **{zone_name}** did not start during its scheduled window "
                f"({_MAX_START_RETRIES} min).\n\n"
                f"Valve `{switch_id}` — reason: **{reason}**"
            )
        else:
            title = "IrriSynk – Arrosage non déclenché"
            msg = (
                f"La zone **{zone_name}** n'a pas démarré pendant sa plage d'arrosage "
                f"({_MAX_START_RETRIES} min).\n\n"
                f"Électrovanne `{switch_id}` — raison : **{reason}**"
            )
        _LOGGER.warning("IrriSynk: zone %s start failed — switch %s: %s", zone_id, switch_id, reason)
        try:
            result = pn_create(self.hass, msg, title=title, notification_id=notif_id)
            if hasattr(result, "__await__"):
                await result
        except Exception:  # noqa: BLE001
            pass
        if self.telegram_enabled and self.telegram_notify_unavailable and self.telegram_chat_id:
            if self._is_english():
                tg_msg = f"⚠️ {zone_name}: irrigation not triggered — valve: {reason}"
            else:
                tg_msg = f"⚠️ {zone_name} : arrosage non déclenché — électrovanne : {reason}"
            self.hass.async_create_task(self._async_send_telegram(tg_msg))

    async def _async_entity_turn_on(self, entity_id: str) -> None:
        """Turn on a switch or open a valve based on entity domain."""
        domain = entity_id.split(".")[0]
        service = "open_valve" if domain == "valve" else "turn_on"
        await self.hass.services.async_call(
            domain, service, service_data={"entity_id": entity_id}, blocking=False
        )

    async def _async_entity_turn_off(self, entity_id: str) -> None:
        """Turn off a switch or close a valve based on entity domain."""
        domain = entity_id.split(".")[0]
        service = "close_valve" if domain == "valve" else "turn_off"
        await self.hass.services.async_call(
            domain, service, service_data={"entity_id": entity_id}, blocking=False
        )

    def _entity_is_on(self, entity_id: str) -> bool:
        """Return True if the switch/valve entity is active (on or open)."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        domain = entity_id.split(".")[0]
        return state.state == ("open" if domain == "valve" else "on")
