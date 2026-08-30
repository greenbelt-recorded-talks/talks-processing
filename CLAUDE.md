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

### Deployment

The server hosts **two checkouts of this repo**, with different jobs. Editing
the wrong one loses work.

| Path | Remote | Role |
|---|---|---|
| `~/build/talks-processing` | SSH — **has push access** | Where you edit, commit and push. No venv, no runtime state. |
| `~/talks-processing` | HTTPS — read-only | The *deployed* copy. Ansible owns it. Never edit it by hand. |

The deployed checkout is also the one holding the state that is not in git:
`.env`, `instance/`, and the `.ve/` virtualenv the systemd unit runs from.

The deploy target is this machine itself — the playbook is `hosts: localhost`.
There is no remote to ship to, which is why "deploying" is just a matter of
getting the pushed commit into `~/talks-processing` and restarting things.

#### edit → push → pull

```bash
# 1. Edit and push, in the build checkout (Claude does this part)
cd ~/build/talks-processing
git commit -am "..."
git push

# 2. Pull and apply, in the deployed checkout (a human does this part)
cd ~/talks-processing
git pull
cd ansible
ansible-playbook --become --ask-become-pass gbtalks-playbook.yaml
```

**A push alone changes nothing.** The commit is not live until step 2 has run.

Step 2's `git pull` looks redundant — the playbook checks the repo out itself —
but it is not. Ansible resolves a task's `src:` from the playbook's own
directory, and the first play that copies a file (`gbtalks-zshenv`) runs
*before* the play that does the git checkout. Without the manual pull, that
early play would copy the previous run's version of the file.

Ansible's `git` module refuses to overwrite local modifications, so
`~/talks-processing` has to stay clean or the deploy dies partway through,
after some services have been reconfigured and others have not.

The playbook is itself in this repo (`ansible/`), so a change to the deployment
goes through exactly the same cycle as a change to the app.

#### What the playbook does

Beyond the checkout: installs apt packages and the `gbtalks` user, installs
`requirements.txt` into `.ve/`, writes `gbtalks-uwsgi.conf` to
`/etc/systemd/system/gbtalks.service` and `gbtalks-nginx` to the nginx sites
dir, restarts both services, installs the 5-minute `conversion_cron.sh` cron
job, configures dnsmasq for the on-site network, and creates the `/storage/*`
working directories.

#### Python version

The app runs on **3.13**, matching CI and PythonAnywhere. Ubuntu 24.04 only
ships 3.12, so the playbook adds the deadsnakes PPA and builds `.ve/` with
`python3.13 -m venv`.

`/usr/bin/python3` stays on 3.12 and must not be repointed — Ubuntu's own
tooling is built against it. Only the venv moves, so `python3` at a shell
prompt is still 3.12 and is not what the app uses; `.ve/bin/python` is.

Ansible's `pip` module creates a venv only when one is absent, so an existing
venv would otherwise stay on whatever Python built it. The play checks
`.ve/bin/python`'s version and deletes the venv when it does not match, forcing
a rebuild. That makes the first run after this change slow — every dependency
reinstalls, and uWSGI compiles from source.

uWSGI is deliberately **not** in `requirements.txt` (PythonAnywhere provides its
own, and the Dockerfile uses gunicorn), so the playbook pip-installs it into the
venv as a separate step. Before that step existed it was only ever installed by
hand, and a venv rebuild would have left the systemd unit with no `uwsgi` to
exec.

`pydub` needs `audioop`, which left the stdlib in 3.13; `requirements.txt`
already covers that with `audioop-lts; python_version >= "3.13"`.

It depends on two Galaxy roles listed in `ansible/gbtalks-requirements.yaml`
(`gantsign.oh-my-zsh`, `diodonfrost.p10k`); both are already installed under
`~/.ansible/roles`, so `ansible-galaxy install -r` is only needed on a fresh
machine.

`.github/workflows/ci.yml` runs ruff and pytest on push and PR. It does **not**
deploy. The `Dockerfile` is leftover VS Code scaffolding and is not part of the
deployment path.

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

