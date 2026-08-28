import csv
import os
import pprint
import re
import shutil
import subprocess
import tempfile
import traceback
from datetime import datetime
from multiprocessing import Pool

import click
from flask import current_app as app
from flask.cli import with_appcontext
from mutagen.id3 import APIC, COMM, ID3, TALB, TCMP, TCOP, TDRC, TIT2, TPE1, TPE2, TRCK
from pydub import AudioSegment
from tendo import singleton

from .libgbtalks import get_cd_dir_for_talk, get_path_for_file
from .models import Editor, Recorder, Talk, db
from .talks_csv import parse_talks_csv

# The two generated filenames, as get_path_for_file writes them: an edited
# upload is gb26-020_EDITED.mp3, a finished conversion GB26_020_Title_Name.mp3.
# Both are matched whole. Picking them apart with replace() and split()
# instead is what let last year's gb25-013_EDITED.mp3 through as a talk id of
# "gb25-013" - the prefix being stripped is always the current year's, so a
# foreign one survives intact - and what made any stray .mp3 without an
# underscore in PROCESSED_DIR raise IndexError and stop the run outright.
EDITED_FILE_RE = re.compile(r"^gb(?P<year>\d{2})-(?P<id>\d{3})_EDITED\.mp3$")
PROCESSED_FILE_RE = re.compile(r"^GB(?P<year>\d{2})_(?P<id>\d{3})_.*\.mp3$")


# ffmpeg-normalize makes two full passes over an uncompressed copy of the talk,
# so an hour-long one takes a few minutes. This is not a performance budget, it
# is a deadlock guard: convert_talks holds a SingleInstance lock for its whole
# lifetime, so a single wedged ffmpeg would stop every later cron run from
# converting anything at all, silently, for the rest of the festival. A talk
# lost to the timeout is one talk; a lock held forever is all of them.
NORMALIZE_TIMEOUT_SECONDS = 3600


def normalise_audio(input_path, output_path):
    """Normalise input_path onto output_path, raising on anything but success.

    The call used to be a bare subprocess.call, whose return code nothing
    looked at. Execution then carried on into AudioSegment.from_file() on an
    output that might never have been written - and because the temp paths
    were derived from the talk id, a leftover file from an earlier failed
    attempt at the *same* talk would be picked up and published as that
    talk's audio. Failing here instead costs one talk and says why.

    ffmpeg-normalize is also chatty on stderr - a progress bar, plus a pair of
    warnings on every talk we have ever fed it - so its output is captured and
    only surfaced when something actually went wrong. Sent straight to the
    cron logger, as before, a real failure looked exactly like a normal run.
    """
    command = [
        "ffmpeg-normalize",
        input_path,
        "-o",
        output_path,
        "--loudness-range-target",
        "3",
        "-t",
        "-13",
        "-f",
        "-ar",
        "44100",
    ]

    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=NORMALIZE_TIMEOUT_SECONDS,
            check=True,
        )
    except FileNotFoundError as error:
        # It lives in the venv's bin, which is on PATH only because
        # conversion_cron.sh sources the activate script. A venv rebuilt
        # without it looks exactly like this.
        raise RuntimeError(
            "ffmpeg-normalize is not on PATH - is the virtualenv active?"
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "ffmpeg-normalize exited "
            + str(error.returncode)
            + " for "
            + input_path
            + "\n"
            + _last_lines(error.stderr)
        ) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "ffmpeg-normalize did not finish within "
            + str(NORMALIZE_TIMEOUT_SECONDS)
            + "s for "
            + input_path
            + "\n"
            + _last_lines(error.stderr)
        ) from error

    # check=True covers a non-zero exit, not a zero exit that wrote nothing.
    # pydub's complaint about a missing input is opaque enough to be worth
    # pre-empting with one that names the step that should have created it.
    if not os.path.exists(output_path):
        raise RuntimeError(
            "ffmpeg-normalize succeeded but wrote no output for " + input_path
        )


def _last_lines(output, count=20):
    """The tail of a captured stream, for putting in an exception message."""
    if not output:
        return "(no output)"
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    return "\n".join(output.strip().splitlines()[-count:])


def process_talk(talk_id):
    """Convert one edited talk, logging any failure rather than raising.

    Pool.map runs these in chunks, and a chunk is a plain map - so an
    exception does not only lose its own talk, it abandons every talk queued
    behind it in the same chunk. One unreadable file should cost one talk.
    """
    try:
        _process_talk(talk_id)
    except Exception:
        pprint.pprint("FAILED to process talk " + str(talk_id))
        traceback.print_exc()


