# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Lovelace dashboard management for IrriSynk.

Generates a 3-tab dashboard and pushes it to HA's Lovelace storage so all
connected browsers receive an automatic reload notification.  Falls back to
a YAML file + persistent notification if the internal API is unavailable.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation as ha_translation
from homeassistant.helpers.storage import Store

from .const import CONF_WEATHER_ENTITY_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

_DASHBOARD_URL = "dashboard-irrisynk"
_STORAGE_KEY_CONFIG = f"lovelace.{_DASHBOARD_URL}"
_STORAGE_VERSION = 1
_EVENT_LOVELACE_UPDATED = "lovelace_updated"

_DASHBOARD_META = {
    "url_path": _DASHBOARD_URL,
    "require_admin": False,
    "show_in_sidebar": True,
    "icon": "mdi:watering-can",
    "title": "IrriSynk",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def async_update_dashboard(hass: HomeAssistant) -> None:
    """Regenerate and push the IrriSynk Lovelace dashboard."""
    ent_reg = er.async_get(hass)
    uid_to_entity: dict[str, str] = {
        e.unique_id: e.entity_id
        for e in ent_reg.entities.values()
        if e.unique_id
    }
    dev_reg = dr.async_get(hass)

    for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
        zone_names = _get_zone_device_names(dev_reg, entry_id, coordinator)
        lang = "en" if coordinator._is_english() else "fr"
        entity_own_names = await _async_build_entity_names(hass, ent_reg, lang)
        config = _build_dashboard_config(
            entry_id, coordinator, uid_to_entity, zone_names, entity_own_names
        )
        # Always write the YAML file so YAML-mode dashboards stay in sync
        await _async_write_yaml_fallback(hass, config)
        # Also push to Lovelace storage for live browser update
        try:
            await _async_push_to_storage(hass, config)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Lovelace storage push failed (%s)", exc)
        return  # Single-instance: first entry only


async def _async_build_entity_names(
    hass: HomeAssistant,
    ent_reg: er.EntityRegistry,
    lang: str,
) -> dict[str, str]:
    """Return {entity_id: translated_own_name} for all integration entities.

    User-overridden names take priority. For all others, the name is resolved
    from HA's translation files so it matches the dashboard language exactly.
    """
    try:
        translations = await ha_translation.async_get_translations(
            hass, lang, "entity", integrations={DOMAIN}
        )
    except Exception:  # noqa: BLE001
        translations = {}

    result: dict[str, str] = {}
    for entry in ent_reg.entities.values():
        if not entry.entity_id or entry.platform != DOMAIN:
            continue
        if entry.name:
            result[entry.entity_id] = entry.name
            continue
        translation_key = getattr(entry, "translation_key", None)
        if not translation_key:
            continue
        entity_domain = entry.entity_id.split(".")[0]
        key = f"component.{DOMAIN}.entity.{entity_domain}.{translation_key}.name"
        if name := translations.get(key):
            result[entry.entity_id] = name
    return result


def _get_zone_device_names(
    dev_reg: dr.DeviceRegistry, entry_id: str, coordinator: Any
) -> dict[str, str]:
    """Return {zone_id: display_name} using user-overridden name when set."""
    names: dict[str, str] = {}
    for device in dr.async_entries_for_config_entry(dev_reg, entry_id):
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            suffix = identifier[len(entry_id) + 1:]
            if suffix in coordinator.zone_states:
                names[suffix] = device.name_by_user or device.name or suffix
    return names


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _get_lovelace_data(hass: HomeAssistant) -> Any:
    """Return hass.data[LOVELACE_DATA], falling back to the raw 'lovelace' key."""
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA  # type: ignore[import]
        data = hass.data.get(LOVELACE_DATA)
        if data is not None:
            return data
    except ImportError:
        pass
    return hass.data.get("lovelace")


async def _async_push_to_storage(hass: HomeAssistant, config: dict) -> None:
    """Write config to Lovelace storage and notify connected browsers."""
    await _async_ensure_registered(hass)

    if not await _async_save_via_lovelace_object(hass, config):
        store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY_CONFIG)
        await store.async_save({"config": config})

    try:
        from homeassistant.components.lovelace.const import EVENT_LOVELACE_UPDATED  # type: ignore[import]
        event_name = EVENT_LOVELACE_UPDATED
    except ImportError:
        event_name = _EVENT_LOVELACE_UPDATED

    hass.bus.async_fire(event_name, {"url_path": _DASHBOARD_URL})


async def _async_save_via_lovelace_object(hass: HomeAssistant, config: dict) -> bool:
    """Save config via HA's internal LovelaceStorage object (dashboards dict).

    Returns True on success.
    """
    try:
        lovelace_data = _get_lovelace_data(hass)
        if lovelace_data is None:
            return False
        dashboards = getattr(lovelace_data, "dashboards", None)
        if not isinstance(dashboards, dict):
            return False
        config_obj = dashboards.get(_DASHBOARD_URL)
        if config_obj is None:
            return False
        for fn_name in ("async_save_config", "async_save"):
            fn = getattr(config_obj, fn_name, None)
            if fn:
                await fn(config)
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def _async_ensure_registered(hass: HomeAssistant) -> None:
    """Ensure LovelaceStorage exists in dashboards dict AND panel is in sidebar."""
    try:
        lovelace_data = _get_lovelace_data(hass)
        if lovelace_data is None:
            raise ValueError("Lovelace data not available")

        dashboards = getattr(lovelace_data, "dashboards", None)
        if not isinstance(dashboards, dict):
            raise TypeError(f"dashboards is not a dict: {type(dashboards)}")

        if _DASHBOARD_URL not in dashboards:
            from homeassistant.components.lovelace.dashboard import LovelaceStorage  # type: ignore[import]
            import uuid as _uuid
            dashboards[_DASHBOARD_URL] = LovelaceStorage(hass, {
                "id": str(_uuid.uuid4()),
                **_DASHBOARD_META,
                "mode": "storage",
            })
            await _async_persist_to_dashboards_store(hass)

        if _DASHBOARD_URL not in hass.data.get("frontend_panels", {}):
            await _async_register_sidebar_panel(hass)

    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("IrriSynk: could not register dashboard (%s)", exc)
        await _async_notify_manual_setup(hass)


async def _async_register_sidebar_panel(hass: HomeAssistant) -> None:
    """Register the Lovelace panel in the sidebar."""
    import homeassistant.components.frontend as _fe
    panel_config = {"mode": "storage", "urlPath": _DASHBOARD_URL, "editMode": False}
    for fn_name in ("async_register_built_in_panel", "async_register_panel"):
        fn = getattr(_fe, fn_name, None)
        if fn is None:
            continue
        try:
            fn(
                hass,
                component_name="lovelace",
                sidebar_title=_DASHBOARD_META["title"],
                sidebar_icon=_DASHBOARD_META["icon"],
                frontend_url_path=_DASHBOARD_URL,
                require_admin=_DASHBOARD_META["require_admin"],
                config=panel_config,
            )
            _LOGGER.info("IrriSynk dashboard registered in sidebar")
            return
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Panel registration via %s failed: %s", fn_name, exc)

    _LOGGER.warning("IrriSynk: no panel registration function available")
    await _async_notify_manual_setup(hass)


async def _async_persist_to_dashboards_store(hass: HomeAssistant) -> None:
    """Write our dashboard metadata to lovelace_dashboards store for persistence across restarts."""
    import uuid as _uuid
    try:
        store = Store(hass, 1, "lovelace_dashboards")
        raw = await store.async_load() or {}
        items: list[dict] = list(raw.get("items", []))
        if any(i.get("url_path") == _DASHBOARD_URL for i in items):
            return
        items.append({"id": str(_uuid.uuid4()), **_DASHBOARD_META, "mode": "storage"})
        await store.async_save({**raw, "items": items})
        _LOGGER.debug("IrriSynk: dashboard metadata persisted to lovelace_dashboards store")
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("IrriSynk: failed to persist to lovelace_dashboards store (%s)", exc)


async def _async_notify_manual_setup(hass: HomeAssistant) -> None:
    """Show a one-time notification only if the dashboard is not in the sidebar."""
    if await _async_dashboard_in_sidebar(hass):
        return

    yaml_path = os.path.join(hass.config.config_dir, "irrisynk_dashboard.yaml")
    notif_id = f"{DOMAIN}_sidebar_setup"
    try:
        from homeassistant.components.persistent_notification import async_create as pn_create  # type: ignore[import]
        result = pn_create(
            hass,
            (
                "Le dashboard IrriSynk ne peut pas être enregistré automatiquement.\n\n"
                f"Le fichier de configuration a été généré : `{yaml_path}`\n\n"
                "**Ajoutez dans `configuration.yaml` :**\n"
                "```yaml\n"
                "lovelace:\n"
                "  dashboards:\n"
                f"    {_DASHBOARD_URL}:\n"
                "      mode: yaml\n"
                "      filename: irrisynk_dashboard.yaml\n"
                "      title: IrriSynk\n"
                "      icon: mdi:watering-can\n"
                "      show_in_sidebar: true\n"
                "      require_admin: false\n"
                "```\n"
                "Puis **redémarrez Home Assistant**."
            ),
            title="IrriSynk – Action requise",
            notification_id=notif_id,
        )
        if hasattr(result, "__await__"):
            await result
    except Exception:  # noqa: BLE001
        _LOGGER.warning(
            "IrriSynk: add to configuration.yaml — lovelace.dashboards.%s",
            _DASHBOARD_URL,
        )


async def _async_dashboard_in_sidebar(hass: HomeAssistant) -> bool:
    """Return True if our dashboard is already in the live dashboards dict."""
    try:
        lovelace_data = _get_lovelace_data(hass)
        if lovelace_data is not None:
            dashboards = getattr(lovelace_data, "dashboards", {})
            if isinstance(dashboards, dict) and _DASHBOARD_URL in dashboards:
                return True
    except Exception:  # noqa: BLE001
        pass

    # Fallback: check the dashboards storage file on disk
    import json
    dashboards_path = hass.config.path(".storage", "lovelace_dashboards")
    if not os.path.exists(dashboards_path):
        return False
    try:
        def _read() -> dict:
            with open(dashboards_path, encoding="utf-8") as f:
                return json.load(f)
        raw = await hass.async_add_executor_job(_read)
        items: list[dict] = raw.get("data", {}).get("items", [])
        return any(item.get("url_path") == _DASHBOARD_URL for item in items)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Could not read lovelace_dashboards storage (%s)", exc)
        return False


