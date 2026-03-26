#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Models
"""
# ========================================================
# IMPORTS
# ========================================================
from datetime import datetime, timezone
from sqlalchemy.orm import declarative_base
from sqlalchemy import (Column, Integer, String, DateTime, Text, Boolean,
                        UniqueConstraint)


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

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc),
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
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc),
                        nullable=False)


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        nullable=False)


class DisabledPosition(Base):
    __tablename__ = "disabled_positions"
    code = Column(String(20), primary_key=True, index=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
