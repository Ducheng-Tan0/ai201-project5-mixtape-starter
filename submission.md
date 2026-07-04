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
