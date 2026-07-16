#!/usr/bin/env python
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Models
"""
# ========================================================
# IMPORTS
# ========================================================
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

# ========================================================
# GLOBALS
# ========================================================
Base = declarative_base()


# ========================================================
# CLASSES (MODELS from BASE)
# ========================================================
class WheelSet(Base):
    """
    Wheelset Class
    """
    __tablename__ = "wheel_sets"

    id = Column(Integer, primary_key=True)
    customer_name = Column(String(200), nullable=False, index=True)
    license_plate = Column(String(50), nullable=False, index=True)
    car_type = Column(String(200), nullable=False, index=True)
    note = Column(Text, nullable=True)
    storage_position = Column(String(20), nullable=False, unique=True,
                              index=True)
    # Extended tire details (optional — enabled via Settings.enable_tire_details)
    tire_manufacturer = Column(String(100), nullable=True)
    tire_size = Column(String(50), nullable=True)
    tire_age = Column(String(20), nullable=True)
    # season: 'sommer', 'winter', 'allwetter'
    season = Column(String(20), nullable=True)
    # rim_type: 'stahl', 'alu'
    rim_type = Column(String(20), nullable=True)
    exchange_note = Column(Text, nullable=True)
    # Tire renewal flag — highlighted in all overviews, filterable
    tires_need_renewal = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=lambda: datetime.now(UTC),
                        nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC),
                        nullable=False)

    __table_args__ = (
        UniqueConstraint("storage_position", name="uq_storage_position"),
    )


class Settings(Base):
    """
    Settings Class
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    backup_interval_minutes = Column(Integer, nullable=False, default=60)
    backup_copies = Column(Integer, nullable=False, default=10)
    dark_mode = Column(Boolean, nullable=False, default=False)
    auto_update = Column(Boolean, nullable=False, default=True)
    language = Column(String(10), nullable=False, default="de")
    custom_positions_json = Column(Text, nullable=True)
    enable_tire_details = Column(Boolean, nullable=False, default=False)
    enable_seasonal_tracking = Column(Boolean, nullable=False, default=False)
    # JSON list of individually enabled optional field names (when
    # enable_tire_details is False).  Empty/null = only defaults shown.
    # Valid keys: tire_manufacturer, tire_size, tire_age, season,
    # rim_type, exchange_note (see Settings.OPTIONAL_FIELDS)
    visible_fields_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC),
                        onupdate=lambda: datetime.now(UTC),
                        nullable=False)

    # All optional field keys that can be individually toggled.
    # "note" is excluded — it is always visible as a core field.
    OPTIONAL_FIELDS = (
        "tire_manufacturer", "tire_size", "tire_age",
        "season", "rim_type", "exchange_note",
    )

    @property
    def visible_fields(self) -> list[str]:
        """Return list of individually enabled optional field names."""
        import json
        if not self.visible_fields_json:
            return []
        try:
            return json.loads(self.visible_fields_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @visible_fields.setter
    def visible_fields(self, fields: list[str]) -> None:
        import json
        valid = [f for f in fields if f in self.OPTIONAL_FIELDS]
        self.visible_fields_json = json.dumps(valid) if valid else None

    def is_field_visible(self, field: str) -> bool:
        """Check if a specific optional field should be shown.

        When enable_tire_details is True, ALL fields are visible.
        Otherwise, only individually selected fields are visible.
        """
        if self.enable_tire_details:
            return True
        return field in self.visible_fields


class AuditLog(Base):
    """
    AuditLog Class
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    # 'create', 'update', 'delete', 'backup'
    action = Column(String(50), nullable=False)
    # optional (bei backup None)
    wheelset_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC),
                        nullable=False)


class DisabledPosition(Base):
    __tablename__ = "disabled_positions"
    code = Column(String(20), primary_key=True, index=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
