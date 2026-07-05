# AI Usage

I used Claude Code (Opus 4.8) throughout, mainly for **codebase orientation and guided
debugging** rather than writing code for me.

**Orientation (Milestone 1):** I had it summarize each service file and trace real call chains
(e.g. how adding a song to a playlist creates a notification). It drafted the codebase map, which
I checked against the source. It correctly flagged a subtlety I'd have missed — that *sharing* a
song doesn't itself emit a notification — and I confirmed that in `models.py` and
`notification_service.py`.

**Reproduction (Milestone 2):** I had it write standalone reproduction scripts. When I pasted the
streak script into `streak_service.py` I hit `No module named 'app'`; working through *why* taught
me how Python resolves imports from the script's own directory, and that reproduction scripts must
be standalone files run from the repo root — not pasted into modules that import `app`.

**Investigation (Milestone 3):** For each bug I read the suspect function first, then used AI to
confirm my understanding — that `datetime.weekday()` returns 6 for Sunday, and that a SQL join
over a one-to-many relationship multiplies result rows. It proposed the minimal fixes (drop the
weekday clause, remove the unnecessary join, remove the `[:-1]` slice), which I applied and
committed myself as separate commits. I also was not too farmiliar with the `from flask_sqlalchemy import SQLAlchemy` 
and claude helped me understand the sytax and functions within. 

**Where I verified / corrected it:** The AI couldn't run Flask or pytest in its sandbox at first,
so every "tests pass" claim had to be confirmed by running `pytest tests/` (13 passed). I also
rejected one edit it proposed to a source file I wanted left alone. The debugging discipline —
reproduce, verify, check side-effects — was mine, and I confirmed every claim against the running
code.

---

# Mixtape — Codebase Map

Mixtape is a **social music-sharing API** built with Flask + SQLAlchemy on SQLite. Users
share songs, build collaborative playlists, rate each other's songs, follow friends, and
maintain daily listening "streaks." It's a pure JSON API (no frontend/templates) — every
endpoint returns `jsonify(...)`.

The codebase is organized in **three layers**, and data flows in one direction:

```
HTTP request
   │
   ▼
routes/*.py      ← Flask blueprints: parse input, format JSON, map errors to status codes
   │
   ▼
services/*.py    ← business logic: load ORM objects, apply rules, commit
   │
   ▼
models.py        ← SQLAlchemy models + association tables
   │
   ▼
SQLite (instance/mixtape.db)
```

---

## Main files and what each does

### Top level

| File | Responsibility |
|------|----------------|
| [app.py](app.py) | Flask **application factory** (`create_app`). Configures the DB URI (env `DATABASE_URL`, default `sqlite:///mixtape.db`), initializes the shared `db = SQLAlchemy()` object, registers the four blueprints under URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls `db.create_all()`. |
| [models.py](models.py) | All SQLAlchemy models and the three association tables. The single source of truth for the data model (details below). |
| [seed_data.py](seed_data.py) | Standalone script (`python seed_data.py`) that drops/recreates all tables and populates 5 users, 25 songs (with 0 / 1 / 3+ tags), 3 playlists, friendships, listening events (recent + old), streaks, and a sample notification. The seed data is deliberately shaped to exercise edge cases. |
| [README.md](README.md) | Project brief — this is **Project 5: Mixtape Bug Hunt**, a starter repo with five planted bugs, all living in `services/`. |
| [requirements.txt](requirements.txt) | Dependencies (Flask, Flask-SQLAlchemy, pytest). |

### Data model — [models.py](models.py)

Seven models, all using **string UUID primary keys** (`generate_uuid()`), plus **three association tables**:

