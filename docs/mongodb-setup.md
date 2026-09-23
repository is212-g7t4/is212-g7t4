# MongoDB setup — for team members

How to connect to the shared MongoDB Atlas cluster and set up the
`threads`/`messages` collections it holds. This is the one MongoDB data
store in the system, owned by **Forum / Communication Service** (see
[AGENTS.md](../AGENTS.md)) — no other service touches it.

## 1. Get the connection string

The connection string needs a real database user password, which is **not**
committed anywhere in this repo.

1. Log into [MongoDB Atlas](https://cloud.mongodb.com) with the account
   that was added to the `is212-g7t4` project.
2. Open the **Cluster0** cluster → **Connect** → **Drivers**, pick Python,
   and copy the connection string.
3. Get the database user password from whoever set up the project, or reset
   it yourself under **Database Access** (this invalidates the old password
   for everyone using it).

## 2. Set up your `.env`

Copy the root `.env.example` to `.env` (if you haven't already for
Supabase) and fill in the real password in `MONGODB_URL`. `MONGODB_DB`
(`forum_service`) is already filled in.

**Never commit `.env`** — it's already covered by `.gitignore`.

## 3. Install the driver

```
python -m pip install "pymongo[srv]" python-dotenv
```

## 4. The collections

There are **two** collections in the `forum_service` database: `threads`
(one per entity being discussed) and `messages` (the individual posts
within a thread). Mongo was chosen because this data is variable-shape and
append-only with no relational joins needed (see
[docs/microservices-diagram-notes.md](microservices-diagram-notes.md) for
the full rationale).

**`threads`**

| Field | Type | Notes |
|---|---|---|
| `_id` | ObjectId | threadId |
| `entityType` | string | `EVENT`, `BOOKING`, `EQUIPMENT_REQUEST`, ... |
| `entityId` | string | PK of the row this thread is attached to, in whichever Postgres service owns it |
| `status` | string (max 50 chars) | |
| `participants` | array | flexible — e.g. a list of user IDs |

Unique compound index on `{entityType: 1, entityId: 1}` — one thread per
entity.

**`messages`**

| Field | Type | Notes |
|---|---|---|
| `_id` | string (UUID) | messageId — app-generated, not Mongo's auto ObjectId |
| `threadId` | ObjectId | logical FK -> `threads._id` |
| `senderId` | string | `"User".user_id` — not a real FK, just a plain field |
| `content` | string | |
| `timestamp` | date | |
| `attachments` | array | optional; list of `{filename, contentType, size, data}`, `data` is the raw file bytes |

Compound index on `{threadId: 1, timestamp: 1}` — fetch a thread's messages
in order.

**Attachments and the 16MB limit:** attachment bytes are stored inline in
the message document (not in external storage), so the whole document —
content, attachments, everything — counts against MongoDB's hard 16MB
per-document limit. Whatever writes messages should check the total
attachment size before inserting and reject anything that would push the
document close to that limit, rather than letting Mongo throw an opaque
error.

The source of truth for both collections' validators + indexes is
[`database/mongodb/init_mongo.py`](../database/mongodb/init_mongo.py) —
Mongo has no migration files the way Postgres does, so that script is the
equivalent. Run it once your `.env` is filled in:

```
python database/mongodb/init_mongo.py
```

Safe to re-run any time — it creates a collection if missing, or updates
its validator in place if it already exists.

## 5. Example: connecting from Python

```python
import os
from pymongo import MongoClient

def get_db():
    client = MongoClient(os.environ["MONGODB_URL"])
    return client[os.environ.get("MONGODB_DB", "forum_service")]

# Example: find the thread for a booking, then its messages in order
db = get_db()
thread = db["threads"].find_one({"entityType": "BOOKING", "entityId": "42"})
messages = list(db["messages"].find({"threadId": thread["_id"]}).sort("timestamp", 1))
```

## 6. If you need to change the schema

Edit the relevant `VALIDATOR` dict in
[`database/mongodb/init_mongo.py`](../database/mongodb/init_mongo.py) and
re-run it against the shared cluster. Don't change a validator by hand in
the Atlas UI — keep the script as the committed source of truth so
everyone's collection shape matches. Coordinate with the team before
changing a field another service's code already depends on.
