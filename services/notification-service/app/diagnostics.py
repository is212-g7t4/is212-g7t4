"""Developer inspection/replay; database access remains inside Notification.
python -m app.diagnostics list
python -m app.diagnostics replay <failure UUID>
Replay validates and saves the original envelope idempotently, never edits it.
"""

import argparse
import json
import os
from uuid import UUID
from app import store
from app.consumer import parse


def inspect(dsn):
    with store.transaction(dsn) as cursor:
        cursor.execute(
            'SELECT failure_id,error,created_at,replayed_at FROM public."NotificationFailure" ORDER BY created_at DESC LIMIT 100'
        )
        return [dict(row) for row in cursor.fetchall()]


def replay(dsn, identifier):
    identifier = str(UUID(identifier))
    with store.transaction(dsn) as cursor:
        cursor.execute(
            'SELECT body FROM public."NotificationFailure" WHERE failure_id=%s',
            (identifier,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Failure not found")
        envelope = parse(bytes(row["body"]))
    # Lost response between save and marker is safe: original source ID deduplicates.
    store.deliver(dsn, envelope)
    with store.transaction(dsn) as cursor:
        cursor.execute(
            'UPDATE public."NotificationFailure" SET replayed_at=now() WHERE failure_id=%s',
            (identifier,),
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["list", "replay"])
    parser.add_argument("id", nargs="?")
    args = parser.parse_args()
    dsn = os.environ["DATABASE_URL"]
    if args.action == "list":
        print(json.dumps(inspect(dsn), default=str))
    else:
        replay(dsn, args.id)


if __name__ == "__main__":
    main()