def _process_talk(talk_id):
    top = AudioSegment.from_file(os.path.join(app.config["UPLOAD_DIR"], "top.mp3"))
    tail = AudioSegment.from_file(os.path.join(app.config["UPLOAD_DIR"], "tail.mp3"))

    talk = db.session.get(Talk, talk_id)

    # Both intermediates are a full uncompressed copy of the talk - about
    # 600MB each for an hour - and they live and die with this directory,
    # whether the block is left normally or by an exception. The old code
    # named them after the talk id and removed them on the happy path only,
    # so any failure after the export stranded both, and the next attempt at
    # that talk found them waiting.
    with tempfile.TemporaryDirectory(prefix="gbtalks-" + str(talk.id) + "-") as work:
        # Add the top and tail, create a high-quality mp3
        hq_mp3 = (
            top + AudioSegment.from_file(get_path_for_file(talk.id, "edited")) + tail
        )

        # Export a WAV of the top/tailed audio for further processing
        toptail_path = os.path.join(work, "toptailed.wav")
        hq_mp3.export(toptail_path, format="wav")

        # Normalise to a fixed level
        normalized_path = os.path.join(work, "normalized.wav")
        normalise_audio(toptail_path, normalized_path)

        # Load the normalised file back in. Everything downstream works from
        # this, in memory, so the temp directory is done with here.
        hq_mp3 = AudioSegment.from_file(normalized_path)

    # Create a reduced-bitrate MP3 from the normalized file
    hq_mp3.export(
        get_path_for_file(talk.id, "processed", talk.title, talk.speaker),
        format="mp3",
        bitrate="128k",
    )

    # Put appropriate metadata on the resultant mp3
    mp3 = ID3(get_path_for_file(talk.id, "processed", talk.title, talk.speaker))

    mp3["TALB"] = TALB(text="Greenbelt Festival Talks " + app.config["GB_FRIDAY"][0:4])
    mp3["TCOP"] = TCOP(text=app.config["GB_FRIDAY"][0:4] + " Greenbelt Festivals")
    mp3["TIT2"] = TIT2(text=talk.title)
    mp3["TPE1"] = TPE1(text=talk.speaker)
    mp3["TPE2"] = TPE2(text=talk.speaker)
    mp3["TRCK"] = TRCK(text=str(talk.id))
    mp3["TDRC"] = TDRC(text=str(app.config["GB_FRIDAY"][0:4]))
    mp3["COMM"] = COMM(text=talk.description)
    mp3["TCMP"] = TCMP(text="1")

    with open(app.config["IMG_DIR"] + "/alltalksicon.png", "rb") as albumart:
        mp3["APIC"] = APIC(
            mime="image/png", type=3, desc="Front cover", data=albumart.read()
        )
    mp3.save()

    # Copy the file to the web_mp3 directory with filename format gbXX-XXXmp3.mp3
    shutil.copy(
        get_path_for_file(str(talk.id), "processed", talk.title, talk.speaker),
        get_path_for_file(str(talk.id), "web_mp3"),
    )

    # Create files for later CD burning
    cd_dir = get_cd_dir_for_talk(talk.id)
    if os.path.exists(cd_dir):
        shutil.rmtree(cd_dir)

    os.makedirs(cd_dir)

    # Split the mp3 into 5min (300k ms) slices
    for idx, cd_file in enumerate(hq_mp3[::300000]):
        cd_file.export(
            cd_dir + "/" + str(idx).zfill(2) + ".wav",
            format="wav",
        )


