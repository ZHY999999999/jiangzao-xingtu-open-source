#!/usr/bin/env python3
"""Refresh the authoritative, complete THS classification evidence snapshot.

Usage: python scripts/refresh-data.py --trade-date 20260918 --financial-period 20260630
All options are delegated to enrich-evidence.py. The application derives its
visible graph from evidence-data.json; this entry point never regenerates the
legacy capped stardata.js catalog. Credentials are read only by the shared
HTTPS client from TUSHARE_TOKEN. A failed core collection keeps the old snapshot.
"""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('enrich-evidence.py')), run_name='__main__')
