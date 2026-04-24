# api/index.py - Vercel WSGI Handler
import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aniwatch_coat_scraper import create_app

app = create_app()

# Vercel handler
def handler(request, context):
    """WSGI handler for Vercel"""
    return app(request.environ, lambda status, headers: (status, headers))