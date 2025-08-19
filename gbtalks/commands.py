import threading
import os
import json
import subprocess
import csv
from datetime import datetime
import click
from flask import current_app as app
from flask.cli import with_appcontext
from werkzeug.exceptions import MethodNotAllowed, NotFound

import shutil

from .models import db, Talk, Recorder, Editor
import sys
from tendo import singleton
from pydub import AudioSegment

from multiprocessing import Pool
from mutagen.id3 import ID3, TALB, TCOP, TIT2, TPE1, TPE2, TRCK, TDRC, COMM, TCMP, APIC
import pprint

from .libgbtalks import (
    get_path_for_file,
    gb_time_to_datetime
)

def run_command(cmd):
    with semaphore:
        os.system(cmd)


def get_cd_dir_for_talk(talk):
    return (
        app.config["CD_DIR"]
        + "/gb"
        + app.config["GB_SHORT_YEAR"]
        + "-"
        + str(talk).zfill(3)
        + "/"
    )


def process_talk(talk_id):
    top = AudioSegment.from_file(app.config["TOP_TAIL_DIR"] + "/" + "top.mp3")
    tail = AudioSegment.from_file(app.config["TOP_TAIL_DIR"] + "/" + "tail.mp3")

    talk = db.session.get(Talk, talk_id)

    # Add the top and tail, create a high-quality mp3
    hq_mp3 = top + AudioSegment.from_file(get_path_for_file(talk.id, "edited")) + tail

    # Export a WAV file of the top/tailed audio into /tmp for further processing
    toptail_path = "/tmp/toptailed" + str(talk.id) + ".wav"
    hq_mp3.export(toptail_path, format="wav")

    # Normalise to a fixed level
    normalized_path = "/tmp/normalized" + str(talk.id) + ".wav"
    subprocess.call(
        [
            "ffmpeg-normalize",
            toptail_path,
            "-o",
            normalized_path,
            "--loudness-range-target",
            "3",
            "-t",
            "-13",
            "-f",
            "-ar",
            "44100",
        ]
    )

    # Load the normalised file back in
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



    # Clean up
    if os.path.exists(toptail_path):
        os.remove(toptail_path)

    if os.path.exists(normalized_path):
        os.remove(normalized_path)

    # Copy the file to the web_mp3 directory with filename format gbXX-XXXmp3.mp3
    shutil.copy(get_path_for_file(str(talk.id), "processed", talk.title, talk.speaker), get_path_for_file(str(talk.id), "web_mp3"))

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

    # Make sure we only run one of these at a time
    only_once_preventer = singleton.SingleInstance(flavor_id="convert_talks")

    gb_year = str(app.config["GB_FRIDAY"][2:4])
    gb_prefix = "gb" + gb_year + "-"

    # Work out which files need to be converted by looking at the filesystem
    # If a talk has an edited file but no converted file, convert it!

    edited_files = (
        set(
            [
                x.name.replace("_EDITED.mp3", "").replace(gb_prefix, "")
                for x in os.scandir(app.config["UPLOAD_DIR"])
                if x.name.endswith("EDITED.mp3")
            ]
        )
        or set()
    )
    processed_files = (
        set(
            [
                x.name.split("_")[1]
                for x in os.scandir(app.config["PROCESSED_DIR"])
                if x.name.endswith(".mp3")
            ]
        )
        or set()
    )

    talks = edited_files
    talks.difference_update(processed_files)

    talks_to_process = [x for x in list(talks) if Talk.query.where(Talk.id==x, Talk.is_cleared)] or []

    pprint.pprint("Processing Talks:")
    pprint.pprint(talks_to_process)

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
    except:
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
    
    # Template for future migrations:
    # Migration(
    #     version="002_descriptive_name",
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
        
        with open(csv_file, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            count = 0
            
            for row in reader:
                if table.lower() == "talks":
                    # Convert string values to appropriate types
                    talk_data = {
                        'id': int(row['id']),
                        'title': row['title'],
                        'description': row['description'],
                        'speaker': row['speaker'],
                        'day': row['day'],
                        'start_time': datetime.strptime(row['start_time'], '%Y-%m-%d %H:%M:%S'),
                        'end_time': datetime.strptime(row['end_time'], '%Y-%m-%d %H:%M:%S'),
                        'venue': row['venue'],
                        'is_priority': bool(int(row['is_priority'])),
                        'is_rotaed': bool(int(row['is_rotaed'])),
                        'is_cleared': bool(int(row['is_cleared'])),
                        'has_explicit_warning_sticker': bool(int(row['has_explicit_warning_sticker'])),
                        'has_distressing_content_warning_sticker': bool(int(row['has_distressing_content_warning_sticker'])),
                        'has_technical_issues_sticker': bool(int(row['has_technical_issues_sticker'])),
                        'has_copyright_removal_sticker': bool(int(row['has_copyright_removal_sticker'])),
                        'recorder_name': row['recorder_name'] if row['recorder_name'] else None,
                        'editor_name': row['editor_name'] if row['editor_name'] else None
                    }
                    
                    # Check if talk already exists
                    existing_talk = Talk.query.filter_by(id=talk_data['id']).first()
                    if existing_talk:
                        print(f"Talk ID {talk_data['id']} already exists, skipping...")
                        continue
                        
                    talk = Talk(**talk_data)
                    db.session.add(talk)
                    
                elif table.lower() == "recorders":
                    # Convert time strings to time objects
                    from datetime import time
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