@click.command()
@with_appcontext
def convert_talks():
    """Create production files (MP3 and CD) from edited files"""

    # Make sure we only run one of these at a time. The instance must stay
    # referenced for the lifetime of the command - it releases the lock when it
    # is garbage collected, so this binding is deliberate and load-bearing.
    only_once_preventer = singleton.SingleInstance(flavor_id="convert_talks")  # noqa: F841

    gb_year = str(app.config["GB_FRIDAY"][2:4])

    # Work out which files need to be converted by looking at the filesystem.
    # If a talk has an edited file but no converted file, convert it!
    #
    # Anything in UPLOAD_DIR that looks like an edited file but is not one of
    # this year's is set aside and named below, rather than guessed at. It is
    # nearly always a leftover from last festival, but a typo in a hand-made
    # filename looks the same and would otherwise be silently ignored - a talk
    # that never converts and nobody notices until the USB build.
    edited_files = set()
    skipped_files = []
    for entry in os.scandir(app.config["UPLOAD_DIR"]):
        if not entry.name.endswith("_EDITED.mp3"):
            continue
        match = EDITED_FILE_RE.match(entry.name)
        if match is None or match["year"] != gb_year:
            skipped_files.append(entry.name)
            continue
        edited_files.add(match["id"])

    # A previous festival's conversions must not count as this one's, or a
    # leftover GB25_020_*.mp3 would suppress GB26's talk 020 for good.
    processed_files = {
        match["id"]
        for match in (
            PROCESSED_FILE_RE.match(entry.name)
            for entry in os.scandir(app.config["PROCESSED_DIR"])
        )
        if match is not None and match["year"] == gb_year
    }

    talks = edited_files - processed_files

    # Only convert talks that are in the database and cleared. A Query is
    # truthy whether or not it matches anything, so the obvious spelling of
    # this test passes everything: an uncleared talk gets converted, and an
    # id with no talk behind it reaches process_talk and fails there on
    # `talk.id`. Ask the database once and intersect - the ids in `talks` came
    # off zero-padded filenames, so the cleared ids are padded to match rather
    # than relying on SQLite quietly reading "020" as an integer.
    cleared_ids = {
        str(row.id).zfill(3)
        for row in Talk.query.where(Talk.is_cleared.is_(True)).all()
    }
    talks_to_process = sorted(talks & cleared_ids)

    # Edited, but not going anywhere: no talk of that id, or not cleared yet.
    # Both are ordinary states rather than errors, and both are invisible
    # unless said out loud.
    held_back = sorted(talks - cleared_ids)

    pprint.pprint("Processing Talks:")
    pprint.pprint(talks_to_process)
    if held_back:
        pprint.pprint("Edited, but not a cleared talk - not converting:")
        pprint.pprint(held_back)
    if skipped_files:
        pprint.pprint("Not an edited file for GB" + gb_year + " - ignoring:")
        pprint.pprint(sorted(skipped_files))

    with Pool(5) as p:
        p.map(process_talk, talks_to_process)


def burn_cd(talk_id, cd_index, cd_writer):
    talk_cd_files = [
        x for x in list(os.scandir(get_cd_dir_for_talk(talk_id))) if x.is_file()
    ]
    cd_files = talk_cd_files[::15][cd_index]
    subprocess.call(
        [
            "wodim",
            "dev=/dev/sg" + cd_writer,
            "-dao",
            "-pad",
            "-audio",
            "-eject",
            cd_files,
        ]
    )


@click.command(name="createdb")
@with_appcontext
def create_db():
    db.create_all()
    db.session.commit()
    print("Database tables created")


class Migration:
    """
    Simple migration system for incremental database updates

    Each migration should:
    - Have a unique version (format: NNN_descriptive_name)
    - Include a clear description of what it does
    - Provide an up_func that applies the changes
    - Optionally provide a down_func for rollbacks
    """

    def __init__(self, version, description, up_func, down_func=None, notes=None):
        self.version = version
        self.description = description
        self.up_func = up_func
        self.down_func = down_func
        self.notes = notes  # Additional documentation for complex migrations

    def apply(self):
        """Apply this migration"""
        print(f"Applying migration {self.version}: {self.description}")
        self.up_func()
        self._record_migration()

    def rollback(self):
        """Rollback this migration"""
        if self.down_func:
            print(f"Rolling back migration {self.version}: {self.description}")
            self.down_func()
            self._remove_migration_record()
        else:
            raise Exception(f"Migration {self.version} has no rollback function")

    def _record_migration(self):
        """Record that this migration has been applied"""
        from sqlalchemy import text
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (:version, datetime('now'))"
            ), {"version": self.version})

    def _remove_migration_record(self):
        """Remove migration record"""
        from sqlalchemy import text
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM schema_migrations WHERE version = :version"), {"version": self.version})


