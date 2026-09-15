#!/usr/bin/env python3
"""
Pipeline Orchestrator
---------------------
Seamlessly connects Stage 1 (LinkedIn Profile URL Discovery Tool)
to Stage 2 (Candidate Filtration & Enrichment Agent) with zero data breakage,
format normalization, state tracking, and credential security.
"""

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("PipelineOrchestrator")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "pipeline_config.json"


def load_dotenv(env_path: Path) -> None:
    """Simple .env loader to populate os.environ."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            value = value.strip().strip("'\"")
            os.environ[key] = value


# Load root .env if present
load_dotenv(BASE_DIR / ".env")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_linkedin_url(url: str) -> str:
    """Sanitize and normalize LinkedIn profile URL to canonical form."""
    if not url:
        return ""
    url = url.strip()
    match = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9%\-_]+)", url, re.IGNORECASE)
    if match:
        clean_handle = match.group(1).rstrip("/")
        return f"https://www.linkedin.com/in/{clean_handle}"
    return ""


def load_pipeline_state(state_file: Path) -> dict:
    """Load state tracking ledger of processed URLs."""
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Pipeline state file corrupted, creating new state tracking.")
    return {"processed_urls": {}, "last_run": None}


def save_pipeline_state(state_file: Path, state_data: dict) -> None:
    """Atomically save state tracking ledger."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_file.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2, ensure_ascii=False)
    temp_file.replace(state_file)


def run_stage1(stage1_dir: Path, query: str = None, postgraduate: bool = False, limit: int = 10, location: str = None) -> bool:
    """Execute Stage 1 scraper via subprocess."""
    logger.info("==========================================")
    logger.info("STARTING STAGE 1: LinkedIn URL Discovery")
    logger.info("==========================================")

    cmd = [sys.executable, "-m", "src.main", "--limit", str(limit)]
    if postgraduate:
        cmd.append("--postgraduate")
    elif query:
        cmd.extend(["--query", query])
    else:
        cmd.append("--postgraduate")

    if location:
        cmd.extend(["--location", location])

    logger.info(f"Running command: {' '.join(cmd)} in {stage1_dir}")
    try:
        env = os.environ.copy()
        res = subprocess.run(cmd, cwd=stage1_dir, env=env, check=False)
        if res.returncode != 0:
            logger.error(f"Stage 1 finished with non-zero exit code: {res.returncode}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to run Stage 1: {e}")
        return False


def transform_and_sync(config: dict) -> tuple[int, Path]:
    """
    Transforms Stage 1 outputs (TXT & CSV) into Stage 2's JSON schema safely,
    filtering out previously processed URLs using pipeline_state.json.
    """
    logger.info("------------------------------------------")
    logger.info("TRANSFORMING STAGE 1 DATA FOR STAGE 2")
    logger.info("------------------------------------------")

    stage1_dir = BASE_DIR / config["stage1"]["dir"]
    txt_path = stage1_dir / config["stage1"]["urls_txt"]
    csv_path = stage1_dir / config["stage1"]["leads_csv"]

    stage2_dir = BASE_DIR / config["stage2"]["dir"]
    stage2_input = stage2_dir / config["stage2"]["urls_json"]

    state_file = BASE_DIR / config["pipeline_state"]
    state_data = load_pipeline_state(state_file)
    processed_set = set(state_data.get("processed_urls", {}).keys())

    discovered_urls = []

    # 1. Read from plain text URL file
    if txt_path.exists():
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                norm_url = normalize_linkedin_url(line)
                if norm_url and norm_url not in discovered_urls:
                    discovered_urls.append(norm_url)

    # 2. Read from CSV leads file
    if csv_path.exists():
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_url = row.get("linkedin_url", "")
                    norm_url = normalize_linkedin_url(raw_url)
                    if norm_url and norm_url not in discovered_urls:
                        discovered_urls.append(norm_url)
        except Exception as e:
            logger.warning(f"Could not read CSV file {csv_path}: {e}")

    logger.info(f"Total canonical URLs collected from Stage 1: {len(discovered_urls)}")

    # Filter out already processed URLs
    new_urls = [url for url in discovered_urls if url not in processed_set]
    logger.info(f"New un-processed URLs queued for Stage 2: {len(new_urls)} (Skipped {len(discovered_urls) - len(new_urls)} duplicate/processed)")

    # Ensure Stage 2 directory exists
    stage2_input.parent.mkdir(parents=True, exist_ok=True)

    # Write Stage 2 JSON input format atomically
    temp_input = stage2_input.with_suffix(".tmp")
    with open(temp_input, "w", encoding="utf-8") as f:
        json.dump(new_urls, f, indent=2, ensure_ascii=False)
    temp_input.replace(stage2_input)

    logger.info(f"Stage 2 input written cleanly to: {stage2_input}")
    return len(new_urls), stage2_input


