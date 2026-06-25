"""Flask application — Quill writing workflow API.

All routes are organized into blueprints under ``blueprints/``.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass  # python-dotenv not installed — rely on env vars from systemd/shell


def create_app() -> Flask:
    """Application factory."""
    # Initialize logging first — before any other imports trigger log calls
    from .logging_config import setup_logging
    setup_logging()

    _pkg_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(_pkg_dir / "templates"),
        static_folder=str(_pkg_dir / "static"),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_prefix=1)

    # Register blueprints
    from .blueprints.pieces import bp as pieces_bp
    from .blueprints.agents import bp as agents_bp
    from .blueprints.runs import bp as runs_bp
    from .blueprints.export import bp as export_bp
    from .blueprints.dashboard import bp as dashboard_bp

    app.register_blueprint(pieces_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(dashboard_bp)

    return app


app = create_app()


@app.context_processor
def inject_base():
    """Inject base URL prefix for static files behind a reverse proxy."""
    prefix = request.headers.get("X-Forwarded-Prefix", "")
    return {"base": prefix}


def main():
    """Run the server."""
    app.run(host="0.0.0.0", port=8325, debug=False)


if __name__ == "__main__":
    main()