#### Deleting one of a talk's files

A talk has several files - raw, the video it may have been extracted from,
edited, processed, web MP3, recorder's notes - and `POST /delete_talk_file`
removes exactly one of them, named by `file_type` alongside `talk_id`. Form in,
JSON out.

The only button on it so far is "Delete Processed File" on the talks page. It
posts from JavaScript (`form.js-delete-file` in `talks.html`) because the route
answers with JSON rather than a redirect, and reloads on success - a card's
contents are rendered from whether the file is on disk, so a reload is what
redraws it. A failure raises a UIkit notification carrying the route's `error`
and leaves the page alone.

The database is untouched, deliberately. Recording status is `os.path.exists`
against the storage directories rather than a column, so removing the file *is*
the state change; the talk row stays.

`TALK_FILE_TYPES` and `talk_file_path` in `routes.py` are the one place that
says which kinds exist and where each lives. A `file_type` from a request is
looked up there and the path comes from the `get_path_for_*` helpers - a name
in a form is never a path, the same rule the critical-file routes follow with
`critical_files()`. An unknown kind is a 400, a missing file a 404, so a caller
that thinks it deleted something did.

It replaces `POST /deletetalk`, which is **gone**. That one redirected to the
referrer, did not check the type (anything unrecognised was a 500 on an unbound
`path`) and did not check the file was there. `talks.html` was its only caller.

### Audio Processing (`gbtalks/commands.py`)
The `convert_talks` command processes edited audio files:
1. Adds top/tail audio segments
2. Normalizes audio levels using ffmpeg-normalize
3. Exports to 128k MP3 with metadata
4. Creates CD-ready WAV files (5-minute segments)
5. Copies to web directory

### Audio Levels

Three values in `config.py`, and every part of the pipeline reads them rather
than carrying its own copy:

| | default | |
|---|---|---|
| `AUDIO_TARGET_LUFS` | -16 | the loudness every finished talk is cut to |
| `AUDIO_LOUDNESS_RANGE_LU` | 11 | the loudness range target handed to loudnorm |
| `AUDIO_TRUE_PEAK_DBTP` | -1.5 | the peak ceiling |

They were three literals in the middle of `convert_talks`'s
`ffmpeg-normalize` argument list. That is how the range target came to be
asking for something no talk can give: real talks measure LRA 8 to 11, and a
target of **3** can only be met by riding the gain 3-4 dB throughout, which is
audible as pumping. Every run logged two warnings saying the filter had given
up on linear normalisation and fallen back to dynamic; the settings had never
once done what they said.

`AUDIO_LOUDNESS_RANGE_LU` is deliberately set **above** the loudness range of
any talk measured so far, so the filter is never asked to compress one to hit
it. Lowering it is a request for compression - that is what it is for.

Up to GB26 the target was **-13 LUFS**, chosen for playback in a car, and
every talk in the archive before this change sits there. -16 is the usual
spoken-word figure and is quieter, so this year's talks are quieter than
previous years': a deliberate change, not a tidy-up. Measured on real talks,
the gain movement across 45 seconds of ordinary speech drops from 3.5 dB at
the old settings to 0.6 dB at these.

Linear normalisation is not reachable for this material at any sane level, and
that is fine. The talks measure -18 to -26 LUFS integrated with true peaks
around -1 dBTP - a crest factor wide enough that lifting them to any modern
target linearly would clip. Dynamic is the right mode here; the point of the
range target is to make it gentle rather than to escape it.

**Changing the target orphans the talks already converted.** Nothing
re-converts a talk that already has a processed file, so a mid-festival change
leaves a split archive until the processed MP3s are deleted and the cron job
rebuilds them.

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

#### GB_FRIDAY

`GB_FRIDAY` is the Friday the festival starts, and it feeds every filename
(`gb26-001_RAW.mp3`), every MP3 year tag, and the date the `day` column in a
talks CSV is resolved against.

It is **dynamic by default**: `config.Config` calls `default_gb_friday()`, which
gives this calendar year's festival. Setting `GB_FRIDAY` in `.env` overrides it;
leaving it unset is the normal case, and an empty `GB_FRIDAY=` counts as unset.

