# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Development Server
```bash
python3 wsgi.py              # Run development server (port 5000)
```

### Flask CLI Commands
```bash
export FLASK_APP=gbtalks
python3 -m flask createdb               # Create database tables
python3 -m flask migrate                # Apply pending database migrations
python3 -m flask migration-status       # Check migration status
python3 -m flask migration-status -v    # Show detailed migration info
python3 -m flask load-sample-data talks --clear    # Load sample talk data
python3 -m flask load-sample-data recorders        # Load sample recorder data
python3 -m flask load-sample-data editors          # Load sample editor data
python3 -m flask convert-talks          # Process edited audio files to production MP3s
```

### Production Deployment
```bash
# Docker deployment
docker build -t gbtalks .
docker run -p 5002:5002 gbtalks

# uWSGI deployment (production)
uwsgi gbtalks.ini
```

### Code Quality
```bash
ruff check .                 # Lint Python code
ruff check --fix .           # Lint and apply safe autofixes
pytest                       # Run the test suite
pytest tests/test_rota.py    # Run one module
```

Lint and test configuration both live in `pyproject.toml`. Ruff targets Python
3.13 and excludes `gbtalks/markdown/`, which is vendored third-party code.

Two lint conventions worth knowing before "fixing" what look like violations:

- SQLAlchemy filters need `Column.is_(True)` / `is_(False)`, not a bare truth
  test. Ruff's E712 suggestion would silently change the query.
- `Talk.recorded_by` is a *relationship*, so `== None` / `!= None` is the
  supported comparison there and is marked `# noqa: E711`.

### Testing
The suite uses an isolated temporary SQLite database and temp storage
directories, both set up in `tests/conftest.py`. That has to happen at module
scope, before `gbtalks` is imported, because `config.Config` reads `os.environ`
when its class body executes.

Useful fixtures: `client` (anonymous), `auth_client` (logged in as a team
leader), `db`, and the `make_talk` / `make_recorder` / `make_editor` factories.

## Architecture

### Application Structure
This is a Flask web application for managing talk recordings at Greenbelt Festival. The app uses SQLAlchemy for database operations and Flask-Dance for Google OAuth authentication.

**Core Components:**
- `gbtalks/` - Main Flask application package
- `config.py` - Configuration management using environment variables
- `wsgi.py` - WSGI entry point for production deployment

### Database Models (`gbtalks/models.py`)
- **Talk** - Central model storing talk metadata, recording status, and content warnings
- **Recorder** - People who record talks, with availability constraints and shift limits
- **Editor** - People who edit recorded audio
- **RotaSettings** - Configurable parameters for rota generation algorithm
- **User/OAuth** - Google authentication models

### Key Features
- **Audio Processing Pipeline**: Raw recordings → edited files → processed MP3s with normalization
- **Rota Management**: Automated assignment of recorders to talks based on availability and constraints
- **Content Management**: Track talk status, warnings, and metadata
- **Authentication**: Google OAuth for team leader permissions

### Talks CSV Format
Talks enter the database two ways - the `/talks` upload and
`flask load-sample-data talks` - and both go through the single parser in
`gbtalks/talks_csv.py`. There is one format; `sample_data/talks.csv` is a
working example of it.

Columns are matched by **header name**, not position, so order does not matter.
Required: `id`, `title`, `speaker`, `day`, `start_time`, `end_time`, `venue`.
Everything else is optional and defaults to empty or False:
`description`, `is_priority`, `is_rotaed`, `is_cleared`, the four `has_*_sticker`
columns, `recorder_name`, `editor_name`.

Values are read leniently, because the file normally comes from the festival
programme export rather than being written by hand:

| Field | Accepted |
|---|---|
| booleans | `Yes`/`No`, `Y`/`N`, `true`/`false`, `1`/`0`, or blank for False |
| `id` | `17`, or a prefixed reference like `GB26-001` |
| `start_time`/`end_time` | a time of day (`7:00 PM`, `19:00`, `19:00:00`), or an absolute `YYYY-MM-DD HH:MM[:SS]` |

**Prefer a time of day.** The date is then derived from the `day` column and the
configured `GB_FRIDAY`, so the same file still works next year. Talks run within
a single day - festival programming is roughly 08:00 to 22:00 - so an end time
that is not after its start is an error, not a talk running past midnight.

A malformed file is rejected in full, naming the offending row and column, and
the existing talks are left untouched - parsing happens before anything is
deleted.

`is_rotaed` is what the rota generator builds around. A file with that column
unset produces an empty rota.

### File Structure
- Raw recordings stored in `UPLOAD_DIR` with `_RAW` suffix
- Edited files stored in `UPLOAD_DIR` with `_EDITED` suffix  
- Processed MP3s in `PROCESSED_DIR` and `WEB_MP3_DIR`
- CD preparation files in `CD_DIR`

### Audio Processing (`gbtalks/commands.py`)
The `convert_talks` command processes edited audio files:
1. Adds top/tail audio segments
2. Normalizes audio levels using ffmpeg-normalize
3. Exports to 128k MP3 with metadata
4. Creates CD-ready WAV files (5-minute segments)
5. Copies to web directory

### Migration System
Custom migration framework in `gbtalks/commands.py`:
- Tracks applied migrations in `schema_migrations` table
- Sequential version numbering (001_name, 002_name, etc.)
- Supports rollback functions and detailed documentation

### Configuration
Environment-based configuration in `config.py`:
- Database: SQLite by default, configurable via `SQLALCHEMY_DATABASE_URI`
- Storage paths: All file directories configurable via environment variables
- Greenbelt-specific: Automatic calculation of festival dates based on August bank holiday
- Authentication: Google OAuth client credentials from environment

### Rota Generation
`is_rotaed` decides which talks the rota is *built around*, not which talks may
be recorded. The two main loops in `gbtalks/rota/routes.py` only seek out a
recorder for flagged talks.

The follow-on passes deliberately do not filter on `is_rotaed`: once a recorder
is on shift anyway, staying on for the next talk is effectively free, so an
unflagged talk nearby is worth picking up. Do not "fix" this by adding an
`is_rotaed` filter to those queries. Note the two passes differ - the priority
follow-on is restricted to the same venue, while the additional-talk follow-on
is not.

### Permission System
Team leader permissions controlled via `TEAM_LEADERS_EMAILS` in config.py. These users can access editing and administration features.

Most routes carry both `@login_required` and `@current_user_is_team_leader`.
The exceptions are deliberate: the read-only rota views (`/rota_by_recorder`,
`/rota_by_time`, `/rota_by_venue`) and the CSV exports are readable without
signing in, so recorders can check their shifts on site. `POST /rota`
regenerates the rota and clears every existing assignment, so it checks team
leader permissions inline even though `GET /rota` is open.

### Dependencies
- Flask ecosystem (Flask, Flask-SQLAlchemy, Flask-Login, Flask-Dance)
- Audio processing: pydub, mutagen, ffmpeg-normalize
- System tools: subprocess calls to wodim (CD burning), ffmpeg-normalize
- Development: flake8 for linting