"""Hearings services (spec 0023 #1).

Status, sequence, dates and counts are written only here. Every service that
assigns a sequence, counts capacity or changes a hearing's status takes the
court lock first, then the hearing rows by id (#11.5).

* ``listing`` — the orders contract: hold, change, release, confirm, cancel (#7).
* ``courtroom`` — start, pass over, end, bulk actions, attendance, board (#5, #6).
* ``reschedule`` — single and bulk court-side moves (#8).
* ``calendar`` — business date, sitting days, capacity, load, calendar entries (#4, #9).
"""
