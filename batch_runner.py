from __future__ import annotations

import random
import time


import db
from gemini_extract import extract_students
from linkedin_scraper import LinkedInScraper
from fp.fp import FreeProxy

BATCH_SIZE = 20
MAX_PROFILES_PER_UNIVERSITY = 30
BATCH_BREAK = (60, 120)


def run_batches(queue, alias_map, no_login=False):
    all_rows = []

    batches = [
        queue[i:i + BATCH_SIZE]
        for i in range(0, len(queue), BATCH_SIZE)
        ]

    total_batches = len(batches)

    for batch_index, batch in enumerate(batches, start=1):

        print(f"\n{'=' * 60}")
        print(f"Starting Batch {batch_index}/{total_batches}")
        print(f"{'=' * 60}\n")

        proxy = FreeProxy(rand=True).get()

        print(f"[proxy] Using {proxy}")

        scraper = LinkedInScraper()

        try:
            scraper.start(proxy=proxy)
            scraper.login(no_login=no_login)
               
            for uni_index, uni in enumerate(batch, start=1):

                name = uni["name"]
                aliases = alias_map.get(name.casefold(), [])

                print(
                    f"[Batch {batch_index}] "
                    f"[{uni_index}/{len(batch)}] "
                    f"{name}"
                )

                db.set_status(uni["id"], "in_progress")

                try:

                    retry = 0

                    while True:

                        try:

                            blobs = scraper.search_university(name, aliases)
                            break

                        except Exception as exc:

                            if str(exc) != "GOOGLE_CAPTCHA":
                                raise

                            retry += 1

                            if retry > 5:
                                raise Exception("Maximum proxy retries exceeded")

                            print(f"\n[captcha] Retry {retry}/5")

                            scraper.close()

                            proxy = FreeProxy(rand=True).get()
                            try:
                                proxy = FreeProxy(rand=True).get()
                            except Exception:
                                proxy = None

                            print(f"[proxy] Switched to {proxy}")

                            scraper = LinkedInScraper()

                            scraper.start(proxy=proxy)

                            scraper.login(no_login=no_login)

                    students = []
                    seen = set()

                    stop = False

                    for blob in blobs:

                        extracted = extract_students(blob, name, aliases)

                        for student in extracted:

                            url = student.get("profile_url")

                            if not url:
                                continue

                            if url in seen:
                                continue

                            seen.add(url)
                            students.append(student)

                            if len(students) >= MAX_PROFILES_PER_UNIVERSITY:
                                stop = True
                                break

                        if stop:
                            break

                    saved = db.save_students(uni["id"], students)
                    db.set_status(uni["id"], "done")

                    print(f"    -> {saved} profiles saved\n")
                    wait = random.uniform(20, 40)
                    print(f"    [wait] Sleeping {wait:.0f} sec before next university...")
                    time.sleep(wait)

                    for student in students:
                        all_rows.append(
                            {
                                **student,
                                "university": name,
                            }
                        )
                    if uni_index % 10 == 0 and uni_index != len(batch):
                        wait = random.uniform(90, 180)
                        print(f"\n[break] {uni_index} universities completed.")
                        print(f"[break] Sleeping {wait:.0f} sec...\n")
                        time.sleep(wait)    

                except Exception as exc:

                    db.set_status(
                        uni["id"],
                        "failed",
                        str(exc)[:500],
                    )

                    print(f"    !! failed: {exc}\n")

        finally:

            try:
                scraper.close()
            except Exception:
                pass 
        if batch_index < total_batches:

            wait = random.uniform(*BATCH_BREAK)

            print(
                f"\nBatch {batch_index} completed."
                f"\nSleeping for {wait:.0f} seconds..."
            )

            time.sleep(wait)

    return all_rows