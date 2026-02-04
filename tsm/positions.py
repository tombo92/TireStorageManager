#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Date    : 2026-02-03 06:54:54
# @Author  : Tom Brandherm (https://github.com/tombo92)
# @Link    : https://github.com/tombo92/TireStorageManager
"""
Postions Logic
"""
# ========================================================
# IMPORTS
# ========================================================
import re
from tsm.models import WheelSet, DisabledPosition


# ========================================================
# GLOABALS
# ========================================================
CONTAINER_NUMBERS = [1, 2, 3, 4]
CONTAINER_SIDES = ["R", "L"]
LEVELS = ["O", "M", "U"]
CONTAINER_POSITIONS = ["LL", "L", "MM", "M", "RR", "R"]

GARAGE_SHELVES = list(range(1, 9))  # 1..8
GARAGE_POSITIONS = ["L", "M", "R"]

RE_CONTAINER = re.compile(r"^C([1-4])([RL])([OMU])(LL|L|MM|M|RR|R)$")
RE_GARAGE = re.compile(r"^GR([1-8])([OMU])([LMR])$")
ALL_POSITIONS = None
SORTED_POSITIONS = None


# ========================================================
# FUNCTIONS
# ========================================================
def all_valid_positions():
    pos = []
    for c in CONTAINER_NUMBERS:
        for side in CONTAINER_SIDES:
            for lvl in LEVELS:
                for p in CONTAINER_POSITIONS:
                    pos.append(f"C{c}{side}{lvl}{p}")
    for g in GARAGE_SHELVES:
        for lvl in LEVELS:
            for p in GARAGE_POSITIONS:
                pos.append(f"GR{g}{lvl}{p}")
    return pos


def is_valid_position(code: str) -> bool:
    return bool(RE_CONTAINER.match(code) or RE_GARAGE.match(code))


def position_sort_key(code: str):
    if code.startswith("C"):
        m = RE_CONTAINER.match(code)
        if not m:
            return (0, 999, 9, 9, 9)
        c = int(m.group(1))
        side = m.group(2)
        lvl = m.group(3)
        p = m.group(4)
        side_order = {"R": 0, "L": 1}[side]
        lvl_order = {"O": 0, "M": 1, "U": 2}[lvl]
        pos_order = {v: i for i, v in enumerate(CONTAINER_POSITIONS)}[p]
        return (0, c, side_order, lvl_order, pos_order)
    else:
        m = RE_GARAGE.match(code)
        if not m:
            return (1, 999, 9, 9)
        g = int(m.group(1))
        lvl = m.group(2)
        p = m.group(3)
        lvl_order = {"O": 0, "M": 1, "U": 2}[lvl]
        pos_order = {v: i for i, v in enumerate(GARAGE_POSITIONS)}[p]
        return (1, g, lvl_order, pos_order)


def get_occupied_positions(db) -> set[str]:
    rows = db.query(WheelSet.storage_position).all()
    return {r[0] for r in rows}


def get_disabled_positions(db) -> set[str]:
    rows = db.query(DisabledPosition.code).all()
    return {r[0] for r in rows}


def disable_position(db, code: str, reason: str | None = None) -> bool:
    """
    Mark a position as unusable. Returns True if created, False if already disabled.
    """
    if not is_valid_position(code):
        return False
    if db.query(DisabledPosition).get(code):
        return False
    db.add(DisabledPosition(code=code, reason=reason))
    db.commit()
    return True


def enable_position(db, code: str) -> bool:
    """
    Remove a position from the disabled list. Returns True if removed, else False.
    """
    row = db.query(DisabledPosition).get(code)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def is_usable_position(db, code: str) -> bool:
    """
    Structurally valid and not disabled.
    """
    return is_valid_position(code) and (code not in get_disabled_positions(db))


def first_free_position(db):
    occupied = get_occupied_positions(db)
    disabled = get_disabled_positions(db)
    for code in SORTED_POSITIONS:
        if code not in occupied and code not in disabled:
            return code
    return None


def free_positions(db):
    occupied = get_occupied_positions(db)
    disabled = get_disabled_positions(db)
    return [code for code in SORTED_POSITIONS if code not in occupied and code not in disabled]


# ========================================================
# GENERATE POSITIONS AND SORT
# ========================================================
ALL_POSITIONS = all_valid_positions()
SORTED_POSITIONS = sorted(ALL_POSITIONS, key=position_sort_key)
