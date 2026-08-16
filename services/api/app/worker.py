import time


def main() -> None:
    # Real SKIP LOCKED polling loop lands in the "Sync state + worker" block.
    print("worker started, nothing to poll yet")
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
