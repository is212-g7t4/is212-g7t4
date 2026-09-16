"""Create/update the threads and messages collections: schema validators + indexes.

This is the MongoDB equivalent of a Postgres migration file — the source of
truth for the two Mongo collections in the system (owned by Forum /
Communication Service, see ../../docs/mongodb-setup.md). Safe to run
repeatedly: it creates a collection only if missing, otherwise updates its
validator in place, and index creation is a no-op if the same index already
exists.

Requires MONGODB_URL (and optionally MONGODB_DB) in the environment, loaded
from the repo-root .env — see ../../.env.example.

Usage:
    pip install "pymongo[srv]" python-dotenv
    python database/mongodb/init_mongo.py
"""

import os

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient

load_dotenv()

THREADS_COLLECTION = "threads"
MESSAGES_COLLECTION = "messages"

THREADS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["entityType", "entityId", "status", "participants"],
        "properties": {
            "entityType": {
                "bsonType": "string",
                "description": "e.g. EVENT, BOOKING, EQUIPMENT_REQUEST",
            },
            "entityId": {
                "bsonType": "string",
                "description": "PK of the row this thread is attached to, in whichever Postgres service owns it",
            },
            "status": {
                "bsonType": "string",
                "maxLength": 50,
            },
            "participants": {
                "bsonType": "array",
                "description": "flexible list of participant info (e.g. user IDs)",
            },
        },
    }
}

MESSAGES_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["threadId", "senderId", "content", "timestamp"],
        "properties": {
            "threadId": {
                "bsonType": "objectId",
                "description": "logical FK -> threads._id",
            },
            "senderId": {
                "bsonType": "string",
                "description": "user_service.user_id — not a real FK, just a plain field",
            },
            "content": {"bsonType": "string"},
            "timestamp": {"bsonType": "date"},
            "attachments": {
                "bsonType": "array",
                "description": "list of {filename, contentType, size, data}; total size kept under the 16MB document limit",
                "items": {
                    "bsonType": "object",
                    "required": ["filename", "contentType", "size", "data"],
                    "properties": {
                        "filename": {"bsonType": "string"},
                        "contentType": {"bsonType": "string"},
                        "size": {"bsonType": "int"},
                        "data": {"bsonType": "binData"},
                    },
                },
            },
        },
    }
}


def _create_or_update_collection(db, name: str, validator: dict) -> None:
    if name in db.list_collection_names():
        db.command("collMod", name, validator=validator)
    else:
        db.create_collection(name, validator=validator)


def main() -> None:
    client = MongoClient(os.environ["MONGODB_URL"])
    db = client[os.environ.get("MONGODB_DB", "forum_service")]

    _create_or_update_collection(db, THREADS_COLLECTION, THREADS_VALIDATOR)
    db[THREADS_COLLECTION].create_index(
        [("entityType", ASCENDING), ("entityId", ASCENDING)],
        name="entityType_entityId_unique",
        unique=True,
    )

    _create_or_update_collection(db, MESSAGES_COLLECTION, MESSAGES_VALIDATOR)
    db[MESSAGES_COLLECTION].create_index(
        [("threadId", ASCENDING), ("timestamp", ASCENDING)],
        name="threadId_timestamp",
    )

    print(f"{THREADS_COLLECTION} and {MESSAGES_COLLECTION} ready in database {db.name!r}.")


if __name__ == "__main__":
    main()
