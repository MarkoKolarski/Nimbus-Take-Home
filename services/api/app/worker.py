import time

from app.sync.runner import POLL_INTERVAL_SECONDS, claim_next_queued_job, run_sync


def main() -> None:
    print("worker started")
    while True:
        claimed = claim_next_queued_job()
        if claimed is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        job_id, user_id, directory_id = claimed
        run_sync(job_id, user_id, directory_id)


if __name__ == "__main__":
    main()
