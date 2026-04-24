# api/index.py - Vercel Serverless Function
import sys
sys.path.append('/var/task')

from aniwatch_coat_scraper import create_app

app = create_app()

def handler(event, context):
    """Vercel serverless function handler"""
    return app(event, context)