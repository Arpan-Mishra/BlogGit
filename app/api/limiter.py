"""
Rate limiter singleton shared across the FastAPI application.

Import ``limiter`` wherever you need the @limiter.limit() decorator.
The limiter must also be attached to ``app.state.limiter`` in main.py.

Default key: client IP address.  Override per-endpoint if needed.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
