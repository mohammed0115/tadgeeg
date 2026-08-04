"""Read-side query logic, kept out of the view functions.

A view's job is: parse the request, call something, render the answer. When it
also assembles the answer, three things follow — the logic cannot be reused by
an API or a Celery task without copying it, it cannot be tested without an HTTP
client, and the file grows until nobody reads it whole. `page_views.py` reached
6,081 lines and 130 ORM calls before this package existed.

Modules here take plain arguments (an organisation, a date range) and return
plain data. No request, no response, no template.
"""
