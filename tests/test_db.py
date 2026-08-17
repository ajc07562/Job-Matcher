import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.config as config  # noqa: E402

# Point at a throwaway DB file before importing backend.db, so tests never
# touch the real job_matcher.db used by the running app.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
config.DB_FILE = _tmp_db.name

from backend import db  # noqa: E402

db.DB_FILE = _tmp_db.name
db.init_db()


def test_create_and_fetch_user():
    user = db.create_user("Test@Example.com", "hash123")
    assert user["email"] == "test@example.com"  # normalized to lowercase

    fetched = db.get_user_by_email("TEST@example.com")
    assert fetched is not None
    assert fetched["id"] == user["id"]


def test_get_missing_user_returns_none():
    assert db.get_user_by_email("nobody@example.com") is None


def test_duplicate_email_rejected():
    db.create_user("dup@example.com", "hash1")
    try:
        db.create_user("dup@example.com", "hash2")
        assert False, "expected an integrity error"
    except Exception:
        pass


def test_save_match_and_upsert():
    user = db.create_user("saver@example.com", "hash")
    m1 = db.save_match(user["id"], "job-1", "Acme", "Engineer", 0.8, "Good fit", "https://x.com")
    assert m1["final_score"] == 0.8

    # Saving the same job again should update, not duplicate
    m2 = db.save_match(user["id"], "job-1", "Acme", "Engineer", 0.95, "Even better", "https://x.com")
    assert m2["final_score"] == 0.95

    history = db.get_saved_matches(user["id"])
    assert len(history) == 1


def test_delete_saved_match():
    user = db.create_user("deleter@example.com", "hash")
    db.save_match(user["id"], "job-a", "Acme", "Engineer", 0.7, None, None)
    db.save_match(user["id"], "job-b", "Beta", "Analyst", 0.6, None, None)

    db.delete_saved_match(user["id"], "job-a")
    history = db.get_saved_matches(user["id"])
    assert len(history) == 1
    assert history[0]["job_id"] == "job-b"