async def _async_write_yaml_fallback(hass: HomeAssistant, config: dict) -> None:
    """Write the dashboard config to a YAML file (silent backup, no notification)."""
    filepath = os.path.join(hass.config.config_dir, "irrisynk_dashboard.yaml")
    await hass.async_add_executor_job(_write_yaml, filepath, config)


def _write_yaml(filepath: str, data: dict) -> None:
    import yaml  # PyYAML — always available in HA
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Dashboard config builders
# ---------------------------------------------------------------------------

def _build_dashboard_config(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_names: dict[str, str],
    entity_own_names: dict[str, str],
) -> dict:
    zone_ids = list(coordinator.zone_states.keys())
    lbl = _get_labels(coordinator)
    zone_args = (entry_id, coordinator, uid_to_entity, zone_ids, zone_names, entity_own_names, lbl)
    return {
        "title": coordinator.entry.title,
        "views": [
            _build_accueil_view(*zone_args),
            _build_programmation_view(*zone_args),
            _build_zones_view(*zone_args),
            _build_cascades_view(entry_id, coordinator, uid_to_entity, zone_names, lbl),
            _build_cult_modes_view(entry_id, coordinator, uid_to_entity, lbl),
            _build_cultures_view(entry_id, coordinator, uid_to_entity, lbl),
            _build_statistiques_view(entry_id, coordinator, uid_to_entity, zone_ids, zone_names, lbl),
            _build_parametres_view(entry_id, uid_to_entity, entity_own_names, lbl),
            _build_calculateur_view(entry_id, uid_to_entity, lbl),
            _build_wiki_view(*zone_args),
        ],
    }


def _uid(uid_to_entity: dict, unique_id: str) -> str | None:
    return uid_to_entity.get(unique_id)


_LABELS: dict[str, dict[str, str]] = {
    "fr": {
        "view_home": "Accueil",
        "view_programmation": "Programmation",
        "view_settings": "Paramètres",
        "view_stats": "Statistiques",
        "view_calculator": "Calculateur",
        "calc_card_title": "Calculateur débit Goutte à Goutte",
        "calc_inputs_section": "Paramètres",
        "calc_result_section": "Résultat",
        "calc_lbl_flow_lh": "Débit goutteur (L/h)",
        "calc_lbl_dripper_spacing": "Espacement entre goutteurs",
        "calc_lbl_line_count": "Nombre de lignes",
        "calc_lbl_line_spacing": "Espacement entre lignes",
        "calc_lbl_line_length": "Longueur de ligne",
        "calc_lbl_zone_width": "Largeur de la zone",
        "calc_lbl_run": "Calculer",
        "calc_lbl_result": "Débit (mm/m²/h)",
        "view_crops": "Cultures",
        "crops_form_crop_title": "Nouvelle culture",
        "crops_field_crop_name": "Nom de la culture",
        "crops_field_kc": "Coefficient Kc",
        "crops_field_duration_open": "Durée Plein champ (j)",
        "crops_field_duration_gh": "Durée Serre (j)",
        "crops_field_create": "Créer la culture",
        "crops_delete_btn": "Supprimer la culture",
        "crops_root_depth_label": "Profondeur racinaire : ",
        "crops_kc_label": "Kc : ",
        "crops_duration_label": "Plein champ / Serre (j) : ",
        "crops_form_edit_stage_title": "Ajouter / Modifier un stade",
        "crops_field_edit_crop": "Culture",
        "crops_field_edit_stage": "Stade (— = nouveau)",
        "crops_field_edit_name": "Nom du stade",
        "crops_field_save_stage": "Valider",
        "view_cult_modes": "Mode de culture",
        "cult_modes_form_title": "Ajouter un mode",
        "cult_modes_et0_label": "Correcteur ETP : ",
        "cult_modes_delete_btn": "Supprimer",
        "cult_modes_field_name": "Nom du Mode",
        "cult_modes_field_et0": "Correcteur ETP",
        "cult_modes_field_add": "Ajouter le mode",
        "card_weather": "Météo",
        "card_config": "Configuration",
        "sec_schedule": "Programmation",
        "sec_balance": "Bilan",
        "sec_actions": "Actions",
        "sec_all_zones": "Pour toutes les zones",
        "sec_cascade": "Cascade",
        "grp_general": "Général",
        "grp_valve": "Électrovanne",
        "grp_terrain": "Terrain",
        "ent_soil_type": "Type de sol",
        "ent_soil_capacity": "Capacité sol (RAW)",
        "grp_planting": "Plantation",
        "grp_actions": "Actions",
        "ent_weather": "Météo",
        "ent_rain": "Pluie",
        "ent_et0": "ETP",
        "sec_culture": "Culture",
        "acc_scheduled": "Heure",
        "acc_duration": "Durée",
        "acc_need": "Besoin",
        "acc_irrigation": "Arrosage du jour",
        "btn_recalculate": "Recalculer",
        "stat_balance": "Bilan hydrique",
        "view_wiki": "Wiki",
        "zone_order_title": "Ordre des zones",
        "sec_telegram": "Telegram",
        "view_zones": "Zones",
        "view_cascades": "Cascades",
        "cascade_form_title": "Nouvelle cascade",
        "cascade_form_name": "Nom de la cascade",
        "cascade_form_time": "Heure de démarrage",
        "cascade_create_btn": "Créer la cascade",
        "cascade_empty": "Aucune cascade. Créez-en une dans le formulaire →",
        "cascade_zone_order_title": "Ordre des zones",
        "cascade_delete_btn": "Supprimer la cascade",
        "cascade_add_zone_label": "Zone à ajouter",
        "cascade_add_zone_btn": "Ajouter la zone",
        "cascade_enabled_label": "Activer",
        "cascade_time_label": "Heure de départ",
    },
    "en": {
        "view_home": "Home",
        "view_programmation": "Schedule",
        "view_settings": "Settings",
        "view_stats": "Statistics",
        "view_calculator": "Calculator",
        "calc_card_title": "Calculateur débit Goutte à Goutte",
        "calc_inputs_section": "Parameters",
        "calc_result_section": "Result",
        "calc_lbl_flow_lh": "Dripper flow rate (L/h)",
        "calc_lbl_dripper_spacing": "Dripper spacing",
        "calc_lbl_line_count": "Number of lines",
        "calc_lbl_line_spacing": "Line spacing",
        "calc_lbl_line_length": "Line length",
        "calc_lbl_zone_width": "Zone width",
        "calc_lbl_run": "Calculate",
        "calc_lbl_result": "Flow rate (mm/m²/h)",
        "view_crops": "Crops",
        "crops_form_crop_title": "New crop",
        "crops_field_crop_name": "Crop name",
        "crops_field_kc": "Kc coefficient",
        "crops_field_duration_open": "Open field duration (d)",
        "crops_field_duration_gh": "Greenhouse duration (d)",
        "crops_field_create": "Create crop",
        "crops_delete_btn": "Delete crop",
        "crops_root_depth_label": "Root depth: ",
        "crops_kc_label": "Kc: ",
        "crops_duration_label": "Open field / Greenhouse (d): ",
        "crops_form_edit_stage_title": "Add / Edit a stage",
        "crops_field_edit_crop": "Crop",
        "crops_field_edit_stage": "Stage (— = new)",
        "crops_field_edit_name": "Stage name",
        "crops_field_save_stage": "Confirm",
        "view_cult_modes": "Cultivation Mode",
        "cult_modes_form_title": "Add a mode",
        "cult_modes_et0_label": "ET0 factor: ",
        "cult_modes_delete_btn": "Delete",
        "cult_modes_field_name": "Mode Name",
        "cult_modes_field_et0": "ET0 correction factor",
        "cult_modes_field_add": "Add mode",
        "card_weather": "Weather",
        "card_config": "Configuration",
        "sec_schedule": "Schedule",
        "sec_balance": "Balance",
        "sec_actions": "Actions",
        "sec_all_zones": "For all zones",
        "sec_cascade": "Cascade",
        "grp_general": "General",
        "grp_valve": "Electrovalve",
        "grp_terrain": "Terrain",
        "ent_soil_type": "Soil type",
        "ent_soil_capacity": "Soil capacity (RAW)",
        "grp_planting": "Planting",
        "grp_actions": "Actions",
        "ent_weather": "Weather",
        "ent_rain": "Rain",
        "ent_et0": "ET0",
        "sec_culture": "Culture",
        "acc_scheduled": "Time",
        "acc_duration": "Duration",
        "acc_need": "Need",
        "acc_irrigation": "Today's irrigation",
        "btn_recalculate": "Recalculate",
        "stat_balance": "Water balance",
        "view_wiki": "Wiki",
        "zone_order_title": "Zone order",
        "sec_telegram": "Telegram",
        "view_zones": "Zones",
        "view_cascades": "Cascades",
        "cascade_form_title": "New cascade",
        "cascade_form_name": "Cascade name",
        "cascade_form_time": "Start time",
        "cascade_create_btn": "Create cascade",
        "cascade_empty": "No cascade yet. Create one using the form →",
        "cascade_zone_order_title": "Zone order",
        "cascade_delete_btn": "Delete cascade",
        "cascade_add_zone_label": "Zone to add",
        "cascade_add_zone_btn": "Add zone",
        "cascade_enabled_label": "Activate",
        "cascade_time_label": "Start time",
    },
}


_BUILTIN_MODES: dict[str, list[tuple[str, float]]] = {
    "fr": [
        ("Plein champ", 1.0),
        ("Serre Hiver", 0.5),
        ("Serre Printemps", 0.6),
        ("Serre Été", 0.7),
        ("Serre Automne", 0.6),
        ("Paillage organique léger (5cm)", 0.9),
        ("Paillage organique moyen (10cm)", 0.8),
        ("Paillage organique épais (15cm)", 0.7),
        ("Toile tissée ou film plastique", 0.7),
    ],
    "en": [
        ("Open field", 1.0),
        ("Greenhouse Winter", 0.5),
        ("Greenhouse Spring", 0.6),
        ("Greenhouse Summer", 0.7),
        ("Greenhouse Autumn", 0.6),
        ("Light organic mulch (5cm)", 0.9),
        ("Medium organic mulch (10cm)", 0.8),
        ("Heavy organic mulch (15cm)", 0.7),
        ("Woven cover or plastic film", 0.7),
    ],
}