- **`User`** — `username`, `email`, `listening_streak`, `last_listened_at`. Owns relationships to shared songs, ratings, listening events, notifications, and playlists. `friends` is a **self-referential many-to-many** via the `friendships` table, declared `lazy="dynamic"` (so `user.friends` is a query, not a list).
- **`Song`** — `title`, `artist`, `album`, `genre`, `shared_by` (FK to the user who shared it), `shared_at`, `share_note`. `to_dict()` flattens tags to a list of name strings.
- **`Tag`** — just `name`; linked to songs via `song_tags`.
- **`ListeningEvent`** — a row per play: `user_id`, `song_id`, `listened_at`. This is the raw material for both the feed and streaks.
- **`Rating`** — `user_id`, `song_id`, `score` (1–5), with a **`UniqueConstraint(user_id, song_id)`** so a user can only have one rating per song. Ratings are their **own table**, not a column on `Song`.
- **`Playlist`** — `name`, `created_by`, `is_collaborative` (default `True`).
- **`Notification`** — `user_id` (recipient), `notification_type`, `body`, `read` flag.

**Association tables** (defined at the top of the file):
- `friendships` — symmetric user↔user (seeded as two rows per friendship for bidirectionality).
- `song_tags` — song↔tag.
- `playlist_entries` — playlist↔song, but **richer than a plain join**: it carries `position` (explicit ordering), `added_by`, and `added_at`. So a playlist's song order is intentional, not insertion order, and the table records who added each song.

### Routes — thin controllers in [routes/](routes/)

Every route follows the same shape: read `request` args/JSON → validate presence → call a service → `jsonify` the result → translate `ValueError` into a 400/404. **No business logic lives here.**

| Blueprint / file | Prefix | Endpoints → service call |
|------|--------|--------------------------|
| [routes/songs.py](routes/songs.py) | `/songs` | `GET /search?q=` → `search_service.search_songs`; `GET /<id>` → `search_service.get_song`; `POST /<id>/rate` → `notification_service.rate_song`; `POST /<id>/listen` → `streak_service.record_listening_event` |
| [routes/playlists.py](routes/playlists.py) | `/playlists` | `POST /` → `create_playlist`; `GET /<id>` → `get_playlist`; `GET /<id>/songs` → `get_playlist_songs`; `POST /<id>/songs` → `notification_service.add_to_playlist` |
| [routes/users.py](routes/users.py) | `/users` | `GET /<id>` → reads `User` directly; `GET /<id>/streak` → `get_streak`; `GET /<id>/notifications` → `get_notifications`; `POST /notifications/<id>/read` → `mark_as_read` |
| [routes/feed.py](routes/feed.py) | `/feed` | `GET /<id>/listening-now` → `get_friends_listening_now`; `GET /<id>/activity` → `get_activity_feed` |

### Services — business logic in [services/](services/)

| File | Responsibility |
|------|----------------|
| [services/search_service.py](services/search_service.py) | `search_songs(query)` — case-insensitive `ILIKE` on title **or** artist, joined to tags; `get_song(id)`. |
| [services/streak_service.py](services/streak_service.py) | `record_listening_event()` creates a `ListeningEvent` and calls `update_listening_streak()`, which applies the consecutive-calendar-day streak rules; `get_streak()` reads the current value. |
| [services/feed_service.py](services/feed_service.py) | `get_friends_listening_now()` — friends' events within 24h, newest-first, **deduped to one per friend**; `get_activity_feed(limit=20)` — most recent N friend events, no time filter, no dedup. |
| [services/notification_service.py](services/notification_service.py) | `create_notification()` (low-level); `add_to_playlist()` — adds a song and notifies its sharer; `rate_song()` — upserts a rating; `get_notifications()` / `mark_as_read()`. |
| [services/playlist_service.py](services/playlist_service.py) | `create_playlist()`, `get_playlist()` (metadata), `get_playlist_songs()` (ordered by `position`), `get_user_playlists()`. |

### Tests — [tests/](tests/)

`pytest` suites at the service layer: [test_streaks.py](tests/test_streaks.py), [test_search.py](tests/test_search.py), [test_playlists.py](tests/test_playlists.py). They test service functions directly, matching where the bugs live.

---

## Data flow: adding a song to a playlist triggers a notification

This is the clearest cross-cutting flow — one request touches routes, two services, and three tables.

