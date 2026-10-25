"""export Job: RUN_ID で作られた note を集計し、成果物を DB に書いて終了する。破棄前提。

検証したいのは「テストが Job を起動 → 成果物をアサート」の型。処理内容に意味はない。
"""

import json
import logging
import os
import sys
import time

import redis

RUN_ID = os.environ["RUN_ID"]
REDIS_URL = os.environ["REDIS_URL"]
JOB_NAME = os.environ.get("JOB_NAME", "-")

logging.basicConfig(format=f"%(asctime)s %(levelname)s run_id={RUN_ID} %(message)s", level=logging.INFO)
log = logging.getLogger("export")


def main() -> int:
    db = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    started_at = int(time.time())
    note_ids = sorted(db.smembers(f"run:{RUN_ID}"))
    titles = [db.hget(f"note:{i}", "title") for i in note_ids]
    log.info("exporting %d notes (job=%s)", len(note_ids), JOB_NAME)

    # 成果物: export:<run_id>  hash (status, note_count, titles, job_name, started_at, finished_at)
    db.hset(f"export:{RUN_ID}", mapping={
        "status": "done",
        "note_count": len(note_ids),
        "titles": json.dumps(titles, ensure_ascii=False),
        "job_name": JOB_NAME,
        "started_at": started_at,
        "finished_at": int(time.time()),
    })
    log.info("wrote export:%s", RUN_ID)
    return 0


if __name__ == "__main__":
    sys.exit(main())
