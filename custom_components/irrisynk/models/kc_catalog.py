# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Kc catalog loading and validation."""

from __future__ import annotations

import json
import csv
import unicodedata
from pathlib import Path

from .domain import CropDefinition, KcCatalog, StageDefinition


class CatalogValidationError(ValueError):
    """Raised when catalog content is invalid."""


def load_catalog_from_path(path: Path) -> KcCatalog:
    """Load and validate Kc catalog from JSON file."""
    if path.suffix.lower() == ".csv":
        return _parse_catalog_csv(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_catalog(raw)


def _slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip().replace("'", "").replace("-", "_").replace("/", "_")
    out = []
    for char in text:
        out.append(char if char.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def _humanize_slug(value: str) -> str:
    """Convert slug-like identifiers into title labels."""
    return value.replace("_", " ").strip().title()


def _parse_catalog_csv(path: Path) -> KcCatalog:
    raw_text = path.read_text(encoding="utf-8")
    delimiter = ";" if raw_text.splitlines()[0].count(";") > raw_text.splitlines()[0].count(",") else ","
    reader = csv.DictReader(raw_text.splitlines(), delimiter=delimiter)

    crops: dict[str, dict] = {}
    for row in reader:
        crop_name = (row.get("Culture") or "").strip()
        stage_label = (row.get("Stade début") or row.get("Stade") or "").strip()
        if not crop_name or not stage_label:
            continue

        crop_id = _slugify(crop_name)
        stage_id = _slugify(stage_label)
        open_days = (row.get("Durée plein champ (jours)") or "").strip()
        greenhouse_days = (row.get("Durée serre (jours)") or "").strip()
        kc_value = (row.get("Kc") or "").strip()
        if not kc_value:
            continue

        crop_payload = crops.setdefault(
            crop_id,
            {
                "crop_id": crop_id,
                "label": crop_name,
                "label_en": _humanize_slug(crop_id),
                "stages": [],
            },
        )
        crop_payload["stages"].append(
            {
                "stage_id": stage_id,
                "label": stage_label,
                "label_en": _humanize_slug(stage_id),
                "duration_days": int(open_days) if open_days else None,
                "duration_days_open_field": int(open_days) if open_days else None,
                "duration_days_greenhouse": int(greenhouse_days) if greenhouse_days else None,
                "kc": float(kc_value),
            }
        )

    ordered = sorted(crops.values(), key=lambda crop: crop["label"])
    return parse_catalog({"version": 1, "crops": ordered})


def parse_catalog(raw: dict) -> KcCatalog:
    """Parse raw catalog payload into typed domain objects."""
    if "version" not in raw or "crops" not in raw:
        raise CatalogValidationError("Catalog must include 'version' and 'crops'.")

    version = int(raw["version"])
    crop_objs: list[CropDefinition] = []
    seen_crops: set[str] = set()

    for crop in raw["crops"]:
        crop_id = str(crop["crop_id"])
        if crop_id in seen_crops:
            raise CatalogValidationError(f"Duplicate crop_id: {crop_id}")
        seen_crops.add(crop_id)

        stages: list[StageDefinition] = []
        seen_stages: set[str] = set()
        for index, stage in enumerate(crop["stages"]):
            stage_id = str(stage["stage_id"])
            if stage_id in seen_stages:
                raise CatalogValidationError(
                    f"Duplicate stage_id '{stage_id}' for crop '{crop_id}'"
                )
            seen_stages.add(stage_id)

            duration_days_raw = stage.get("duration_days")
            duration_days = None if duration_days_raw is None else int(duration_days_raw)
            duration_open_field_raw = stage.get("duration_days_open_field", duration_days_raw)
            duration_greenhouse_raw = stage.get("duration_days_greenhouse", duration_days_raw)
            duration_days_open_field = (
                None if duration_open_field_raw is None else int(duration_open_field_raw)
            )
            duration_days_greenhouse = (
                None if duration_greenhouse_raw is None else int(duration_greenhouse_raw)
            )
            if duration_days is not None and duration_days <= 0:
                raise CatalogValidationError(
                    f"Invalid duration_days for {crop_id}/{stage_id}"
                )
            if duration_days_open_field is not None and duration_days_open_field <= 0:
                raise CatalogValidationError(
                    f"Invalid duration_days_open_field for {crop_id}/{stage_id}"
                )
            if duration_days_greenhouse is not None and duration_days_greenhouse <= 0:
                raise CatalogValidationError(
                    f"Invalid duration_days_greenhouse for {crop_id}/{stage_id}"
                )
            if duration_days is None and index != len(crop["stages"]) - 1:
                raise CatalogValidationError(
                    f"Only last stage may have null duration_days ({crop_id}/{stage_id})"
                )

            kc = float(stage["kc"])
            if kc <= 0:
                raise CatalogValidationError(f"Kc must be > 0 for {crop_id}/{stage_id}")

            stages.append(
                StageDefinition(
                    stage_id=stage_id,
                    label=str(stage["label"]),
                    label_en=stage.get("label_en"),
                    duration_days=duration_days,
                    duration_days_open_field=duration_days_open_field,
                    duration_days_greenhouse=duration_days_greenhouse,
                    kc=kc,
                )
            )

        if not stages:
            raise CatalogValidationError(f"Crop '{crop_id}' has no stage.")

        root_depth_raw = crop.get("root_depth_cm")
        root_depth_cm = int(root_depth_raw) if root_depth_raw is not None else None

        crop_objs.append(
            CropDefinition(
                crop_id=crop_id,
                label=str(crop["label"]),
                label_en=crop.get("label_en"),
                stages=tuple(stages),
                root_depth_cm=root_depth_cm,
            )
        )

    if not crop_objs:
        raise CatalogValidationError("Catalog has no crops.")

    return KcCatalog(version=version, crops=tuple(crop_objs))