_WIKI_CONTENT: dict[str, tuple[dict, dict, dict]] = {
    "fr": (
        {
            "type": "markdown",
            "title": "IrriSynk",
            "content": (
                "## Présentation\n\n"
                "**IrriSynk** est une intégration Home Assistant pour la **gestion intelligente "
                "de l'arrosage par électrovannes**.\n\n"
                "Elle calcule chaque jour, pour chaque zone, la quantité d'eau exacte à apporter "
                "selon la méthode scientifique **FAO-56** (Penman-Monteith simplifiée), puis "
                "**pilote automatiquement les électrovannes** à l'heure programmée — pour la durée "
                "précise calculée ou définie.\n\n"
                "Pluie du jour, bilan de la veille, stade de végétation, mode de culture : tout est "
                "pris en compte. Si la pluie suffit, l'arrosage est annulé. Le surplus ou le "
                "déficit s'accumule dans un bilan hydrique cumulatif — ce qui évite les oscillations d'arrosage.\n\n"
                "Trois modes par zone — **Manuel**, **Programmé** ou **Auto** —, un mode "
                "**cascade** pour enchaîner les zones séquentiellement.\n\n"
                "### Termes de la formule\n\n"
                "`Besoin = ET₀ × Kc − Pluie efficace − Arrosage du jour − Bilan hydrique − Tampon sol`\n\n"
                "| Terme | Signification |\n"
                "|---|---|\n"
                "| **ET₀** | Évapotranspiration de référence calculée depuis la météo |\n"
                "| **Kc** | Coefficient cultural — dépend de la culture et du stade |\n"
                "| **Pluie efficace** | Précipitations × taux d'efficacité (défaut 80 %) |\n"
                "| **Arrosage du jour** | Mm déjà apportés aujourd'hui (depuis l'historique) |\n"
                "| **Bilan hydrique** | Solde cumulatif des surplus/déficits passés (SWD) |\n"
                "| **Tampon sol** | Réserve hydrique avant déclenchement de l'arrosage |\n\n"
                "Le détail du calcul de chaque terme est dans la carte **Algorithme**.\n\n"
                "---\n\n"
                "## Guide de démarrage\n\n"
                "### 1 · Configurer la zone\n"
                "Dans **Paramètres**, pour chaque zone :\n"
                "- Associer l'**électrovanne** (entity_id du switch HA)\n"
                "- Saisir le **débit d'irrigation** (mm/h) — utilisez le Calculateur\n"
                "- Définir une **durée maximale** de sécurité\n\n"
                "### 2 · Choisir la culture\n"
                "- Sélectionner la **culture** plantée dans la zone\n"
                "- Choisir le **mode de culture** (plein champ, serre, paillage…)\n"
                "- Régler le **mode de stade** : Manuel ou Automatique par jours\n"
                "- En manuel : sélectionner le **stade phénologique** actuel\n\n"
                "### 3 · Activer l'arrosage automatique\n"
                "- Dans **Programmation**, sélectionner le mode **Auto** (durée calculée) ou **Programmé** (durée fixe)\n"
                "- Définir l'**heure de déclenchement** de la zone\n"
                "- En mode **Auto**, IrriSynk calcule et exécute la durée optimale chaque jour\n\n"
                "### 4 · Affiner les paramètres\n"
                "- **Correcteur ETP** : réduire si la météo surestime l'évaporation (ex : 0,9)\n"
                "- **Efficacité pluie** : réduire pour un sol en pente ou très compact\n"
                "- **Tampon sol** : augmenter pour un sol argileux (2–8 mm typique)\n\n"
                "---\n\n"
                "## Pilotage des électrovannes\n\n"
                "IrriSynk commande directement les switchs Home Assistant associés aux électrovannes. "
                "Chaque zone dispose de trois modes de fonctionnement :\n\n"
                "| Mode | Comportement |\n"
                "|---|---|\n"
                "| **Manuel** | Aucun arrosage automatique — la zone est gérée à la main |\n"
                "| **Programmé** | L'électrovanne s'ouvre à l'heure définie pour une **durée fixe** |\n"
                "| **Auto** | L'électrovanne s'ouvre à l'heure définie pour la **durée calculée FAO-56** (nulle si pluie suffisante) |\n\n"
                "L'heure de démarrage se configure par zone dans l'onglet **Programmation**. "
                "Le planificateur vérifie chaque minute les démarrages et arrêts à effectuer.\n\n"
                "**Récupération au redémarrage** : si Home Assistant redémarre pendant un arrosage, "
                "l'irrigation en cours est re-armée pour la durée restante ; "
                "les arrosages en retard sont stoppés automatiquement.\n\n"
                "---\n\n"
                "## Arrosage en cascade\n\n"
                "Le mode cascade permet d'arroser toutes les zones éligibles **séquentiellement** "
                "depuis une unique heure de démarrage globale.\n\n"
                "**Fonctionnement :**\n"
                "1. Activer le switch **Cascade** dans l'onglet Programmation\n"
                "2. Définir l'**heure de démarrage cascade**\n"
                "3. IrriSynk calcule les heures de départ de chaque zone dans l'ordre, "
                "avec **1 minute de battement** entre elles\n"
                "4. Quand une zone se termine, les heures des zones suivantes sont **recalculées dynamiquement**\n\n"
                "Les zones en mode **Manuel** sont exclues de la cascade. "
                "Les zones en mode **Programmé** utilisent leur durée fixe ; "
                "les zones en mode **Auto** utilisent la durée calculée FAO-56.\n\n"
                "---\n\n"
                "## Indicateurs de zone\n\n"
                "| Indicateur | Rôle |\n"
                "|---|---|\n"
                "| ET₀ | Évapotranspiration du jour (mm) |\n"
                "| Kc actuel | Coefficient cultural au stade courant |\n"
                "| Besoin en eau | Quantité à apporter aujourd'hui (mm) |\n"
                "| Durée recommandée | Temps d'arrosage calculé depuis le débit |\n"
                "| Pluie efficace | Précipitations retenues dans le calcul |\n"
                "| Bilan hydrique | Solde cumulatif des surplus/déficits (SWD) |\n"
                "| Confiance | Fiabilité du calcul d'ET₀ (%) |\n\n"
                "**Confiance < 70 %** — données météo partielles : le calcul reste "
                "conservateur et l'arrosage n'est pas inhibé.\n\n"
                "---\n\n"
                "## Cultures & Stades\n\n"
                "### Ajouter une culture personnalisée\n"
                "1. **Cultures** → *Nouvelle culture* : saisir le nom → **Créer**\n"
                "2. Formulaire *Ajouter / Modifier un stade* → sélectionner la culture\n"
                "3. Choisir **— (nouveau stade)**, renseigner : nom, Kc, durée plein champ, durée serre\n"
                "4. Cliquer **Valider** — répéter pour chaque stade\n\n"
                "### Coefficient Kc de référence (FAO-56)\n\n"
                "| Stade phénologique | Kc indicatif |\n"
                "|---|---|\n"
                "| Initial (germination / levée) | 0,3 – 0,5 |\n"
                "| Développement végétatif | 0,7 – 1,0 |\n"
                "| Mi-saison (floraison / fructification) | 1,0 – 1,2 |\n"
                "| Fin de saison (maturation) | 0,6 – 0,9 |\n\n"
                "---\n\n"
                "## Modes de culture\n\n"
                "Le mode de culture applique un **correcteur à l'ET₀** pour modéliser "
                "l'environnement réel de la plante.\n\n"
                "| Mode | Correcteur |\n"
                "|---|---|\n"
                "| Plein champ | 1,0 |\n"
                "| Paillage organique léger (5 cm) | 0,9 |\n"
                "| Paillage organique moyen (10 cm) | 0,8 |\n"
                "| Paillage organique épais (15 cm) | 0,7 |\n"
                "| Toile tissée ou film plastique | 0,7 |\n"
                "| Serre hiver | 0,5 |\n"
                "| Serre printemps / automne | 0,6 |\n"
                "| Serre été | 0,7 |\n\n"
                "Des modes personnalisés (correcteur libre) s'ajoutent dans **Mode de culture**.\n\n"
                "---\n\n"
                "## Calculateur de débit\n\n"
                "Le calculateur détermine le **débit en mm/m²/h** d'un système "
                "goutte-à-goutte à partir de ses caractéristiques physiques.\n\n"
                "**Paramètres d'entrée**\n"
                "- Débit goutteur (L/h)\n"
                "- Espacement entre goutteurs (cm)\n"
                "- Nombre de lignes et espacement inter-lignes (cm)\n"
                "- Longueur de ligne (m) et largeur de zone (m)\n\n"
                "Le résultat alimente directement le champ **Débit d'irrigation** "
                "de chaque zone (Paramètres)."
            ),
        },
        {
            "type": "markdown",
            "title": "Algorithme — Besoin en eau",
            "content": (
                "## Formule centrale\n\n"
                "`Besoin (mm) = max(0 ; ET₀_zone × Kc − Pluie efficace − Arrosage du jour − Bilan hydrique − Tampon sol)`\n\n"
                "`Durée (min) = min(Besoin / Débit × 60 ; Durée max)`\n\n"
                "---\n\n"
                "## 1 · ET₀ — Penman-Monteith FAO-56\n\n"
                "Calculée chaque cycle depuis la **prévision météo du jour**. "
                "Si l'entité météo expose `et0_mm` ou `evapotranspiration`, cette valeur est utilisée directement.\n\n"
                "| Entrée | Source météo | Défaut |\n"
                "|---|---|---|\n"
                "| Tmax (°C) | `temperature` forecast J0 | 25 °C |\n"
                "| Tmin (°C) | `templow` forecast J0 | Tmax − 12 °C |\n"
                "| Vent (km/h) | `wind_speed` | 7,2 km/h |\n"
                "| Pression (hPa) | `pressure` | 1013 hPa |\n"
                "| Couverture nuageuse (%) | `cloud_coverage` | 40 % |\n\n"
                "Étapes : Ra (rayonnement extra-terrestre) → Rs (Ångström-Prescott) "
                "→ Rn (bilan radiatif net) → ET₀ (équation PM FAO-56 eq. 6).\n\n"
                "---\n\n"
                "## 2 · Correcteur ET₀ de zone\n\n"
                "`ET₀_zone = ET₀ × et0_correction_factor`\n\n"
                "Le **mode de culture** initialise automatiquement ce facteur à la sélection. "
                "Il peut ensuite être ajusté manuellement par zone.\n\n"
                "| Mode | Facteur initial |\n"
                "|---|---|\n"
                "| Plein champ | 1,0 |\n"
                "| Paillage léger (5 cm) | 0,9 |\n"
                "| Paillage moyen (10 cm) | 0,8 |\n"
                "| Paillage épais / toile | 0,7 |\n"
                "| Serre été | 0,7 |\n"
                "| Serre printemps / automne | 0,6 |\n"
                "| Serre hiver | 0,5 |\n\n"
                "---\n\n"
                "## 3 · Coefficient cultural Kc\n\n"
                "Le Kc représente le besoin réel de la culture par rapport au gazon FAO de référence.\n\n"
                "**Mode manuel** — stade sélectionné par l'utilisateur → Kc fixe du stade.\n\n"
                "**Mode automatique** — stade déduit de la date de plantation et des durées "
                "de chaque stade (plein champ ou serre selon le mode de culture) :\n\n"
                "`jour_courant = today − date_plantation`  \n"
                "Parcours des stades dans l'ordre jusqu'à trouver le stade actif.\n\n"
                "---\n\n"
                "## 4 · Pluie efficace\n\n"
                "`Pluie_efficace = Pluie_prévue × (efficacité_pluie / 100)`\n\n"
                "- **Capteur prévision pluie** configuré → prioritaire sur le `precipitation` du forecast.\n"
                "- **Efficacité** (défaut 80 %) — réduire pour sol en pente ou très compact.\n"
                "- En mode **serre** : pluie efficace forcée à **0**.\n\n"
                "---\n\n"
                "## 5 · Bilan hydrique cumulatif (SWD)\n\n"
                "Mis à jour à **minuit** à partir des données réelles de la veille. "
                "Chaque nuit, la variation du jour est **accumulée** dans le solde courant "
                "au lieu d'être remplacée — ce qui élimine les oscillations d'arrosage.\n\n"
                "`Δ jour = (Pluie_j1 + Irrigation_j1) − ET₀_j1 × Kc`\n\n"
                "`Bilan_new = Bilan_old + Δ jour` (borné à [−RAW ; +RAW])\n\n"
                "Les bornes sont **dynamiques** : RAW = Réserve facilement utilisable, recalculée à chaque cycle "
                "selon le type de sol et la profondeur racinaire effective du stade courant "
                "(voir **§ 8 · Capacité sol** ci-dessous).\n\n"
                "| Source | Station locale configurée | Sinon |\n"
                "|---|---|---|\n"
                "| ET₀ J-1 | Recalculé depuis capteurs physiques | Valeur forecast mémorisée |\n"
                "| Pluie J-1 | Capteur pluie (historique HA) | Valeur forecast mémorisée |\n"
                "| Irrigation J-1 | Historique switch × débit (mm/h) | — |\n\n"
                "- **Bilan > 0** (surplus cumulé) → réduit le besoin du jour\n"
                "- **Bilan < 0** (déficit cumulé) → augmente le besoin du jour\n"
                "- Le capteur **Bilan hydrique** converge vers 0 quand l'arrosage est bien calé\n"
                "- Le bouton **Remise à zéro** réinitialise le solde si nécessaire\n\n"
                "---\n\n"
                "## 6 · Tampon sol\n\n"
                "Réserve minimale avant déclenchement de l'arrosage. "
                "Valeur typique : **2–8 mm** pour un sol argileux. "
                "Évite les arrosages pour des besoins très faibles.\n\n"
                "---\n\n"
                "## 7 · Profondeur racinaire (FAO-56)\n\n"
                "La profondeur racinaire détermine le **volume de sol exploité** par la plante "
                "et conditionne le calcul de la Réserve facilement utilisable (RAW).\n\n"
                "| Culture | Profondeur (cm) |\n"
                "|---|---|\n"
                "| Fraise | 25 |\n"
                "| Salade d'été | 30 |\n"
                "| Ail, Épinard, Framboise, Oignon | 40 |\n"
                "| Chou-fleur, Poireau, Pomme de terre | 50 |\n"
                "| Carotte, Haricot | 60 |\n"
                "| Courgette, Pois, Poivron, Tabac | 70 |\n"
                "| Aubergine, Concombre, Soja | 80 |\n"
                "| Betterave, Kiwi | 90 |\n"
                "| Colza, Courge, Maïs doux, Melon, Tomate, Tournesol | 100 |\n"
                "| Céréales d'hiver, Maïs grain, Noisetier | 120 |\n"
                "| Asperge, Pommier, Prunier | 150 |\n\n"
                "**Source** : Allen et al. — *Crop evapotranspiration* (FAO-56, 1998), Tableau 22.  \n"
                "La valeur retenue est la médiane de la plage FAO pour chaque culture.\n\n"
                "---\n\n"
                "## 8 · Capacité sol (RAW)\n\n"
                "La **Réserve facilement utilisable (RAW)** est la quantité d'eau extractible sans stress hydrique. "
                "Elle définit les bornes du bilan hydrique `[−RAW ; +RAW]` et s'affiche dans le capteur **Capacité sol (RAW)**.\n\n"
                "**Calcul :**\n\n"
                "`TAW (mm) = AWC (mm/m) × profondeur_effective (m)`  \n"
                "`RAW (mm) = 0,4 × TAW`\n\n"
                "**AWC par type de sol (FAO-56, mm/m) :**\n\n"
                "| Type de sol | AWC |\n"
                "|---|---|\n"
                "| Sable | 75 mm/m |\n"
                "| Sable limoneux | 100 mm/m |\n"
                "| Limon sableux | 130 mm/m |\n"
                "| Limon | 170 mm/m |\n"
                "| Limon fin | 175 mm/m |\n"
                "| Limon argileux | 155 mm/m |\n"
                "| Argile | 150 mm/m |\n\n"
                "**Profondeur effective progressive :**\n\n"
                "La profondeur effective est pondérée par les durées cumulées des stades :\n\n"
                "`profondeur_eff = 15 + (profondeur_max − 15) × (jours_cumulés_fin_stade / durée_totale_culture)`\n\n"
                "**Exemple — Tomate + limon (profondeur_max = 100 cm, durée totale = 135 j) :**\n\n"
                "| Stade | Durée | Jours cumulés | Prof. eff. | RAW |\n"
                "|---|---|---|---|---|\n"
                "| Plantation | 10 j | 10 j | 36 cm | 24,5 mm |\n"
                "| Reprise | 40 j | 50 j | 58 cm | 39,1 mm |\n"
                "| Floraison 3e bouquet | 50 j | 100 j | 79 cm | 53,5 mm |\n"
                "| Mi-récolte | 35 j | 135 j | 100 cm | 68,0 mm |\n\n"
                "**Source** : Allen et al. — FAO-56, Tableau 19 (AWC) et Tableau 22 (profondeurs)."
            ),
        },
        {
            "type": "markdown",
            "title": "Sommaire",
            "content": (
                "#### Comprendre\n"
                "- **Présentation**\n"
                "  Termes de la formule & modes\n\n"
                "- **Guide de démarrage**\n"
                "  Mise en route en 4 étapes\n\n"
                "---\n\n"
                "#### Programmation\n"
                "- **Pilotage des électrovannes**\n"
                "  Modes Manuel / Programmé / Auto\n\n"
                "- **Arrosage en cascade**\n"
                "  Séquencement automatique\n\n"
                "---\n\n"
                "#### Algorithme\n"
                "- **Formule centrale**\n"
                "  Besoin & durée\n\n"
                "- **ET₀ FAO-56**\n"
                "  Penman-Monteith\n\n"
                "- **Correcteur ET₀**\n"
                "  Mode de culture\n\n"
                "- **Kc & stades**\n"
                "  Manuel / automatique\n\n"
                "- **Pluie efficace**\n"
                "  Forecast & capteur\n\n"
                "- **Bilan hydrique (SWD)**\n"
                "  Solde cumulatif\n\n"
                "- **Tampon sol**\n"
                "  Seuil de déclenchement\n\n"
                "- **Profondeur racinaire**\n"
                "  Table FAO-56 par culture\n\n"
                "- **Capacité sol (RAW)**\n"
                "  AWC par type de sol, profondeur progressive\n\n"
                "---\n\n"
                "#### Référence\n"
                "- **Indicateurs de zone**\n"
                "  Lecture des capteurs\n\n"
                "- **Cultures & Stades**\n"
                "  Kc de référence FAO-56\n\n"
                "- **Modes de culture**\n"
                "  Correcteurs ET₀\n\n"
                "- **Calculateur de débit**\n"
                "  Système goutte-à-goutte"
            ),
        },
    ),
    "en": (
        {
            "type": "markdown",
            "title": "IrriSynk",
            "content": (
                "## Overview\n\n"
                "**IrriSynk** is a Home Assistant integration for **intelligent electrovalve irrigation management**.\n\n"
                "Every day, for each zone, it calculates the exact amount of water needed using the "
                "scientific **FAO-56** method (simplified Penman-Monteith), then **automatically controls "
                "the electrovalves** at the scheduled time — for the precise calculated or configured duration.\n\n"
                "Today's rain, cumulative water balance, crop growth stage, cultivation mode: everything is "
                "taken into account. If rain is sufficient, irrigation is cancelled. Surpluses and "
                "deficits accumulate in a running balance — eliminating irrigation oscillation.\n\n"
                "Three modes per zone — **Manual**, **Scheduled** or **Auto** —, plus a "
                "**cascade** mode to sequence zones one after another.\n\n"
                "### Formula terms\n\n"
                "`Need = ET₀ × Kc − Effective rain − Today's irrigation − Water balance − Soil buffer`\n\n"
                "| Term | Meaning |\n"
                "|---|---|\n"
                "| **ET₀** | Reference evapotranspiration from weather data |\n"
                "| **Kc** | Crop coefficient — depends on crop and growth stage |\n"
                "| **Effective rain** | Precipitation × effectiveness rate (default 80 %) |\n"
                "| **Today's irrigation** | mm already applied today (from switch history) |\n"
                "| **Water balance** | Cumulative surplus/deficit running total (SWD) |\n"
                "| **Soil buffer** | Soil water reserve before triggering irrigation |\n\n"
                "How each term is computed is detailed in the **Algorithm** card.\n\n"
                "---\n\n"
                "## Getting Started\n\n"
                "### 1 · Configure the zone\n"
                "In **Settings**, for each zone:\n"
                "- Assign the **electrovalve** (HA switch entity_id)\n"
                "- Enter the **irrigation flow rate** (mm/h) — use the Calculator\n"
                "- Set a **maximum duration** as a safety limit\n\n"
                "### 2 · Choose a crop\n"
                "- Select the **crop** planted in the zone\n"
                "- Choose the **cultivation mode** (open field, greenhouse, mulch…)\n"
                "- Set the **stage mode**: Manual or Automatic by days\n"
                "- In manual mode: select the current **phenological stage**\n\n"
                "### 3 · Enable automatic irrigation\n"
                "- In **Scheduling**, select **Auto** mode (calculated duration) or **Scheduled** mode (fixed duration)\n"
                "- Set the zone **start time**\n"
                "- In **Auto** mode, IrriSynk calculates and runs the optimal duration each day\n\n"
                "### 4 · Fine-tune parameters\n"
                "- **ET0 correction**: reduce if weather overestimates evaporation (e.g. 0.9)\n"
                "- **Rain effectiveness**: reduce for sloped or compacted soil\n"
                "- **Soil buffer**: increase for clay soil (typical 2–8 mm)\n\n"
                "---\n\n"
                "## Valve Control\n\n"
                "IrriSynk directly controls the Home Assistant switch entities linked to electrovalves. "
                "Each zone has three operating modes:\n\n"
                "| Mode | Behaviour |\n"
                "|---|---|\n"
                "| **Manual** | No automatic irrigation — the zone is managed by hand |\n"
                "| **Scheduled** | Valve opens at the configured time for a **fixed duration** |\n"
                "| **Auto** | Valve opens at the configured time for the **FAO-56 calculated duration** (zero if rain is sufficient) |\n\n"
                "The start time is set per zone in the **Scheduling** tab. "
                "The scheduler checks every minute for irrigations to start or stop.\n\n"
                "**Restart recovery**: if Home Assistant restarts during irrigation, "
                "the active irrigation is re-armed for the remaining duration; "
                "overdue irrigations are stopped automatically.\n\n"
                "---\n\n"
                "## Cascade Irrigation\n\n"
                "Cascade mode irrigates all eligible zones **sequentially** "
                "from a single global start time.\n\n"
                "**How it works:**\n"
                "1. Enable the **Cascade** switch in the Scheduling tab\n"
                "2. Set the **cascade start time**\n"
                "3. IrriSynk computes each zone's start time in order, "
                "with a **1-minute gap** between zones\n"
                "4. When a zone finishes, remaining zone times are **recalculated dynamically**\n\n"
                "Zones in **Manual** mode are excluded from the cascade. "
                "Zones in **Scheduled** mode use their fixed duration; "
                "zones in **Auto** mode use the FAO-56 calculated duration.\n\n"
                "---\n\n"
                "## Zone Indicators\n\n"
                "| Indicator | Role |\n"
                "|---|---|\n"
                "| ET₀ | Today's evapotranspiration (mm) |\n"
                "| Current Kc | Crop coefficient at current stage |\n"
                "| Water need | Amount to apply today (mm) |\n"
                "| Recommended duration | Calculated irrigation time from flow rate |\n"
                "| Effective rain | Precipitation counted in the calculation |\n"
                "| Water balance | Cumulative surplus/deficit running total (SWD) |\n"
                "| Confidence | ET₀ calculation reliability (%) |\n\n"
                "**Confidence < 70 %** — partial weather data: the calculation remains "
                "conservative and irrigation is not suppressed.\n\n"
                "---\n\n"
                "## Crops & Stages\n\n"
                "### Add a custom crop\n"
                "1. **Crops** → *New crop*: enter the name → **Create**\n"
                "2. *Add / Edit a stage* form → select the crop\n"
                "3. Choose **— (new stage)**, fill in: name, Kc, open field duration, greenhouse duration\n"
                "4. Click **Confirm** — repeat for each stage\n\n"
                "### Reference Kc values (FAO-56)\n\n"
                "| Phenological stage | Typical Kc |\n"
                "|---|---|\n"
                "| Initial (germination / emergence) | 0.3 – 0.5 |\n"
                "| Crop development | 0.7 – 1.0 |\n"
                "| Mid-season (flowering / fruiting) | 1.0 – 1.2 |\n"
                "| Late season (maturation) | 0.6 – 0.9 |\n\n"
                "---\n\n"
                "## Cultivation Modes\n\n"
                "The cultivation mode applies a **correction factor to ET₀** to model "
                "the actual growing environment.\n\n"
                "| Mode | Factor |\n"
                "|---|---|\n"
                "| Open field | 1.0 |\n"
                "| Light organic mulch (5 cm) | 0.9 |\n"
                "| Medium organic mulch (10 cm) | 0.8 |\n"
                "| Heavy organic mulch (15 cm) | 0.7 |\n"
                "| Woven cover or plastic film | 0.7 |\n"
                "| Greenhouse winter | 0.5 |\n"
                "| Greenhouse spring / autumn | 0.6 |\n"
                "| Greenhouse summer | 0.7 |\n\n"
                "Custom modes (free factor) can be added in **Cultivation Mode**.\n\n"
                "---\n\n"
                "## Flow Rate Calculator\n\n"
                "The calculator determines the **flow rate in mm/m²/h** for a drip system "
                "from its physical characteristics.\n\n"
                "**Input parameters**\n"
                "- Dripper flow rate (L/h)\n"
                "- Dripper spacing (cm)\n"
                "- Number of lines and line spacing (cm)\n"
                "- Line length (m) and zone width (m)\n\n"
                "The result feeds directly into the **Irrigation flow** field "
                "for each zone (Settings)."
            ),
        },
        {
            "type": "markdown",
            "title": "Algorithm — Water Need",
            "content": (
                "## Core formula\n\n"
                "`Need (mm) = max(0 ; ET₀_zone × Kc − Effective rain − Today's irrigation − Water balance − Soil buffer)`\n\n"
                "`Duration (min) = min(Need / Flow × 60 ; Max duration)`\n\n"
                "---\n\n"
                "## 1 · ET₀ — Penman-Monteith FAO-56\n\n"
                "Computed each cycle from **today's weather forecast**. "
                "If the weather entity exposes `et0_mm` or `evapotranspiration`, that value is used directly.\n\n"
                "| Input | Weather source | Default |\n"
                "|---|---|---|\n"
                "| Tmax (°C) | `temperature` forecast D0 | 25 °C |\n"
                "| Tmin (°C) | `templow` forecast D0 | Tmax − 12 °C |\n"
                "| Wind (km/h) | `wind_speed` | 7.2 km/h |\n"
                "| Pressure (hPa) | `pressure` | 1013 hPa |\n"
                "| Cloud cover (%) | `cloud_coverage` | 40 % |\n\n"
                "Steps: Ra (extra-terrestrial radiation) → Rs (Ångström-Prescott) "
                "→ Rn (net radiation balance) → ET₀ (PM FAO-56 eq. 6).\n\n"
                "---\n\n"
                "## 2 · Zone ET₀ correction factor\n\n"
                "`ET₀_zone = ET₀ × et0_correction_factor`\n\n"
                "The **cultivation mode** automatically sets this factor when selected. "
                "It can then be adjusted manually per zone.\n\n"
                "| Mode | Initial factor |\n"
                "|---|---|\n"
                "| Open field | 1.0 |\n"
                "| Light organic mulch (5 cm) | 0.9 |\n"
                "| Medium organic mulch (10 cm) | 0.8 |\n"
                "| Heavy organic mulch / cover | 0.7 |\n"
                "| Greenhouse summer | 0.7 |\n"
                "| Greenhouse spring / autumn | 0.6 |\n"
                "| Greenhouse winter | 0.5 |\n\n"
                "---\n\n"
                "## 3 · Crop coefficient Kc\n\n"
                "Kc represents the actual crop water need relative to the FAO reference grass.\n\n"
                "**Manual mode** — stage selected by user → fixed Kc.\n\n"
                "**Automatic mode** — stage derived from planting date and stage durations "
                "(open field or greenhouse durations depending on cultivation mode):\n\n"
                "`current_day = today − planting_date`  \n"
                "Stages are scanned in order until the active stage is found.\n\n"
                "---\n\n"
                "## 4 · Effective rain\n\n"
                "`Effective_rain = Forecast_rain × (rain_effectiveness / 100)`\n\n"
                "- **Forecast rain sensor** configured → takes priority over forecast `precipitation`.\n"
                "- **Effectiveness** (default 80 %) — reduce for sloped or compacted soil.\n"
                "- In **greenhouse** mode: effective rain forced to **0**.\n\n"
                "---\n\n"
                "## 5 · Cumulative water balance (SWD)\n\n"
                "Updated at **midnight** from yesterday's actual data. "
                "Each night, the day's variation is **accumulated** into the running balance "
                "rather than being replaced — eliminating irrigation oscillation.\n\n"
                "`Daily delta = (Rain_d-1 + Irrigation_d-1) − ET₀_d-1 × Kc`\n\n"
                "`Balance_new = Balance_old + daily delta` (clamped to [−RAW ; +RAW])\n\n"
                "Bounds are **dynamic**: RAW = Readily Available Water, recomputed each cycle "
                "from the soil type and the current stage's effective root depth "
                "(see **§ 8 · Soil capacity** below).\n\n"
                "| Source | Local station configured | Otherwise |\n"
                "|---|---|---|\n"
                "| ET₀ D-1 | Recomputed from physical sensors | Saved forecast value |\n"
                "| Rain D-1 | Rain sensor (HA history) | Saved forecast value |\n"
                "| Irrigation D-1 | Switch history × flow (mm/h) | — |\n\n"
                "- **Balance > 0** (cumulative surplus) → reduces today's need\n"
                "- **Balance < 0** (cumulative deficit) → increases today's need\n"
                "- The **Water balance** sensor converges to 0 when irrigation is well-calibrated\n"
                "- The **Reset** button reinitialises the balance if needed\n\n"
                "---\n\n"
                "## 6 · Soil buffer\n\n"
                "Minimum reserve before irrigation is triggered. "
                "Typical value: **2–8 mm** for clay soil. "
                "Prevents irrigation for very small needs.\n\n"
                "---\n\n"
                "## 7 · Root depth (FAO-56)\n\n"
                "Root depth determines the **soil volume explored** by the plant "
                "and drives the Readily Available Water (RAW) calculation.\n\n"
                "| Crop | Root depth (cm) |\n"
                "|---|---|\n"
                "| Strawberry | 25 |\n"
                "| Summer lettuce | 30 |\n"
                "| Garlic, Spinach, Raspberry, Onion | 40 |\n"
                "| Cauliflower, Leek, Potato | 50 |\n"
                "| Carrot, Bean | 60 |\n"
                "| Zucchini, Pea, Bell pepper, Tobacco | 70 |\n"
                "| Eggplant, Cucumber, Soybean | 80 |\n"
                "| Beet, Kiwi | 90 |\n"
                "| Rapeseed, Squash, Sweet corn, Melon, Tomato, Sunflower | 100 |\n"
                "| Winter cereals, Grain corn, Hazelnut | 120 |\n"
                "| Asparagus, Apple tree, Plum tree | 150 |\n\n"
                "**Source**: Allen et al. — *Crop evapotranspiration* (FAO-56, 1998), Table 22.  \n"
                "The value used is the median of the FAO range for each crop.\n\n"
                "---\n\n"
                "## 8 · Soil capacity (RAW)\n\n"
                "The **Readily Available Water (RAW)** is the amount of water extractable without plant stress. "
                "It sets the water balance bounds `[−RAW ; +RAW]` and is shown by the **Soil capacity (RAW)** sensor.\n\n"
                "**Calculation:**\n\n"
                "`TAW (mm) = AWC (mm/m) × effective_depth (m)`  \n"
                "`RAW (mm) = 0.4 × TAW`\n\n"
                "**AWC by soil type (FAO-56, mm/m):**\n\n"
                "| Soil type | AWC |\n"
                "|---|---|\n"
                "| Sandy | 75 mm/m |\n"
                "| Loamy sand | 100 mm/m |\n"
                "| Sandy loam | 130 mm/m |\n"
                "| Loam | 170 mm/m |\n"
                "| Silt loam | 175 mm/m |\n"
                "| Clay loam | 155 mm/m |\n"
                "| Clay | 150 mm/m |\n\n"
                "**Progressive effective root depth:**\n\n"
                "Effective depth is weighted by cumulative stage durations:\n\n"
                "`depth_eff = 15 + (depth_max − 15) × (cumulative_days_at_stage_end / total_crop_duration)`\n\n"
                "**Example — Tomato + loam (depth_max = 100 cm, total duration = 135 d):**\n\n"
                "| Stage | Duration | Cumul. days | Eff. depth | RAW |\n"
                "|---|---|---|---|---|\n"
                "| Planting | 10 d | 10 d | 36 cm | 24.5 mm |\n"
                "| Recovery | 40 d | 50 d | 58 cm | 39.1 mm |\n"
                "| 3rd truss flowering | 50 d | 100 d | 79 cm | 53.5 mm |\n"
                "| Mid-harvest | 35 d | 135 d | 100 cm | 68.0 mm |\n\n"
                "**Source**: Allen et al. — FAO-56, Table 19 (AWC) and Table 22 (root depths)."
            ),
        },
        {
            "type": "markdown",
            "title": "Contents",
            "content": (
                "#### Understanding\n"
                "- **Overview**\n"
                "  Formula terms & operating modes\n\n"
                "- **Getting Started**\n"
                "  4-step setup guide\n\n"
                "---\n\n"
                "#### Scheduling\n"
                "- **Valve Control**\n"
                "  Manual / Scheduled / Auto modes\n\n"
                "- **Cascade Irrigation**\n"
                "  Automatic sequencing\n\n"
                "---\n\n"
                "#### Algorithm\n"
                "- **Core formula**\n"
                "  Need & duration\n\n"
                "- **ET₀ FAO-56**\n"
                "  Penman-Monteith\n\n"
                "- **ET₀ correction**\n"
                "  Cultivation mode\n\n"
                "- **Kc & stages**\n"
                "  Manual / automatic\n\n"
                "- **Effective rain**\n"
                "  Forecast & sensor\n\n"
                "- **Water balance (SWD)**\n"
                "  Cumulative running total\n\n"
                "- **Soil buffer**\n"
                "  Trigger threshold\n\n"
                "- **Root depth**\n"
                "  FAO-56 table per crop\n\n"
                "- **Soil capacity (RAW)**\n"
                "  AWC by soil type, progressive depth\n\n"
                "---\n\n"
                "#### Reference\n"
                "- **Zone Indicators**\n"
                "  Reading sensor values\n\n"
                "- **Crops & Stages**\n"
                "  FAO-56 Kc reference table\n\n"
                "- **Cultivation Modes**\n"
                "  ET₀ correction factors\n\n"
                "- **Flow Rate Calculator**\n"
                "  Drip irrigation system"
            ),
        },
    ),
}


