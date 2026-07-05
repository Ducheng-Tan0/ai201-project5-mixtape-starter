"""Reproduces Issue #1: listening streak resets on Sundays.
Runs the exact conditional from streak_service.update_listening_streak()
against controlled dates."""
from datetime import date

def new_streak(current, last_date, today):
    # --- exact logic copied from update_listening_streak() ---
    days = (today - last_date).days
    if days == 0:
        return current                              # already listened today
    elif days == 1 and today.weekday() != 6:        # consecutive day -> increment
        return current + 1
    else:
        return 1                                    # gap -> reset

print("weekday(): Mon=0 ... Sat=5, Sun=6\n")

# A consecutive-day listen that LANDS on a Sunday:
print("Listened Sat 2026-07-04, listens Sun 2026-07-05 (consecutive):")
print("   new streak =", new_streak(3, date(2026,7,4), date(2026,7,5)), " (EXPECTED 4)")

# The same consecutive-day listen on a non-Sunday:
print("Listened Sun 2026-07-05, listens Mon 2026-07-06 (consecutive):")
print("   new streak =", new_streak(3, date(2026,7,5), date(2026,7,6)), " (EXPECTED 4)")



""" Issue 3 """

"""Reproduces Issue #3: multi-tag songs appear multiple times in search.
Runs the exact query shape from search_service.search_songs()."""
import sqlite3

c = sqlite3.connect("instance/mixtape.db")
query = "Borough"   # matches artist "Borough Kings" (song has 3 tags)

# LEFT JOIN to song_tags, filter on title/artist, NO DISTINCT -- as in search_songs()
sql = """
  SELECT s.id, s.title FROM song s
  LEFT JOIN song_tags st ON s.id = st.song_id
  WHERE s.title LIKE ? OR s.artist LIKE ?
"""
rows = c.execute(sql, (f"%{query}%", f"%{query}%")).fetchall()

print(f"Search q={query!r} -> service returns {len(rows)} rows:")
for r in rows:
    print("   ", r[1])
print("\n   Distinct songs actually matching:", len(set(r[0] for r in rows)))



"""Issue 5 """


"""Reproduces Issue #5: the last song of every playlist is missing.
Replicates get_playlist_songs(): order by position, then apply songs[:-1]."""
import sqlite3

c = sqlite3.connect("instance/mixtape.db")

sql = """
  SELECT s.title, pe.position FROM song s
  JOIN playlist_entries pe ON s.id = pe.song_id
  JOIN playlist p ON p.id = pe.playlist_id
  WHERE p.name = 'Late Night Vibes'
  ORDER BY pe.position ASC
"""
songs = c.execute(sql).fetchall()
print(f"Playlist has {len(songs)} songs (ordered by position):")
for t, pos in songs:
    print(f"   pos {pos}: {t}")

returned = songs[:-1]   # the exact slice the service applies
print(f"\nService returns songs -> {len(returned)} songs")
print(f"DROPPED: {songs[-1][0]!r} (position {songs[-1][1]})")


