"""Dash application entry point."""

import dash
import dash_bootstrap_components as dbc

from dashboard.data_loader import get_dashboard_stats
from dashboard.layouts import make_layout
from dashboard.callbacks import register_callbacks
from analysis.config import DASH_HOST, DASH_PORT, DASH_DEBUG


def create_app() -> dash.Dash:
    """Create and configure the Dash application."""
    app = dash.Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY],
        title="AI in K-12 Education Dashboard",
        suppress_callback_exceptions=True,
    )

    stats = get_dashboard_stats()
    app.layout = make_layout(stats)
    register_callbacks(app)

    return app


def main():
    app = create_app()
    print(f"Starting dashboard at http://{DASH_HOST}:{DASH_PORT}")
    app.run(host=DASH_HOST, port=DASH_PORT, debug=DASH_DEBUG)


if __name__ == "__main__":
    main()