The arithmetic lives once, in top-level `festival_dates.py`. It is top-level
rather than in the package because `config.py` needs it and must not import the
application; `gbtalks/libgbtalks.py` re-exports `calculate_greenbelt_friday` so
the rest of the app still imports it from where it always has.

The default follows the **calendar year**, deliberately *not*
`festival_cycle_start`'s notion of the cycle. The two disagree from the Tuesday
after the festival until New Year, and the calendar year is right here:
September is spent turning August's recordings into MP3s, and those filenames
want the year of the festival they came from. New Year is therefore the one
moment the default moves under you - which is when to pin `GB_FRIDAY` if a
year's talks are somehow still unfinished.

The value is read when the class body executes, so a restart is needed to pick
up a change. That is not worth engineering around: the only time the default
moves is 1 January, when nothing is running on site.

`POST /update_festival_year` on the setup page writes `.env` (the path is
`ENV_FILE`, defaulting to the deployed checkout and overridable so tests are not
editing the real one). It pins `GB_FRIDAY` **only when the chosen year differs
from `default_gb_friday()`**, and strips the line otherwise. Picking the current
year is asking for the default, so freezing it as a literal is exactly wrong -
that is how the on-site `.env` came to say `GB_FRIDAY=2025-08-22` with GB26 a
day away. A pin for a genuine look-ahead to a future year removes itself the
next time someone picks the current year.

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

### Cover Art
`alltalksicon.png` in `IMG_DIR` is embedded as the front cover of every
processed MP3 (`APIC` in `gbtalks/commands.py`). It is not something to prepare
by hand: `POST /upload_cover_image` accepts a PNG or JPEG at any size and
`normalise_cover_image` in `libgbtalks.py` converts it to a square PNG of
`COVER_ART_SIZE` (default 300, override with the env var).

A source that is not square is **padded** with transparency, not centre-cropped.
The icon is a logo, and cropping one silently eats its edges - padding is
visibly wrong rather than subtly wrong, which is the better failure when nobody
looks at the result until the MP3s are on the USB sticks. If you ever want
cropping instead, that is the one decision to revisit in that function.

`filetype.guess` returns `None` for anything it cannot identify, so the format
check has to be `kind is not None and kind.extension in (...)`. The same
unguarded `kind.extension` pattern still exists in the recorder-notes upload in
`routes.py` and will 500 on an unrecognised file.

### Carried-over Files
`top.mp3`, `tail.mp3`, `alltalksicon.png` and the all-talks index keep the same
names from one year to the next, so last year's copy sits in `/storage` looking
perfectly healthy. The health check flags any of them not modified since the
last festival ended, and `POST /confirm_file_current` records "checked, still
the right one" by **touching the file**. mtime is the only state, so there is
no second record to drift out of step with the files themselves; the price is
that "Last Modified" now means "modified or confirmed", which is what the page
calls it.

`festival_cycle_start` in `libgbtalks.py` draws the line: the Tuesday after the
most recently *finished* festival. It works that out from the clock rather than
from `GB_FRIDAY`, deliberately. A year nobody rolled over is exactly what this
check exists to catch, and when it was written the on-site `.env` still said
`GB_FRIDAY=2025-08-22` with GB26 a day away - a config-derived cutoff would
have called all four files current.

A stale file is a **warning**, never an error. It is present and readable, and
only a human can say whether it is the right one. The confirm route resolves
the submitted name against `critical_files()` instead of trusting a path from
the form, and will not create a file that is missing - an empty `top.mp3` would
satisfy the exists check and then break conversion quietly.

