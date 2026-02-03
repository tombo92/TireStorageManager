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
from sqlalchemy import Column, Integer, String, DateTime, Text, UniqueConstraint


# ========================================================
# GLOABALS
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
