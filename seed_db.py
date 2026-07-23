"""
Seed the SQLite database with the three user movie URLs so they are automatically monitored.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import database as db
from app.models import MovieConfig

async def run():
    # Make sure DB and tables exist
    await db.init_db()
    
    # Get existing movies to avoid duplicate seeding
    existing = await db.get_all_movies()
    existing_names = {m.name for m in existing}
    
    movies_to_seed = [
        MovieConfig(
            name="Spider-Man: Brand New Day (Regular/3D)",
            city="Chennai",
            bms_url="https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260801?etCodes=*&language=english&refEventCode=ET00502600",
            district_url="https://www.district.in/movies/spider-man-brand-new-day-movie-tickets-in-chennai-MV194537?frmtid=rrfdpndypd&fromdate=2026-08-01",
            interval=180,
            enabled=True
        ),
        MovieConfig(
            name="Spider-Man: Brand New Day (EPIQ 3D)",
            city="Chennai",
            bms_url="https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day-epiq-3d/buytickets/ET00505581/20260801",
            district_url="",
            interval=180,
            enabled=True
        )
    ]
    
    for movie in movies_to_seed:
        if movie.name not in existing_names:
            movie_id = await db.add_movie(movie)
            print(f"Added movie: {movie.name} with ID {movie_id}")
        else:
            print(f"Movie already exists in DB: {movie.name}")

if __name__ == "__main__":
    asyncio.run(run())
