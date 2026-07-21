"""
Update the date in the SQLite database for existing movies.
"""
import sqlite3

def run():
    conn = sqlite3.connect("data/showpulser.db")
    cursor = conn.cursor()
    
    # Update regular movie url to point to 20260801
    cursor.execute(
        "UPDATE movies SET bms_url = ? WHERE name = ?",
        ("https://in.bookmyshow.com/movies/chennai/spider-man-brand-new-day/buytickets/ET00502600/20260801", 
         "Spider-Man: Brand New Day (Regular/3D)")
    )
    conn.commit()
    print("Updated movie records:", cursor.rowcount)
    
    # Also delete cached snapshots for this movie so it fetches fresh ones for the new URL
    cursor.execute("DELETE FROM snapshots WHERE movie_id = 1")
    conn.commit()
    print("Deleted old snapshots to force clean fetch:", cursor.rowcount)
    
    conn.close()

if __name__ == "__main__":
    run()
