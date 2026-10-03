from tokencat.cli import create_dashboard_app
from tokencat_native.dashboard import load_dashboard

app = create_dashboard_app(load_dashboard)
