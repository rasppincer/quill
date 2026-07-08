import os
import sys
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from quill.db import Base
from quill.models import Project, DocumentNode, StageState, Metrics, AgentLog

def migrate():
    parser = argparse.ArgumentParser(description="Migrate Quill data from SQLite to PostgreSQL")
    parser.add_argument("--source", default="sqlite:///quill.db", help="Source SQLite connection string")
    parser.add_argument("--dest", required=True, help="Destination PostgreSQL connection string (e.g. postgresql://user:pass@host/dbname)")
    args = parser.parse_args()

    source_url = args.source
    dest_url = args.dest

    print(f"Starting migration from {source_url} to {dest_url}...")

    # Create engines
    src_engine = create_engine(source_url)
    dst_engine = create_engine(dest_url)

    # Create sessions
    SrcSession = sessionmaker(bind=src_engine)
    DstSession = sessionmaker(bind=dst_engine)

    src_session = SrcSession()
    dst_session = DstSession()

    try:
        # 1. Ensure destination schema is up to date
        print("Initializing target schema...")
        Base.metadata.create_all(dst_engine)

        # Order of migration to respect foreign keys
        tables = [
            (Project, "projects"),
            (DocumentNode, "document_nodes"),
            (StageState, "stage_states"),
            (Metrics, "metrics"),
            (AgentLog, "agent_logs"),
        ]

        for model, table_name in tables:
            print(f"Migrating {table_name}...")
            # Fetch all records from source
            records = src_session.query(model).all()
            count = len(records)
            print(f"  Found {count} records.")

            if count == 0:
                continue

            # Convert SQLAlchemy objects to dicts for easy insertion
            data_to_insert = []
            for rec in records:
                # Extract values based on mapped columns
                row = {c.name: getattr(rec, c.name) for c in model.__table__.columns}
                data_to_insert.append(row)

            # Insert into destination
            # Using bulk insert via core for efficiency
            dst_session.execute(model.__table__.insert(), data_to_insert)
            dst_session.commit()
            print(f"  Successfully migrated {count} records.")

        print("\nMigration completed successfully!")

        # Verification phase
        print("\n--- Verification ---")
        for model, table_name in tables:
            src_count = src_session.query(model).count()
            dst_count = dst_session.query(model).count()
            status = "✅" if src_count == dst_count else "❌"
            print(f"{status} {table_name}: Source={src_count}, Dest={dst_count}")

    except Exception as e:
        print(f"Error during migration: {e}")
        dst_session.rollback()
        sys.exit(1)
    finally:
        src_session.close()
        dst_session.close()

if __name__ == "__main__":
    migrate()
