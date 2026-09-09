# Temporary helper: paste the following at the END of app/main.py if not present:
#
# from app.notes_routes import register_notes_routes
# register_notes_routes(app, get_current_user, get_ed_notification_count, log_activity)
#
# After this is present in main.py, this file can be deleted.
WIRE_SNIPPET = """
# Team Notes + @mention
from app.notes_routes import register_notes_routes
register_notes_routes(app, get_current_user, get_ed_notification_count, log_activity)
"""