def run_stage2(config: dict, delay: float = 3.0, headless: bool = True) -> bool:
    """Execute Stage 2 qualification & filter pipeline via subprocess."""
    logger.info("==========================================")
    logger.info("STARTING STAGE 2: Candidate Qualification")
    logger.info("==========================================")

    stage2_dir = BASE_DIR / config["stage2"]["dir"]
    urls_file = config["stage2"]["urls_json"]
    out_file = config["stage2"]["output_json"]
    report_file = config["stage2"]["report_json"]

    cmd = [
        sys.executable, "filter_pg_students.py",
        "--urls", urls_file,
        "--out", out_file,
        "--report", report_file,
        "--delay", str(delay)
    ]

    if not headless:
        cmd.append("--headed")

    logger.info(f"Running command: {' '.join(cmd)} in {stage2_dir}")
    try:
        env = os.environ.copy()
        res = subprocess.run(cmd, cwd=stage2_dir, env=env, check=False)
        if res.returncode != 0:
            logger.error(f"Stage 2 finished with exit code: {res.returncode}")
            return False
        
        # Sync newly processed URLs back into state tracking ledger
        sync_results_to_state(config)
        return True
    except Exception as e:
        logger.error(f"Failed to run Stage 2: {e}")
        return False


def sync_results_to_state(config: dict) -> None:
    """Update pipeline_state.json with details from Stage 2 execution."""
    stage2_dir = BASE_DIR / config["stage2"]["dir"]
    report_path = stage2_dir / config["stage2"]["report_json"]
    state_file = BASE_DIR / config["pipeline_state"]

    if not report_path.exists():
        logger.warning("No filter report generated by Stage 2.")
        return

    state_data = load_pipeline_state(state_file)
    processed = state_data.setdefault("processed_urls", {})

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report_records = json.load(f)
            for rec in report_records:
                url = normalize_linkedin_url(rec.get("url", ""))
                if url:
                    processed[url] = {
                        "status": rec.get("status"),
                        "reason": rec.get("reason"),
                        "ug_university": rec.get("ug_university"),
                        "pg_university": rec.get("pg_university"),
                        "pg_year": rec.get("pg_year"),
                        "processed_at": datetime.now().isoformat()
                    }
        state_data["last_run"] = datetime.now().isoformat()
        save_pipeline_state(state_file, state_data)
        logger.info(f"Pipeline state updated. Total tracked profiles: {len(processed)}")
    except Exception as e:
        logger.error(f"Failed to sync Stage 2 results to pipeline state: {e}")


def main():
    parser = argparse.ArgumentParser(description="End-to-End Candidate Sourcing & Filtering Pipeline")
    parser.add_argument("--query", "-q", type=str, help="Search keywords for Stage 1")
    parser.add_argument("--postgraduate", action="store_true", help="Run Stage 1 postgraduate discovery set")
    parser.add_argument("--limit", type=int, default=10, help="Max profiles to scrape in Stage 1")
    parser.add_argument("--location", type=str, help="Location filter for Stage 1")
    parser.add_argument("--sync-only", action="store_true", help="Skip Stage 1 discovery and run transform + Stage 2 on existing outputs")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode (visible window)")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between profiles in Stage 2")

    args = parser.parse_args()
    config = load_config()

    # Step 1: Run Stage 1 Discovery (unless --sync-only is passed)
    if not args.sync_only:
        stage1_dir = BASE_DIR / config["stage1"]["dir"]
        success = run_stage1(
            stage1_dir=stage1_dir,
            query=args.query,
            postgraduate=args.postgraduate,
            limit=args.limit,
            location=args.location
        )
        if not success:
            logger.warning("Stage 1 discovery hit a restriction or warning. Proceeding to process collected URLs...")

    # Step 2: Transform & Deduplicate Stage 1 outputs for Stage 2
    new_url_count, stage2_input_path = transform_and_sync(config)

    if new_url_count == 0:
        logger.info("No new un-processed URLs to pass to Stage 2. Pipeline execution complete.")
        return

    # Step 3: Run Stage 2 Qualification & Filtering
    stage2_success = run_stage2(
        config=config,
        delay=args.delay,
        headless=not args.headed
    )

    if stage2_success:
        logger.info("==========================================")
        logger.info("PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
        logger.info("==========================================")
    else:
        logger.error("Pipeline completed with errors in Stage 2.")


if __name__ == "__main__":
    main()