def _get_labels(coordinator: Any) -> dict[str, str]:
    lang = "en" if coordinator._is_english() else "fr"
    return _LABELS[lang]


def _param_groups(lbl: dict[str, str]) -> list[tuple[str, list[str]]]:
    return [
        (lbl["grp_general"],  ["zone_name"]),
        (lbl["grp_valve"],    ["switch_entity_id", "flow_mm_h", "max_duration_min"]),
        (lbl["grp_terrain"],  ["soil_type", "cultivation_mode", "et0_correction_factor", "rain_effectiveness_pct", "soil_buffer_mm"]),
        (lbl["grp_planting"], ["planting_date", "crop", "stage_mode", "stage"]),
        (lbl["grp_actions"],  ["delete_zone"]),
    ]


def _meteo_cards(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_ids: list[str],
    lbl: dict[str, str],
) -> list[dict]:
    """Carte Météo partagée (colonne droite de tous les onglets)."""
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{suffix}")

    def z(zone_id: str, key: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{zone_id}_{key}")

    def item(eid: str, name: str) -> dict:
        return {"entity": eid, "name": name}

    weather_eid = (
        coordinator.entry.options.get(CONF_WEATHER_ENTITY_ID)
        or coordinator.entry.data.get(CONF_WEATHER_ENTITY_ID, "")
    )
    entities: list[dict] = []
    if weather_eid:
        entities.append(item(weather_eid, lbl["ent_weather"]))
    if zone_ids and (rain_eid := z(zone_ids[0], "effective_rain_mm")):
        entities.append(item(rain_eid, lbl["ent_rain"]))
    if et0_eid := g("et0_daily"):
        entities.append(item(et0_eid, lbl["ent_et0"]))

    if not entities:
        return []
    return [{
        "type": "entities",
        "title": lbl["card_weather"],
        "show_header_toggle": False,
        "entities": entities,
    }]


def _zone_order_card(
    zone_ids: list[str],
    zone_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    """Custom drag-and-drop card for zone reordering."""
    return {
        "type": "custom:irrisynk-zone-order-card",
        "title": lbl["zone_order_title"],
        "zone_ids": zone_ids,
        "zone_names": zone_names,
    }


def _zones_config_cards(
    entry_id: str,
    uid_to_entity: dict[str, str],
    entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> list[dict]:
    """Carte Configuration pour la vue Zones (Pour toutes les zones + Ajouter une zone)."""
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{suffix}")

    def item(eid: str) -> dict:
        label = entity_own_names.get(eid, "")
        return {"entity": eid, "name": label} if label else {"entity": eid}

    entities: list[Any] = [{"type": "section", "label": lbl["sec_all_zones"]}]
    if eid := g("config_all_max_duration_min"):
        entities.append(item(eid))
    if eid := g("config_all_rain_effectiveness_pct"):
        entities.append(item(eid))
    if eid := g("config_all_soil_buffer_mm"):
        entities.append(item(eid))
    entities.append({"type": "divider"})
    if eid := g("config_add_zone"):
        entities.append(item(eid))

    return [{
        "type": "entities",
        "title": lbl["card_config"],
        "show_header_toggle": False,
        "entities": entities,
    }]


def _telegram_cards(
    entry_id: str,
    uid_to_entity: dict[str, str],
    entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> list[dict]:
    """Carte Telegram pour la vue Paramètres."""
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{suffix}")

    def item(eid: str) -> dict:
        label = entity_own_names.get(eid, "")
        return {"entity": eid, "name": label} if label else {"entity": eid}

    entities: list[Any] = [{"type": "section", "label": lbl["sec_telegram"]}]
    if eid := g("config_telegram_enabled"):
        entities.append(item(eid))
    if eid := g("config_telegram_chat_id"):
        entities.append(item(eid))
    if eid := g("config_telegram_notify_irrigations"):
        entities.append(item(eid))
    if eid := g("config_telegram_notify_unavailable"):
        entities.append(item(eid))

    return [{
        "type": "entities",
        "title": lbl["card_config"],
        "show_header_toggle": False,
        "entities": entities,
    }]


def _cascade_cards(
    entry_id: str,
    uid_to_entity: dict[str, str],
    entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> list[dict]:
    """Carte Configuration (Cascade + Pour toutes les zones) pour la vue Programmation."""
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{suffix}")

    def item(eid: str) -> dict:
        label = entity_own_names.get(eid, "")
        return {"entity": eid, "name": label} if label else {"entity": eid}

    def sec(key: str) -> dict:
        return {"type": "section", "label": lbl[key]}

    entities: list[Any] = [sec("sec_all_zones")]
    if eid := g("config_all_zone_mode"):
        entities.append(item(eid))
    if eid := g("config_all_recalculate"):
        entities.append(item(eid))
    if eid := g("config_all_reset"):
        entities.append(item(eid))
    return [{
        "type": "entities",
        "title": lbl["card_config"],
        "show_header_toggle": False,
        "entities": entities,
    }]



# --- Onglet 1 : Accueil (résumé rapide) ---

def _build_accueil_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_ids: list[str],
    zone_names: dict[str, str],
    _entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def z(zone_id: str, key: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{zone_id}_{key}")

    # --- Blocs détail par zone (switch inclus en tête) ---
    zone_cards: list[dict] = []
    for zone_id in zone_ids:
        device_name = zone_names.get(zone_id, f"{coordinator.entry.title} – {zone_id}")

        tiles: list[dict] = []
        if switch_eid := coordinator.zone_states[zone_id].switch_entity_id:
            tiles.append({"type": "tile", "entity": switch_eid, "name": device_name})
        if eid := z(zone_id, "start_time"):
            tiles.append({"type": "tile", "entity": eid, "name": lbl["acc_scheduled"]})
        if eid := z(zone_id, "effective_duration_min"):
            tiles.append({"type": "tile", "entity": eid, "name": lbl["acc_duration"]})
        if eid := z(zone_id, "water_need_mm"):
            tiles.append({"type": "tile", "entity": eid, "name": lbl["acc_need"]})
        if eid := z(zone_id, "irrigation_today_mm"):
            tiles.append({"type": "tile", "entity": eid, "name": lbl["acc_irrigation"]})
        if eid := z(zone_id, "recalculate"):
            tiles.append({"type": "tile", "entity": eid, "name": lbl["btn_recalculate"]})

        zone_cards.append({
            "type": "vertical-stack",
            "cards": [
                {"type": "markdown", "content": f"## {device_name}"},
                {"type": "grid", "columns": 2, "square": False, "cards": tiles},
            ],
        })

    return {
        "title": lbl["view_home"],
        "path": "accueil",
        "icon": "mdi:home",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": zone_cards},
            {
                "column_span": 1,
                "cards": _meteo_cards(entry_id, coordinator, uid_to_entity, zone_ids, lbl) + (
                    [_zone_order_card(zone_ids, zone_names, lbl)] if len(zone_ids) > 1 else []
                ),
            },
        ],
    }


# --- Onglet 2 : Programmation (détail complet par zone) ---

def _build_programmation_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_ids: list[str],
    zone_names: dict[str, str],
    entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def z(zone_id: str, key: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{zone_id}_{key}")

    def item(eid: str, name: str | None = None) -> dict:
        label = name or entity_own_names.get(eid, "")
        return {"entity": eid, "name": label} if label else {"entity": eid}

    def sec(key: str) -> dict:
        return {"type": "section", "label": lbl[key]}

    zone_cards: list[dict] = []

    for zone_id in zone_ids:
        device_name = zone_names.get(zone_id, f"{coordinator.entry.title} – {zone_id}")
        entities: list[Any] = []

        entities.append(sec("sec_schedule"))

        if eid := z(zone_id, "zone_mode"):
            entities.append(item(eid))
        if eid := z(zone_id, "start_time"):
            entities.append(item(eid))
        if (sched_eid := z(zone_id, "scheduled_duration_min")) and (mode_eid := z(zone_id, "zone_mode")):
            row: dict = {"entity": sched_eid}
            if label := entity_own_names.get(sched_eid):
                row["name"] = label
            entities.append({
                "type": "conditional",
                "conditions": [{"condition": "state", "entity": mode_eid, "state": "scheduled"}],
                "row": row,
            })
        for key in ["recommended_duration_min"]:
            if eid := z(zone_id, key):
                entities.append(item(eid))

        entities.append(sec("sec_culture"))

        for key in ["crop", "current_stage", "kc_current"]:
            if eid := z(zone_id, key):
                entities.append(item(eid))

        entities.append(sec("sec_balance"))

        for key in ["water_need_mm", "irrigation_today_mm", "confidence",
                    "soil_water_balance_mm", "soil_capacity_mm"]:
            if eid := z(zone_id, key):
                entities.append(item(eid))

        entities.append(sec("sec_actions"))

        if eid := z(zone_id, "recalculate"):
            entities.append(item(eid))
        if eid := z(zone_id, "reset_stats"):
            entities.append(item(eid))

        zone_cards.append({
            "type": "entities",
            "title": device_name,
            "show_header_toggle": False,
            "entities": entities,
        })

    right_cards = _cascade_cards(entry_id, uid_to_entity, entity_own_names, lbl)

    return {
        "title": lbl["view_programmation"],
        "path": "programmation",
        "icon": "mdi:calendar-clock",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": zone_cards},
            {"column_span": 1, "cards": right_cards},
        ],
    }


# --- Vue Zones (configuration par zone) ---

def _build_zones_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_ids: list[str],
    zone_names: dict[str, str],
    entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def z(zone_id: str, key: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{zone_id}_{key}")

    def item(eid: str, name: str | None = None) -> dict:
        label = name or entity_own_names.get(eid, "")
        return {"entity": eid, "name": label} if label else {"entity": eid}

    zone_cards: list[dict] = []

    for zone_id in zone_ids:
        device_name = zone_names.get(zone_id, f"{coordinator.entry.title} – {zone_id}")
        entities: list[Any] = []
        for group_label, keys in _param_groups(lbl):
            entities.append({"type": "section", "label": group_label})
            for key in keys:
                if eid := z(zone_id, key):
                    entities.append(item(eid))

        zone_cards.append({
            "type": "entities",
            "title": device_name,
            "show_header_toggle": False,
            "entities": entities,
        })

    return {
        "title": lbl["view_zones"],
        "path": "zones",
        "icon": "mdi:sprinkler-variant",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": zone_cards},
            {"column_span": 1, "cards": _zones_config_cards(entry_id, uid_to_entity, entity_own_names, lbl)},
        ],
    }


# --- Vue Paramètres (Telegram uniquement) ---

def _build_parametres_view(
    entry_id: str,
    uid_to_entity: dict[str, str],
    entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    return {
        "title": lbl["view_settings"],
        "path": "parametres",
        "icon": "mdi:cog",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            {"column_span": 1, "cards": _telegram_cards(entry_id, uid_to_entity, entity_own_names, lbl)},
        ],
    }


# --- Onglet 3 : Statistiques ---

def _build_statistiques_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_ids: list[str],
    zone_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def z(zone_id: str, key: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_{zone_id}_{key}")

    stat_cards: list[dict] = []

    for zone_id in zone_ids:
        device_name = zone_names.get(zone_id, f"{coordinator.entry.title} – {zone_id}")

        if balance_eid := z(zone_id, "soil_water_balance_mm"):
            stat_cards.append({
                "type": "statistics-graph",
                "title": f"{lbl['stat_balance']} J-1 – {device_name}",
                "entities": [balance_eid],
                "stat_types": ["mean"],
                "period": "day",
                "days_to_show": 7,
                "chart_type": "line",
            })

    return {
        "title": lbl["view_stats"],
        "path": "statistiques",
        "icon": "mdi:chart-line",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": stat_cards},
            {"column_span": 1, "cards": _meteo_cards(
                entry_id, coordinator, uid_to_entity, zone_ids, lbl
            )},
        ],
    }


# --- Onglet 4 : Calculateur ---

def _build_calculateur_view(
    entry_id: str,
    uid_to_entity: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_calculator_{suffix}")

    input_keys = [
        ("flow_lh",           "calc_lbl_flow_lh"),
        ("dripper_spacing_cm","calc_lbl_dripper_spacing"),
        ("line_count",        "calc_lbl_line_count"),
        ("line_spacing_cm",   "calc_lbl_line_spacing"),
        ("line_length_m",     "calc_lbl_line_length"),
        ("zone_width_m",      "calc_lbl_zone_width"),
    ]

    entities: list[Any] = [{"type": "section", "label": lbl["calc_inputs_section"]}]
    for key, lbl_key in input_keys:
        if eid := g(key):
            entities.append({"entity": eid, "name": lbl[lbl_key]})

    if btn_eid := g("run"):
        entities.append({"type": "divider"})
        entities.append({"entity": btn_eid, "name": lbl["calc_lbl_run"]})

    entities.append({"type": "section", "label": lbl["calc_result_section"]})
    if result_eid := g("result_mm_h"):
        entities.append({"entity": result_eid, "name": lbl["calc_lbl_result"]})

    card = {
        "type": "entities",
        "title": lbl["calc_card_title"],
        "show_header_toggle": False,
        "entities": entities,
    }

    return {
        "title": lbl["view_calculator"],
        "path": "calculateur",
        "icon": "mdi:calculator",
        "type": "sections",
        "max_columns": 2,
        "sections": [
            {"column_span": 1, "cards": [card]},
        ],
    }


# --- Onglet 5 : Mode de culture ---

def _build_cult_modes_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_cult_modes_{suffix}")

    # --- Left column: one card per mode ---
    mode_cards: list[dict] = []
    lang = "en" if coordinator._is_english() else "fr"

    # One card per built-in mode (read-only, no delete button)
    for mode_name, et0 in _BUILTIN_MODES[lang]:
        mode_cards.append({
            "type": "markdown",
            "title": mode_name,
            "content": f"{lbl['cult_modes_et0_label']}{et0}",
        })

    # One card per custom mode with its delete button
    for mode in coordinator.custom_cultivation_modes:
        delete_eid = g(f"delete_{mode.name}")
        info_card: dict = {
            "type": "markdown",
            "title": mode.name,
            "content": f"{lbl['cult_modes_et0_label']}{mode.et0_factor}",
        }
        if delete_eid:
            mode_cards.append({
                "type": "vertical-stack",
                "cards": [
                    info_card,
                    {
                        "type": "entities",
                        "show_header_toggle": False,
                        "entities": [
                            {"entity": delete_eid, "name": lbl["cult_modes_delete_btn"]},
                        ],
                    },
                ],
            })
        else:
            mode_cards.append(info_card)

    # --- Right card: add form (entity names overridden for clean display) ---
    form_entities: list[Any] = []
    if name_eid := g("form_name"):
        form_entities.append({"entity": name_eid, "name": lbl["cult_modes_field_name"]})
    if et0_eid := g("form_et0"):
        form_entities.append({"entity": et0_eid, "name": lbl["cult_modes_field_et0"]})
    if btn_eid := g("add"):
        form_entities.append({"type": "divider"})
        form_entities.append({"entity": btn_eid, "name": lbl["cult_modes_field_add"]})

    form_card = {
        "type": "entities",
        "title": lbl["cult_modes_form_title"],
        "show_header_toggle": False,
        "entities": form_entities,
    }

    return {
        "title": lbl["view_cult_modes"],
        "path": "modes-culture",
        "icon": "mdi:layers-triple-outline",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": mode_cards},
            {"column_span": 1, "cards": [form_card]},
        ],
    }


# --- Onglet 5 : Cultures ---

def _build_cultures_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_crops_{suffix}")

    # --- Left column ---
    crop_cards: list[dict] = []

    def _stage_lines(stages, label_fn, kc_lbl: str, dur_lbl: str) -> str:
        lines = []
        for s in stages:
            name = label_fn(s)
            open_d = s.duration_days_open_field if s.duration_days_open_field is not None else "—"
            gh_d = s.duration_days_greenhouse if s.duration_days_greenhouse is not None else "—"
            lines.append(f"**{name}** &nbsp;·&nbsp; {kc_lbl}{s.kc} &nbsp;·&nbsp; {dur_lbl}{open_d}/{gh_d}")
        return "  \n".join(lines) if lines else "*(aucun stade)*"

    # One card per custom crop: each stage as a delete-stage button row (no section separators)
    for crop in coordinator.custom_crops:
        delete_crop_eid = g(f"delete_{crop.crop_id}")
        card_entities: list[Any] = []
        for stage in crop.stages:
            stage_eid = g(f"delete_stage_{crop.crop_id}_{stage.stage_id}")
            if stage_eid:
                open_d = stage.duration_days_open_field if stage.duration_days_open_field is not None else "—"
                gh_d = stage.duration_days_greenhouse if stage.duration_days_greenhouse is not None else "—"
                row_name = f"{stage.label}  ·  {lbl['crops_kc_label']}{stage.kc}  ·  {lbl['crops_duration_label']}{open_d}/{gh_d}"
                card_entities.append({"entity": stage_eid, "name": row_name})
        if delete_crop_eid:
            card_entities.append({"type": "divider"})
            card_entities.append({"entity": delete_crop_eid, "name": lbl["crops_delete_btn"]})
        depth_suffix = f" — {crop.root_depth_cm} cm" if crop.root_depth_cm else ""
        crop_cards.append({
            "type": "entities",
            "title": f"{crop.name}{depth_suffix}",
            "show_header_toggle": False,
            "entities": card_entities,
        })

    # Built-in catalog: one card per crop, sorted alphabetically
    builtin_sorted = sorted(coordinator.catalog.crops, key=lambda c: coordinator._crop_label(c))
    for crop in builtin_sorted:
        crop_label = coordinator._crop_label(crop)
        depth_line = (
            f"*{lbl['crops_root_depth_label']}{crop.root_depth_cm} cm*  \n\n"
            if crop.root_depth_cm is not None else ""
        )
        stage_content = _stage_lines(
            crop.stages,
            coordinator._stage_label,
            lbl["crops_kc_label"],
            lbl["crops_duration_label"],
        )
        crop_cards.append({
            "type": "markdown",
            "title": crop_label,
            "content": depth_line + stage_content,
        })

    # --- Right column: two form cards ---
    # Card 1: create a new crop
    create_entities: list[Any] = []
    if name_eid := g("form_crop_name"):
        create_entities.append({"entity": name_eid, "name": lbl["crops_field_crop_name"]})
    if root_depth_eid := g("form_crop_root_depth"):
        create_entities.append({"entity": root_depth_eid, "name": lbl["crops_root_depth_label"].rstrip(" : ")})
    if btn_eid := g("create_crop"):
        create_entities.append({"type": "divider"})
        create_entities.append({"entity": btn_eid, "name": lbl["crops_field_create"]})
    create_card = {
        "type": "entities",
        "title": lbl["crops_form_crop_title"],
        "show_header_toggle": False,
        "entities": create_entities,
    }

    # Card 2: add or edit a stage (unified form)
    edit_stage_entities: list[Any] = []
    if edit_crop_eid := g("edit_stage_crop"):
        edit_stage_entities.append({"entity": edit_crop_eid, "name": lbl["crops_field_edit_crop"]})
    if edit_stage_eid := g("edit_stage_stage"):
        edit_stage_entities.append({"entity": edit_stage_eid, "name": lbl["crops_field_edit_stage"]})
    edit_stage_entities.append({"type": "divider"})
    if edit_name_eid := g("edit_stage_name"):
        edit_stage_entities.append({"entity": edit_name_eid, "name": lbl["crops_field_edit_name"]})
    if edit_kc_eid := g("edit_stage_kc"):
        edit_stage_entities.append({"entity": edit_kc_eid, "name": lbl["crops_field_kc"]})
    if edit_dur_open_eid := g("edit_stage_dur_open"):
        edit_stage_entities.append({"entity": edit_dur_open_eid, "name": lbl["crops_field_duration_open"]})
    if edit_dur_gh_eid := g("edit_stage_dur_gh"):
        edit_stage_entities.append({"entity": edit_dur_gh_eid, "name": lbl["crops_field_duration_gh"]})
    if save_eid := g("save_stage"):
        edit_stage_entities.append({"type": "divider"})
        edit_stage_entities.append({"entity": save_eid, "name": lbl["crops_field_save_stage"]})
    edit_stage_card = {
        "type": "entities",
        "title": lbl["crops_form_edit_stage_title"],
        "show_header_toggle": False,
        "entities": edit_stage_entities,
    }

    return {
        "title": lbl["view_crops"],
        "path": "cultures",
        "icon": "mdi:sprout",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": crop_cards},
            {"column_span": 1, "cards": [create_card, edit_stage_card]},
        ],
    }


# --- Onglet Cascades ---

def _build_cascades_view(
    entry_id: str,
    coordinator: Any,
    uid_to_entity: dict[str, str],
    zone_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    def g(suffix: str) -> str | None:
        return _uid(uid_to_entity, f"{entry_id}_cascade_{suffix}")

    def item(eid: str, name: str | None = None) -> dict:
        label = name or ""
        return {"entity": eid, "name": label} if label else {"entity": eid}

    # --- Left column: one vertical-stack card per cascade ---
    cascade_cards: list[dict] = []

    for cascade in coordinator.cascades:
        cid = cascade.cascade_id
        card_entities: list[Any] = []

        if eid := g(f"{cid}_enabled"):
            card_entities.append(item(eid, lbl["cascade_enabled_label"]))
        if eid := g(f"{cid}_time"):
            card_entities.append(item(eid, lbl["cascade_time_label"]))
        if eid := g(f"{cid}_zone_selector"):
            card_entities.append({"entity": eid, "name": lbl["cascade_add_zone_label"]})
        if eid := g(f"{cid}_add_zone"):
            card_entities.append({"entity": eid, "name": lbl["cascade_add_zone_btn"]})
        if card_entities:
            card_entities.append({"type": "divider"})
        if eid := g(f"{cid}_delete"):
            card_entities.append({"entity": eid, "name": lbl["cascade_delete_btn"]})

        config_card: dict = {
            "type": "entities",
            "title": cascade.name,
            "show_header_toggle": False,
            "entities": card_entities,
        }

        # Zone-order custom card for this cascade (drag-to-reorder + × remove buttons)
        cascade_zones = [z for z in cascade.zone_ids if z in coordinator.zone_states]

        cards: list[dict] = [config_card]
        if cascade_zones:
            # Prefer user-set name (name_by_user) then device name then zone_id
            zone_names_map = {
                z: coordinator._zone_display_name(z) or zone_names.get(z) or z
                for z in cascade_zones
            }
            cards.append({
                "type": "custom:irrisynk-zone-order-card",
                "cascade_id": cid,
                "zone_ids": cascade_zones,
                "zone_names": zone_names_map,
                "title": lbl["cascade_zone_order_title"],
            })

        cascade_cards.append({"type": "vertical-stack", "cards": cards})

    if not cascade_cards:
        cascade_cards = [{"type": "markdown", "content": lbl["cascade_empty"]}]

    # --- Right column: create form ---
    form_entities: list[Any] = []
    if name_eid := g("form_name"):
        form_entities.append({"entity": name_eid, "name": lbl["cascade_form_name"]})
    if time_eid := g("form_time"):
        form_entities.append({"entity": time_eid, "name": lbl["cascade_form_time"]})
    if btn_eid := g("create"):
        form_entities.append({"type": "divider"})
        form_entities.append({"entity": btn_eid, "name": lbl["cascade_create_btn"]})

    form_card = {
        "type": "entities",
        "title": lbl["cascade_form_title"],
        "show_header_toggle": False,
        "entities": form_entities,
    }

    return {
        "title": lbl["view_cascades"],
        "path": "cascades",
        "icon": "mdi:order-numeric-ascending",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": cascade_cards},
            {"column_span": 1, "cards": [form_card]},
        ],
    }


# --- Onglet Wiki ---

def _build_wiki_view(
    _entry_id: str,
    coordinator: Any,
    _uid_to_entity: dict[str, str],
    _zone_ids: list[str],
    _zone_names: dict[str, str],
    _entity_own_names: dict[str, str],
    lbl: dict[str, str],
) -> dict:
    lang = "en" if coordinator._is_english() else "fr"
    content_card, algo_card, nav_card = _WIKI_CONTENT[lang]
    return {
        "title": lbl["view_wiki"],
        "path": "wiki",
        "icon": "mdi:book-open-outline",
        "type": "sections",
        "max_columns": 3,
        "sections": [
            {"column_span": 2, "cards": [content_card, algo_card]},
            {"column_span": 1, "cards": [nav_card]},
        ],
    }
