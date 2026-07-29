import os
import sys
from dotenv import load_dotenv

# Load environment variables from parent directory
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=env_path)

from agent3 import ValidationStorageAgent

def main():
    print("--- Running Agent 3 Standalone Test ---")

    # Sample input candidate records with missing (null) fields
    input_candidates = [
        {
            "name": "Harsh Misra",
            "contact": None,
            "email": "harsh.misra@example.edu",
            "technology": "Management Information Systems",
            "visa_status": None,
            "graduation_year": 2019,
            "university": "University of Illinois at Chicago",
            "linkedin_url": "https://harshmisra-1.github.io/resume/"
        },
        {
            "name": "Divyansh Mittal",
            "contact": None,
            "email": "divyansh@example.com",
            "technology": "Computer Science & Data Structures",
            "visa_status": None,
            "graduation_year": 2024,
            "university": "Carnegie Mellon University",
            "linkedin_url": "https://www.linkedin.com/in/sample-divyansh-mittal"
        }
    ]

    agent3 = ValidationStorageAgent()
    agent3.process_and_store(input_candidates, csv_filename="candidates.csv")

if __name__ == "__main__":
    main()