Confirming a file only means anything if you can check it first, so each card
carries a preview: an inline player for the two MP3s, a thumbnail for the cover
art, a download button for all four. The cards are laid out two to a row and
kept short: what stays on the face of one is the preview plus the glance-level
facts (size, then the describers' values with their labels dropped - "0:07 ·
128 kbps", "300 × 300 px · PNG"), and everything else is behind a **Details**
disclosure. The stale warning is not repeated in the issues line, because the
"Modified or confirmed" line already carries it. The directory cards above
them follow the same shape - three to a row, contents and permissions on the
face, path and used-by behind Details - so the whole page fits on a screen or
two instead of a dozen. `GET /critical_file?name=` serves the
bytes - inline by default, `&download=1` as an attachment - and resolves the
name against `critical_files()` for the same reason the confirm route does.
The URL carries the file's mtime as a cache buster, so a replaced cover image
does not come back from the browser cache.

The `describe_*_file` helpers in `libgbtalks.py` supply the stats beside each
one (duration and bitrate, dimensions and colour mode, PDF version). They are
**display only**: `describe_file` catches their failures into a message rather
than adding an issue, because whether a present, readable file is the right one
is exactly the question a human is being asked. A `top.mp3` mutagen cannot
parse still gets a green card and a note. The PDF describer reads the 8-byte
header and nothing else - page counts would mean a PDF library the app has no
other use for, and the download button is right there.

The thumbnail sits on a CSS checkerboard because `normalise_cover_image` pads a
non-square source with transparency, which is invisible against a white card.

Confirming is only one of the two answers, so every card also carries a
`POST /replace_critical_file` form, behind its own disclosure and open by
default when the file is missing, that writes a new copy in place. It resolves
the name against `critical_files()` like the other two routes, and each entry
there says what it will accept (`upload`, `upload_label`, `accept`). The cover
art goes through `normalise_cover_image`, so a JPEG at any size is fine; the
other three are checked with the guarded `kind is not None` form of
`filetype.guess`. A replacement is written now, so it clears the staleness
check on its own without also being touched. Setup's own `upload_top_tail` and
`put_alltalks_pdf` still exist and are unchanged - they land you back on the
setup page, where there is nothing to look at, which is the whole reason for
having the same thing on the card you have just previewed.

### Jingle Levels

`top.mp3` and `tail.mp3` are bolted onto every processed talk, so they want to
sit at the loudness the talks themselves are cut to. The health check measures
both against `AUDIO_TARGET_LUFS` and `AUDIO_TRUE_PEAK_DBTP` (see Audio Levels
above) with `audio_level_check` in `libgbtalks.py`.

Note this only bites once the jingles are levelled *separately* from the talk.
While `convert_talks` normalises `top + body + tail` as one unit, loudnorm
pulls the jingle to the target whatever level it arrived at, so re-levelling
the source file changes almost nothing about the output. The check is here for
the split, and because a jingle that cannot reach the target is worth knowing
about before the split rather than after.

The verdict separates two cases that read the same on a meter and want
different answers: a file that is quiet **with** peak headroom can simply be
turned up (`quiet`), and one that is quiet **without** it (`squashed`) can only
reach the target by having its peaks limited. Both current jingles are the
second kind - they are mastered at -18.5 and -17.2 LUFS with true peaks at
-1.5 and -1.1 dBTP, which is essentially no headroom at all. At the -16 target
the top needs about 2.4 dB of limiting and the tail about 1.6 dB. The message
says so, and past 2 dB it suggests a re-cut instead, which is why the top asks
for one and the tail does not.

Being off target does **not** move the card's status or the page's. The
pipeline has run for years on jingles that sit off target, so this is something
to act on rather than a fault, and turning the whole page amber over it would
only teach people to ignore amber.

`POST /relevel_critical_file` is the fix. It resolves the name against
`critical_files()` like the confirm, download and replace routes, and only
entries carrying `level_check` are eligible.

`relevel_audio` applies a fixed gain, and a peak limiter *only* when the gain
will not otherwise fit under the ceiling - a produced jingle wants
gain-matching, not compression. Limiting costs loudness by an amount that
depends entirely on the material, so the gain is **solved for** rather than
calculated: render, measure, correct, up to three times, each attempt starting
from the original so the limiter never acts on its own output. In practice it
lands within 0.3 LU.

The order in the route is load-bearing: the new audio is rendered and measured
**before** anything on disk is touched, then the original is copied to
`BACKUP_DIR`, then the replacement is staged in the destination directory and
`os.replace`d into place. A failure at any point leaves the file alone, and an
interrupted write cannot leave a truncated `top.mp3` - which would satisfy the
health check's exists test and then break every conversion after it.

Re-levelling costs a generation of MP3 (hence 320k on a file that is seconds
long) and whatever the limiter caught, and there is no undo from the file
itself. The backup is the way back.

Measuring shells out to ffmpeg, which the PythonAnywhere deployment does not
have. `measure_loudness` turns that into a `ValueError` and the check reports
status `unknown` rather than taking the health page down with it.

### Moving the Database Between Deployments

There are two deployments - the PythonAnywhere one and the festival server -
and the database moves between them as a file. `GET /download_database` and
`POST /upload_database` on the setup page are that, and there is deliberately
no merge: the incoming talks, rota and recorders replace the ones here, because
two divergent copies of a rota cannot be reconciled by anything but a human.

The copy is taken with SQLite's **online backup API** (`sqlite3.Connection
.backup`, via `snapshot_database`), not `shutil.copy`. uWSGI is writing to the
file, and a plain read can catch a transaction half-written and produce a file
that opens cleanly while being subtly wrong. The same call takes the "here is
what you overwrote" snapshot on the way in, which is the only way back from an
upload.

`instance/gbtalks.sqlite` is on `journal_mode=delete`, so there are no `-wal` /
`-shm` sidecars to move alongside it. If that ever changes to WAL, a plain file
copy starts silently losing recent commits and this becomes the only safe path.

The upload stages the file **inside the instance directory** so the install is
an `os.replace` within one filesystem - atomic, with no moment where a worker
can see a half-written database. `mkstemp` makes it private to its owner, hence
the `shutil.copymode` from the file being replaced.

`inspect_database_file` splits its findings into *problems* (do not install)
and *notes* (install, but say this). A database from **newer** code is a
problem: its schema carries changes this code cannot read and there is no
down-migration path. One that is **behind** is only a note - that is what
`flask migrate` is for. `DATABASE_REQUIRED_TABLES` is the four model tables
and deliberately not `schema_migrations`: that table is not a model, only
`flask migrate` creates it, so a database straight from `flask createdb` has
never had one and requiring it would reject a good file. `user` and
`flask_dance_oauth` are likewise not required, because the login flow creates
those rows on first sign-in.

After the swap the route calls `db.session.remove()` **before**
`db.engine.dispose()`. The session's identity map describes rows in a database
that no longer exists, and its connection is an open handle on the moved-aside
inode, so disposing the pool alone leaves it serving the old file. With both,
the replacement takes effect immediately; the flash still asks for a restart,
which is what covers a uWSGI configured with more than one worker.

What does **not** travel is the audio. Recording status is `os.path.exists`
against `UPLOAD_DIR` / `PROCESSED_DIR`, not a column, so a database moved to a
machine without the files shows every talk as un-recorded. That is expected.
Nor does `GB_FRIDAY`: it comes from the environment, and a database whose talks
are from a different year than the receiving deployment's `GB_FRIDAY` will
generate filenames that match nothing on disk.

### Deployment Badge
The navbar carries a badge saying which deployment you are looking at - `Cloud`
on PythonAnywhere, `On-site` on the festival server. Detection is a sniff for
`PYTHONANYWHERE_DOMAIN` / `PYTHONANYWHERE_SITE`, which PythonAnywhere sets in
web workers and consoles alike and nothing else does; `DEPLOYMENT_ENV`
overrides it. An unrecognised value renders in red rather than being hidden.

`DEPLOYMENT_LABELS` in `gbtalks/__init__.py` maps the value to its label,
colour and tooltip, and a context processor injects it, so the badge needs no
per-route wiring.

It only appears on templates that extend `base.html`, all of which are behind a
login. The three anonymous rota views (`/rota_by_recorder`, `/rota_by_time`,
`/rota_by_venue`) are standalone print-oriented templates with no navbar at
all, so they carry no badge.

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