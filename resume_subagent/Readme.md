# 📄 In-Memory Resume Scraper Sub-Agent

A high-speed, zero-disk-storage document parsing sub-agent designed to extract structured candidate data (specifically target contact details like Email and Phone, alongside missing experience/skills) from unstructured files (PDF, DOCX).

This module operates as a lightweight, memory-bounded enrichment engine within the primary scraping pipeline — triggered when primary profile scrapers return incomplete records.

---

## 📌 Table of Contents

- [Overview](#-overview)
- [Sub-Agent Architecture](#-sub-agent-architecture)
- [Zero-Disk In-Memory Workflow](#-zero-disk-in-memory-workflow)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
- [Configuration](#-configuration)
- [Input / Output Schema](#-input--output-schema)
- [Technical Challenges & Mitigations](#-technical-challenges--mitigations)

---

## 🔍 Overview

Traditional PDF parsing engines write files to disk, creating I/O bottlenecks and storage overhead. This sub-agent fetches candidate resumes directly into RAM as raw byte streams, parses layout and plain text in-memory using lightweight parsers, runs a hybrid **Regex + LLM** extraction pipeline, and instantly discards the stream.

It is specifically optimized to catch missing candidate contact attributes (Email, Phone Number) while keeping memory usage strictly bounded to a single active stream (typically < 5MB).

---

## 🏗 Sub-Agent Architecture

```
                  +-----------------------------------+
                  |  Trigger: Null Values Identified  |
                  |  (e.g., Missing Email / Phone)    |
                  +-----------------------------------+
                                    |
                                    v
            +-----------------------------------------------+
            |    1. In-Memory Streaming Fetcher             |
            | - HTTP GET Stream via `httpx` / `requests`    |
            | - Load directly into `io.BytesIO(buffer)`     |
            |   (Zero Local Disk Storage)                   |
            +-----------------------------------------------+
                                    |
                                    v
            +-----------------------------------------------+
            |    2. Light-Footprint In-Memory Parser        |
            | - Pass `BytesIO` directly to `fitz.open()`    |
            | - Fast spatial & plain text extraction        |
            | - Context Manager closes stream immediately   |
            +-----------------------------------------------+
                                    |
                                    v
            +-----------------------------------------------+
            |    3. Fast Regular Expression Filter          |
            | - Regex pass for Email & Phone patterns       |
            | - Bypasses LLM cost if simple contact found   |
            +-----------------------------------------------+
                                    |
                          /                   \
                  (Found / Complete)    (Missing / Complex)
                        /                       \
                       v                         v
            +---------------------+   +---------------------+
            | High-Speed Direct   |   | LLM Structured      |
            | Output Mapping      |   | Extraction Engine   |
            |                     |   | (Pydantic / Schema) |
            +---------------------+   +---------------------+
                       \                         /
                        \                       /
                         v                     v
            +-----------------------------------------------+
            |    4. Memory Garbage Collection (`gc`)        |
            | - Discard `BytesIO` buffer & `fitz` doc       |
            | - Reclaim RAM immediately                     |
            +-----------------------------------------------+
                                    |
                                    v
                  +-----------------------------------+
                  |  Return Standardized Payload to   |
                  |          Merge Stage              |
                  +-----------------------------------+
```

---

## 🔄 Zero-Disk In-Memory Workflow

### In-Memory Stream Ingestion
Fetches the resume file over HTTP as a raw binary response (`response.content`) directly into Python's `io.BytesIO` buffer. **Zero bytes are written to disk.**

### Fast In-Memory Extraction
Passes the `BytesIO` object straight to PyMuPDF (`fitz.open(stream=..., filetype="pdf")`) to extract text and spatial blocks directly from RAM.

### Hybrid Extraction Engine (Regex → LLM)

- **Stage 1 (Regex Pre-Filter)**: Runs optimized regular expressions to rapidly detect standard candidate email addresses and international phone numbers without incurring API latency or LLM token costs.
- **Stage 2 (LLM Fallback)**: If contact details use obscured formatting (e.g., `john [at] email [dot] com`) or non-contact fields (experience, skills) are requested, text is routed to an LLM with strict Pydantic schema enforcement.

### Instant Resource Disposal & Garbage Collection
The `fitz` document object and `BytesIO` stream are explicitly closed and deleted inside a `finally` block, triggering garbage collection (`gc.collect()`) to prevent RAM buildup.

---

## ✨ Features

- **Zero Local Storage Overhead**: Never writes temporary `.pdf` or `.docx` files to the filesystem, eliminating local storage management and file cleanup routines.
- **Low Memory Footprint**: Bounded RAM consumption (processes 1 stream at a time, using ~2–5 MB of memory per active resume).
- **Targeted Contact Extraction**: Uses ultra-fast regex filters for candidate email and phone detection, avoiding unnecessary LLM calls when basic contact info is all that's missing.
- **Type-Safe Data Schema**: Employs Pydantic validation to ensure phone numbers, emails, and experience arrays match target database types before merging.

---

## 🛠 Tech Stack

| Component                    | Technology                                     |
| ---------------------------- | ---------------------------------------------- |
| **Core Runtime**             | Python 3.10+                                   |
| **Networking & Streaming**   | `httpx` (async) / `requests` + `io.BytesIO`    |
| **In-Memory PDF Parsing**    | PyMuPDF (`fitz`), `python-docx`                |
| **Regex Engine**             | Python standard library `re`                   |
| **Structured LLM Extraction**| OpenAI API (`gpt-4o-mini`) + Pydantic          |
| **Memory Management**        | Python `gc` module                             |

---

## 🚀 Getting Started

### Installation

```bash
# Clone and navigate to the sub-agent module
cd agents/resume_scraper_agent

# Install dependencies
pip install -r requirements.txt
```

### Usage Example

```python
import asyncio
from resume_agent import InMemoryResumeProcessor

async def main():
    processor = InMemoryResumeProcessor()
    
    # Define target missing fields for candidate
    missing_fields = ["email", "phone", "skills"]
    pdf_url = "https://example.com/resumes/candidate_cv.pdf"

    # Stream, extract, and auto-cleanup in RAM
    result = await processor.process_pdf_from_url(
        pdf_url=pdf_url, 
        missing_fields=missing_fields
    )

    print("Extracted Candidate Contact/Skills Delta:")
    print(result.model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(main())
```

---

## ⚙️ Configuration

Set stream limits and parsing models in `config.yaml`:

```yaml
in_memory_resume_scraper:
  max_stream_size_mb: 10          # Abort fetch if PDF exceeds this size in RAM
  max_pages_to_parse: 3           # Limit parsing to first N pages
  regex_prefilter_enabled: true   # Use fast regex pass before calling LLM
  llm_model: "gpt-4o-mini"
  temperature: 0.0
```

---

## 📊 Input / Output Schema

### Target Request Input

```json
{
  "candidate_id": "cand_12345",
  "resume_stream_url": "https://storage.googleapis.com/resumes/john_doe.pdf",
  "missing_fields": ["email", "phone"]
}
```

### Standardized Extracted Delta Output

```json
{
  "candidate_id": "cand_12345",
  "extracted_data": {
    "email": "john.doe@email.com",
    "phone": "+1-555-019-2834",
    "skills": ["Python", "FastAPI", "PostgreSQL"]
  },
  "extraction_method": {
    "email": "regex_pass",
    "phone": "regex_pass",
    "skills": "llm_pass"
  },
  "status": "success"
}
```

---

## ⚠️ Technical Challenges & Mitigations

| Challenge                          | Mitigation                                                                                                  |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **Memory Spikes on Large Files**   | Inspect `Content-Length` headers before streaming and hard-cap `BytesIO` buffer allocations at 10 MB.        |
| **Memory Leaks in Async Pipelines**| Wrap PDF parsing inside explicit `try...finally` blocks, closing `fitz.Document` and invoking `gc.collect()`. |
| **Obscured Email/Phone Formats**   | Fall back to spatial layout parsing (`get_text("blocks")`) or the LLM extractor if regex finds no match.     |