1. **Request** — `POST /playlists/<playlist_id>/songs` with JSON `{"song_id": ..., "added_by": ...}`.
2. **Route** — [`add_song()` in routes/playlists.py](routes/playlists.py#L43) parses `song_id` and `added_by`, returns 400 if either is missing, then calls `notification_service.add_to_playlist(playlist_id, song_id, added_by)`.
3. **Service** — [`add_to_playlist()` in notification_service.py](services/notification_service.py#L35):
   - Loads the `Song`, adding `User`, and `Playlist`; raises `ValueError` (→ 400) if any is missing.
   - Appends the song to `playlist.songs` (writes a `playlist_entries` row) and commits.
   - **Notification trigger:** if `song.shared_by != added_by_user_id`, it calls `create_notification(...)` targeting the song's **original sharer** with type `"song_added_to_playlist"` and a human-readable body. You don't get notified for adding your own song.
4. **Persist** — `create_notification()` writes a `Notification` row and commits.
5. **Response** — route returns `{"message": "Song added to playlist"}`, 201.
6. **Read side (later)** — the sharer calls `GET /users/<id>/notifications`, which flows through `get_notifications()` and returns the notification's `to_dict()`.

> Note on terminology: in this app, **sharing** a song (setting `Song.shared_by`) does *not* itself
> emit a notification — notifications are triggered by *others interacting with* a shared song
> (adding it to a playlist, and — once Issue #4 is fixed — rating it).

### Related flow: rating a song
`POST /songs/<id>/rate` → [`rate()` in routes/songs.py](routes/songs.py#L29) → `notification_service.rate_song()`, which validates the 1–5 score and **upserts** a `Rating` (updates the existing row if the user already rated this song, thanks to the unique constraint; otherwise inserts).

---

## Patterns I noticed

1. **Strict layering, thin routes.** Every route immediately delegates to a service. Routes only parse input and format output; all business rules and DB writes live in `services/`. The one exception is `GET /users/<id>`, which reads a `User` directly in the route — a minor break from the pattern.

2. **Services take IDs, return dicts.** Service functions accept string IDs (not ORM objects), load what they need via `db.session.get(...)`, and return **JSON-ready dicts** via each model's `to_dict()`. This keeps the ORM contained below the service boundary — routes never touch SQLAlchemy objects (again except `get_user`).

3. **Errors as `ValueError`.** "Not found" / invalid input is signaled by `raise ValueError(...)` in services, and every route wraps calls in `try/except ValueError` to map them to 404 (reads) or 400 (writes). There's no shared error handler — it's repeated per route.

4. **Application-factory + shared `db` + blueprints.** `db` is created once in `app.py` and imported everywhere; `create_app()` wires blueprints with URL prefixes. This is the standard Flask factory pattern and makes test setup (custom config) easy.

5. **UUID string PKs everywhere**, generated app-side via `generate_uuid()` rather than by the DB.

6. **`to_dict()` as the serialization convention.** Each model owns its own JSON shape. Notably, `Song.to_dict()` flattens tags to name strings, and `User.to_dict()` deliberately omits `email`.

7. **Rich join table.** `playlist_entries` carries `position`/`added_by`/`added_at` instead of being a bare link table — a deliberate choice so playlists have explicit ordering and provenance.

8. **Circular-import avoidance via local imports.** `notification_service.add_to_playlist()` imports `Playlist` and `playlist_service` *inside the function* to sidestep an import cycle between the two service modules.

9. **Bugs are concentrated in the service layer.** Per the README, this is a bug-hunt starter with five planted issues, all in `services/`. Two are visible on a first read: `playlist_service.get_playlist_songs()` returns `songs[:-1]` (drops the last song — Issue #5), and `streak_service.update_listening_streak()` has a `today.weekday() != 6` (Sunday) condition that prevents legitimate streak increments (Issue #1). The seed data is intentionally built to surface these.

---

# Bug Fixes : Root Cause Analysis

I chose to fix **Issue #1 (streak reset)**, **Issue #3 (duplicate search results)**, and
**Issue #5 (last playlist song missing)** .
These three distinct root-cause categories are 
date-boundary logic, SQL join cardinality, and an off-by-one slice.

Each entry has five fields: issue, how I reproduced it, how I found the root cause, the root
cause, and the fix + side-effect check.

## Issue #1 — My listening streak keeps resetting

- **How I reproduced it:** The streak update is pure date logic, so I isolated the exact
  conditional from `update_listening_streak()` and ran it against controlled dates instead of
  firing HTTP requests. I simulated a user with `listening_streak = 3` who listened *yesterday*
  and listens again *today*, varying only which weekday "today" is:
  - listened Sat 2026-07-04, listens Sun 2026-07-05 (consecutive) → streak became **1** (expected 4) 
  - listened Sun 2026-07-05, listens Mon 2026-07-06 (consecutive) → streak became **4** 

  The only variable that changed the outcome was whether the listen landed on a Sunday. End-to-end
  equivalent in the seeded DB: `darius` has `listening_streak = 3` and `last_listened_at = 2026-07-03`;
  a `POST /songs/<id>/listen` as darius on any Sunday drops his streak to 1.

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


- **How I found the root cause:** The report pointed at streak behavior, so I followed the
  "listen" path top-down: `POST /songs/<id>/listen` in `routes/songs.py` → `record_listening_event()`
  in `streak_service.py` → which delegates the math to `update_listening_streak(user, now)`. That
  function has four branches; the only one that could wrongly reset a *valid* streak was
  `elif days_since_last == 1 and today.weekday() != 6`. I confirmed it was the exact cause (not just
  a suspicious line) by copying the conditional verbatim into a standalone script and running it on
  controlled dates: a Sat→Sun consecutive listen returned 1 while Sun→Mon returned 4. Since
  `weekday()` returns 6 only for Sunday, the `!= 6` clause was provably the switch.
- **The root cause:** Python's `datetime.weekday()` returns 6 for Sunday (Mon=0 … Sat=5, Sun=6).
  The increment branch required `days_since_last == 1 and today.weekday() != 6`, so on any Sunday
  the second condition was `False` even for a legitimate consecutive-day listen. Execution then fell
  through to the `else`, which sets `listening_streak = 1`. Result: a user's streak reset to 1
  whenever their listen landed on a Sunday, despite having listened the day before. The weekday
  check enforced no real rule — a streak should grow on any consecutive calendar day.
- **My fix and side-effect check:** I removed the `and today.weekday() != 6` clause, leaving
  `elif days_since_last == 1: user.listening_streak += 1`. That restores the intended rule:
  consecutive day → increment, regardless of weekday. I checked every branch on both sides of the
  boundary — same day (no change), consecutive day including Sat→Sun and Sun→Mon (increment),
  gap > 1 day (reset), and first-ever listen (streak = 1, handled earlier). Verified with
  `pytest tests/test_streaks.py`: the previously failing `test_streak_increments_on_sunday` now
  passes and the other four still pass (5 passed).

## Issue #3 — The same song keeps showing up twice in search

- **How I reproduced it:** I ran the exact query from `search_songs()` (a `LEFT JOIN` from `song`
  to `song_tags`, filtering on title/artist, with **no `DISTINCT`**) against the seeded DB with
  `q="Borough"`, which matches the artist "Borough Kings". That song ("Crown Heights Anthem") has
  3 tags, and the query returned **3 identical rows** for it, though only **1** distinct song
  matches. HTTP equivalent: `GET /songs/search?q=Borough` reports `count: 3` for one song.
  Crucially, songs with 0 or 1 tag return exactly once, so the duplication only appears for
  multi-tag songs — which is why the report calls it "inconsistent."
- **How I found the root cause:** I traced search top-down from the route: `GET /songs/search?q=`
  in `routes/songs.py` → `search_songs(query)` in `search_service.py`. The route only wraps the
  result, so the duplication had to originate in the query. Reading `search_songs()`, I saw it
  `outerjoin`s `song_tags` and calls `.all()` with no `.distinct()`. Because a SELECT over a
  one-to-many join returns one row per child, a song with N tags yields N identical `Song` rows. I
  confirmed this by running the same join in raw SQL against the seeded DB: `q="Borough"` returned 3
  rows for one 3-tag song, and adding `DISTINCT` collapsed it to 1. I also noticed the join
  contributed nothing to the output — only `Song` is selected and `to_dict()` loads tags separately
  — so it was pure dead weight causing the fan-out.
- **The root cause:** The query joined `Song` to the `song_tags` association table
  (`.outerjoin(song_tags, ...)`) but selected only `Song` and never de-duplicated. A relational join
  over a one-to-many relationship produces one result row per matching child row, so a song with 3
  tags came back as 3 identical `Song` objects, which `to_dict()` then serialized 3 times. Songs with
  0 or 1 tag produced a single row, which is why duplication appeared only for multi-tag songs and
  looked "inconsistent."
- **My fix and side-effect check:** I removed the `.outerjoin(song_tags, ...)` line entirely, so the
  query is simply `query(Song).filter(title/artist ilike).all()`. The join was never needed: each
  result's tags are attached by `Song.to_dict()` via the `tags` relationship, not by the join. This
  removes the row fan-out at its source rather than masking it with `.distinct()`. Side-effect check:
  results still include the `tags` list; a multi-tag song now appears once, single-tag once, no-tag
  once, and a non-matching query returns `[]`. Verified with `pytest tests/test_search.py`: the
  previously failing `test_search_no_duplicates_multi_tag_song` passes and the other four pass
  (5 passed).

## Issue #5 — The last song in a playlist never shows up

- **How I reproduced it:** I replicated `get_playlist_songs()` — songs ordered ascending by
  `playlist_entries.position`, then the `songs[:-1]` slice it applies — against the "Late Night
  Vibes" playlist. The playlist has **7** songs (positions 1–7); the service returns **6**,
  dropping "Free Throws" at position 7 (the highest position / last-added). HTTP equivalent:
  `GET /playlists/<id>/songs` reports `count: 6`. Every non-empty playlist loses exactly its last
  song.
- **How I found the root cause:** The symptom is user-facing ("last song missing"), so I started
  at the endpoint that lists a playlist's songs — `GET /playlists/<id>/songs` in
  `routes/playlists.py`. That route does nothing but call `get_playlist_songs()` and JSON-encode
  the result, so the logic had to be in the service. Reading `get_playlist_songs()`, the
  SQLAlchemy query correctly joins through `playlist_entries` and orders by `position` — nothing
  wrong there. The problem was the final line: `return [song.to_dict() for song in songs[:-1]]`.
  The `[:-1]` slice, combined with the function's own docstring promising it "returns all songs,"
  made me confident this was the specific cause, not just a suspicious area — and the reproduction
  confirmed it (7 fetched, 6 returned, position-7 dropped).
- **The root cause:** The database query was correct — all N songs were fetched in position order
  — but the return statement sliced the list with `songs[:-1]`, which is Python for "every element
  except the last one." That silently discarded the highest-position song on every read. A
  one-song playlist would return zero songs; an empty playlist was unaffected only because
  `[][:-1]` is still `[]`.
- **My fix and side-effect check:** I changed `songs[:-1]` to `songs` so every fetched song is
  serialized and returned — the smallest change that addresses the root cause, leaving the query
  and ordering untouched. I checked both sides of the boundary: the empty-playlist case still
  returns `[]` (the only change was removing the slice), and non-empty playlists now return all
  songs in order. Verified with `pytest tests/test_playlists.py`: `test_playlist_returns_all_songs`,
  `test_playlist_returns_songs_in_order`, and `test_empty_playlist_returns_empty_list` all pass.
  `get_playlist_songs` is consumed only by this one route (plus an unused import in
  `notification_service`), so no other feature is affected.