def ensure_migrations_table():
    """Ensure the schema_migrations table exists"""
    from sqlalchemy import text
    with db.engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """))


def get_applied_migrations():
    """Get list of applied migration versions"""
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version"))
            return {row[0] for row in result}
    except Exception:
        return set()


def create_rota_settings_table():
    """Migration: Create rota_settings table"""
    from .models import RotaSettings
    RotaSettings.__table__.create(db.engine, checkfirst=True)
    RotaSettings.initialize_defaults()


def add_recorder_time_constraints():
    """Migration: Add earliest_start_time and latest_end_time columns to recorders table"""
    from sqlalchemy import text

    try:
        # For SQLite, use ALTER TABLE to add columns
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE recorders ADD COLUMN earliest_start_time TIME'))
    except Exception as e:
        print(f"Note: earliest_start_time column may already exist: {e}")

    try:
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE recorders ADD COLUMN latest_end_time TIME'))
    except Exception as e:
        print(f"Note: latest_end_time column may already exist: {e}")


def add_talk_cancelled_field():
    """Migration: Add is_cancelled field to talks table"""
    from sqlalchemy import text

    try:
        # For SQLite, use ALTER TABLE to add column with default value
        with db.engine.begin() as conn:
            conn.execute(text('ALTER TABLE talks ADD COLUMN is_cancelled BOOLEAN DEFAULT 0'))
        print("Added is_cancelled column to talks table")
    except Exception as e:
        print(f"Note: is_cancelled column may already exist: {e}")


# Define all migrations here
#
# Migration Naming Convention:
# - Use format: NNN_descriptive_name (e.g., 001_create_rota_settings)
# - Always increment version numbers sequentially
# - Use descriptive names that explain what the migration does
#
# Documentation Requirements:
# - Always include a clear description
# - Add notes for complex migrations that affect multiple tables or data
# - Consider adding rollback functions for reversible operations
# - Document any manual steps required before/after migration
#
MIGRATIONS = [
    Migration(
        version="001_create_rota_settings",
        description="Create rota_settings table with default configuration",
        up_func=create_rota_settings_table,
        notes=(
            "Adds configurable rota generation settings to replace hardcoded values. "
            "Creates 7 default settings: shift_length, break_between_shifts, "
            "minimum_time_between_talks, max_talks_per_shift, same_venue_assignment_window, "
            "additional_talk_search_window, and additional_talk_minimum_gap. "
            "No existing data is affected."
        )
    ),

    Migration(
        version="002_add_recorder_time_constraints",
        description="Add earliest_start_time and latest_end_time fields to recorders",
        up_func=add_recorder_time_constraints,
        notes=(
            "Adds optional time constraint fields to recorders table: "
            "- earliest_start_time: Earliest time a recorder can start recording (nullable) "
            "- latest_end_time: Latest time a recorder needs to finish by (nullable) "
            "These fields allow recorders to specify availability windows. "
            "Existing recorders will have NULL values (no constraints). "
            "Rota generation will respect these constraints when assigning talks."
        )
    ),

    Migration(
        version="003_add_talk_cancelled_field",
        description="Add is_cancelled field to talks table for safe talk cancellation",
        up_func=add_talk_cancelled_field,
        notes=(
            "Adds is_cancelled field to talks table to allow marking talks as cancelled "
            "without deleting them or reusing talk IDs. This preserves data integrity "
            "while providing a safe way to handle cancelled talks. "
            "All existing talks will default to is_cancelled=False (active). "
            "The talks page will show cancelled status with filtering options."
        )
    ),

    # Template for future migrations:
    # Migration(
    #     version="004_descriptive_name",
    #     description="Brief description of what this migration does",
    #     up_func=your_migration_function,
    #     down_func=your_rollback_function,  # Optional
    #     notes=(
    #         "Detailed explanation of the migration including: "
    #         "- What tables/columns are affected "
    #         "- Any data transformations "
    #         "- Potential impact on existing functionality "
    #         "- Manual steps required before/after running migration"
    #     )
    # ),
]


@click.command(name="migrate")
@with_appcontext
def migrate_db():
    """Apply pending database migrations"""

    print("Checking for pending migrations...")

    try:
        # Ensure migrations table exists
        ensure_migrations_table()

        # Get applied migrations
        applied = get_applied_migrations()

        # Find pending migrations
        pending = [m for m in MIGRATIONS if m.version not in applied]

        if not pending:
            print("✓ No pending migrations")
            return

        print(f"Found {len(pending)} pending migration(s)")

        # Apply each pending migration
        for migration in pending:
            try:
                migration.apply()
                print(f"✓ Applied {migration.version}")
            except Exception as e:
                print(f"✗ Failed to apply {migration.version}: {e}")
                db.session.rollback()
                raise

        db.session.commit()
        print(f"Successfully applied {len(pending)} migration(s)!")

    except Exception as e:
        db.session.rollback()
        print(f"Migration failed: {e}")
        raise


@click.command(name="migration-status")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed migration information")
@with_appcontext
def migration_status(verbose):
    """Show migration status and documentation"""

    try:
        ensure_migrations_table()
        applied = get_applied_migrations()

        print("Migration Status:")
        print("=" * 70)

        for migration in MIGRATIONS:
            status = "✓ Applied" if migration.version in applied else "○ Pending"
            print(f"\n{status} {migration.version}")
            print(f"    Description: {migration.description}")

            if verbose and migration.notes:
                print(f"    Notes: {migration.notes}")

            if verbose:
                has_rollback = "Yes" if migration.down_func else "No"
                print(f"    Rollback available: {has_rollback}")

        print(f"\nSummary: {len(applied)}/{len(MIGRATIONS)} migrations applied")

        if not verbose:
            print("\nUse --verbose for detailed information about each migration")

    except Exception as e:
        print(f"Error checking migration status: {e}")


@click.command(name="load-sample-data")
@click.argument("table", type=click.Choice(["talks", "recorders", "editors"], case_sensitive=False))
@click.option("--clear", is_flag=True, help="Clear existing data before loading")
@with_appcontext
def load_sample_data(table, clear):
    """Load sample data from CSV files into specified table"""

    sample_data_dir = os.path.join(os.path.dirname(app.root_path), "sample_data")
    csv_file = os.path.join(sample_data_dir, f"{table.lower()}.csv")

    if not os.path.exists(csv_file):
        print(f"Error: Sample data file not found: {csv_file}")
        return

    try:
        if clear:
            print(f"Clearing existing {table} data...")
            if table.lower() == "talks":
                Talk.query.delete()
            elif table.lower() == "recorders":
                Recorder.query.delete()
            elif table.lower() == "editors":
                Editor.query.delete()
            db.session.commit()

        print(f"Loading sample {table} data from {csv_file}...")

        count = 0

        if table.lower() == "talks":
            # Talks go through the same parser as the /talks upload, so the
            # sample data is always a valid example of the real format.
            with open(csv_file, newline='', encoding='utf-8') as file:
                for talk_data in parse_talks_csv(file):
                    if db.session.get(Talk, talk_data['id']):
                        print(f"Talk ID {talk_data['id']} already exists, skipping...")
                        continue

                    db.session.add(Talk(**talk_data))
                    count += 1

            db.session.commit()
            print(f"Successfully loaded {count} {table} records!")
            return

        with open(csv_file, newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)

            for row in reader:
                if table.lower() == "recorders":
                    # Convert time strings to time objects
                    earliest_start = None
                    latest_end = None

                    if row['earliest_start_time']:
                        earliest_start = datetime.strptime(row['earliest_start_time'], '%H:%M:%S').time()
                    if row['latest_end_time']:
                        latest_end = datetime.strptime(row['latest_end_time'], '%H:%M:%S').time()

                    recorder_data = {
                        'name': row['name'],
                        'max_shifts_per_day': int(row['max_shifts_per_day']),
                        'earliest_start_time': earliest_start,
                        'latest_end_time': latest_end
                    }

                    # Check if recorder already exists
                    existing_recorder = Recorder.query.filter_by(name=recorder_data['name']).first()
                    if existing_recorder:
                        print(f"Recorder {recorder_data['name']} already exists, skipping...")
                        continue

                    recorder = Recorder(**recorder_data)
                    db.session.add(recorder)

                elif table.lower() == "editors":
                    editor_data = {'name': row['name']}

                    # Check if editor already exists
                    existing_editor = Editor.query.filter_by(name=editor_data['name']).first()
                    if existing_editor:
                        print(f"Editor {editor_data['name']} already exists, skipping...")
                        continue

                    editor = Editor(**editor_data)
                    db.session.add(editor)

                count += 1

        db.session.commit()
        print(f"Successfully loaded {count} {table} records!")

    except Exception as e:
        db.session.rollback()
        print(f"Error loading sample data: {e}")
        raise
