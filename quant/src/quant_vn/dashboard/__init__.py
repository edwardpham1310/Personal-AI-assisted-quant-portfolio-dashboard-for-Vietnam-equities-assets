"""Dashboard analysis and static HTML rendering."""

from .analysis import DashboardSignal, analyze_symbol, analyze_universe
from .static import build_dashboard_html, save_dashboard

__all__ = [
    "DashboardSignal",
    "analyze_symbol",
    "analyze_universe",
    "build_dashboard_html",
    "save_dashboard",
]
