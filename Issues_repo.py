"""
Issues_repo.py — Mixtape Bug Hunt reproduction scripts

Standalone reproductions for the three bugs I fixed (Issues #1, #3, #5).
Each section intentionally replicates the ORIGINAL buggy behavior so the bug can
be observed directly — the real fixes live in services/, not here.

Run from the repo root:
    python Issues_repo.py
"""

from datetime import date
import sqlite3

DB = "instance/mixtape.db"


# ---------------------------------------------------------------------------
# Issue #1 — Listening streak resets on Sundays   (services/streak_service.py)
# ---------------------------------------------------------------------------
# Root cause: the increment branch required `today.weekday() != 6`, and
# weekday() returns 6 for Sunday, so a consecutive-day listen that lands on a
# Sunday falls through to the reset branch and the streak drops to 1.
#
# EXPECTED OUTPUT:
#   Sat->Sun (consecutive): new streak = 1   (EXPECTED 4)   <- the bug
#   Sun->Mon (consecutive): new streak = 4                  <- fine
def new_streak(current, last_date, today):
    # exact conditional copied from the ORIGINAL update_listening_streak()
    days = (today - last_date).days
    if days == 0:
        return current                      # already listened today
    elif days == 1 and today.weekday() != 6:  # <- buggy Sunday clause
        return current + 1                  # consecutive day -> increment
    else:
        return 1                            # gap -> reset

print("=== Issue #1: streak reset on Sundays ===")
print("Sat->Sun (consecutive): new streak =",
      new_streak(3, date(2026, 7, 4), date(2026, 7, 5)), " (EXPECTED 4)")
print("Sun->Mon (consecutive): new streak =",
      new_streak(3, date(2026, 7, 5), date(2026, 7, 6)), " (EXPECTED 4)")
print()


# ---------------------------------------------------------------------------
# Issue #3 — Multi-tag songs duplicated in search  (services/search_service.py)
# ---------------------------------------------------------------------------
# Root cause: the query joined song_tags (one row per tag) with no DISTINCT, so
# a song with N tags came back as N identical rows.
#
# EXPECTED OUTPUT: 3 rows all named "Crown Heights Anthem"; 1 distinct song.
print("=== Issue #3: duplicate search results ===")
conn = sqlite3.connect(DB)
query = "Borough"   # matches artist "Borough Kings" (a 3-tag song)
sql = """
    SELECT s.id, s.title FROM song s
    LEFT JOIN song_tags st ON s.id = st.song_id
    WHERE s.title LIKE ? OR s.artist LIKE ?
"""
rows = conn.execute(sql, (f"%{query}%", f"%{query}%")).fetchall()
print(f"Search q={query!r} -> {len(rows)} rows:")
for r in rows:
    print("   ", r[1])
print("Distinct songs actually matching:", len(set(r[0] for r in rows)))
conn.close()
print()


# ---------------------------------------------------------------------------
# Issue #5 — Last playlist song dropped   (services/playlist_service.py)
# ---------------------------------------------------------------------------
# Root cause: get_playlist_songs returned songs[:-1], slicing off the last
# (highest-position) song on every read.
#
# EXPECTED OUTPUT: 7 songs stored, 6 returned, "Free Throws" (pos 7) dropped.
print("=== Issue #5: last playlist song missing ===")
conn = sqlite3.connect(DB)
sql = """
    SELECT s.title, pe.position FROM song s
    JOIN playlist_entries pe ON s.id = pe.song_id
    JOIN playlist p ON p.id = pe.playlist_id
    WHERE p.name = 'Late Night Vibes'
    ORDER BY pe.position ASC
"""
songs = conn.execute(sql).fetchall()
print(f"Playlist has {len(songs)} songs (ordered by position):")
for t, pos in songs:
    print(f"   pos {pos}: {t}")
returned = songs[:-1]   # the exact slice the ORIGINAL service applied
print(f"Service returned songs[:-1] -> {len(returned)} songs")
print(f"DROPPED: {songs[-1][0]!r} (position {songs[-1][1]})")
conn.close()
