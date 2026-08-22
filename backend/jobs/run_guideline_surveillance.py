"""Scheduler entry point. Run from backend with PYTHONPATH=. python jobs/run_guideline_surveillance.py"""
import asyncio
from guideline_surveillance_agent import run_surveillance_check

if __name__ == "__main__":
    reviews = asyncio.run(run_surveillance_check())
    print(f"new_pending_reviews={len(reviews)}")
