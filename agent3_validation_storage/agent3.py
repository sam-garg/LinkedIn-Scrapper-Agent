import os
import sys
import json
import re
from typing import List, Dict, Any, Optional
import pandas as pd

# Add parent directory to sys.path to import schemas and storage
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from dotenv import load_dotenv

# Automatically load environment variables from parent directory .env
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=env_path)

from schemas import CandidateProfile

class ValidationStorageAgent:
    """
    Agent 3: Validation & Storage Agent
    Flowchart Workflow:
    1. Validate Data & Check for Null Values
    2. Decision: Any Null Values?
       - Yes: Re-check & Fill (AI / Heuristic Missing Field Filler) -> Re-check Loop
       - No: Proceed to Storage
    3. Store in Supabase
    4. Export CSV
    """
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.supabase = self._init_supabase()

    def _init_supabase(self):
        if self.supabase_url and self.supabase_key and "your-project" not in self.supabase_url:
            try:
                from supabase import create_client, Client
                return create_client(self.supabase_url, self.supabase_key)
            except Exception as e:
                print(f"[Agent 3] Supabase initialization notice: {e}")
        return None

    def process_and_store(self, candidate_data_list: List[Any], csv_filename: str = "candidates.csv", max_fill_retries: int = 2) -> List[CandidateProfile]:
        print("\n" + "="*60)
        print("  [Agent 3] Validation & Storage Agent Initialized  ")
        print("="*60)

        validated_profiles: List[CandidateProfile] = []

        for idx, candidate in enumerate(candidate_data_list):
            # Convert candidate dict or Pydantic model to CandidateProfile
            if isinstance(candidate, dict):
                profile = CandidateProfile(**candidate)
            else:
                profile = candidate

            print(f"\n[Agent 3] Validating Candidate #{idx+1}: {profile.name}")
            
            # Step 1 & Decision Loop: Check and Fill Null Values
            profile = self._validation_and_fill_loop(profile, max_retries=max_fill_retries)
            validated_profiles.append(profile)

        # Step 2: Store in Supabase
        print("\n[Agent 3] Storing validated candidate records in Supabase...")
        for prof in validated_profiles:
            self._store_in_supabase(prof)

        # Step 3: Export CSV
        print(f"\n[Agent 3] Exporting final data to CSV file '{csv_filename}'...")
        self._export_to_csv(validated_profiles, filename=csv_filename)

        print("\n" + "="*60)
        print("  [Agent 3] Validation & Storage Agent Completed  ")
        print("="*60)

        return validated_profiles

    def _get_null_fields(self, profile: CandidateProfile) -> List[str]:
        p_dict = profile.model_dump() if hasattr(profile, 'model_dump') else profile.dict()
        return [field for field, val in p_dict.items() if val is None]

    def _validation_and_fill_loop(self, profile: CandidateProfile, max_retries: int = 2) -> CandidateProfile:
        retry_count = 0
        current_profile = profile

        while retry_count < max_retries:
            null_fields = self._get_null_fields(current_profile)
            if not null_fields:
                print(f"  --> [Agent 3] No null values present for '{current_profile.name}'.")
                break

            print(f"  --> [Agent 3] Null values present ({null_fields}). Triggering 'Re-check & Fill' Sub-Agent (Attempt {retry_count+1})...")
            filled_profile = self._recheck_and_fill(current_profile, null_fields)
            
            if filled_profile == current_profile:
                # No new fields were filled
                print("  --> [Agent 3] Re-check completed. Remaining fields finalized.")
                current_profile = filled_profile
                break
            
            current_profile = filled_profile
            retry_count += 1

        return current_profile

    def _recheck_and_fill(self, profile: CandidateProfile, null_fields: List[str]) -> CandidateProfile:
        """
        Flowchart Sub-Node: Re-check & Fill
        Uses AI (Gemini 2.5 Flash Lite) or heuristics to fill missing fields.
        """
        p_dict = profile.model_dump() if hasattr(profile, 'model_dump') else profile.dict()

        if not self.gemini_key or "your_" in self.gemini_key:
            # Heuristic fill fallback
            print("  --> [Re-check & Fill] Applying fallback heuristics for missing fields.")
            if "visa_status" in null_fields:
                p_dict["visa_status"] = "F1 Visa / Overseas Student"
            if "technology" in null_fields and p_dict.get("university"):
                p_dict["technology"] = "Engineering / General Tech"
            return CandidateProfile(**p_dict)

        prompt = f"""
You are Agent 3's "Re-check & Fill" AI assistant.
Candidate Profile so far:
{json.dumps(p_dict, indent=2)}

Missing fields to infer/fill: {null_fields}

Task: Infer or supply reasonable standard values for missing fields based on context (e.g. if university is outside India, visa_status might be "F1 Visa" or "Student Visa").

Return a valid JSON object matching the complete Candidate Profile schema with missing fields filled where possible:
{{
  "name": "{profile.name}",
  "contact": string or null,
  "email": string or null,
  "technology": string or null,
  "visa_status": string or null,
  "graduation_year": integer or null,
  "university": string or null,
  "linkedin_url": string or null
}}
Return ONLY valid JSON.
"""
        try:
            raw_response = None
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_key)
                response = client.models.generate_content(
                    model=self.gemini_model,
                    contents=prompt,
                )
                raw_response = response.text
            except Exception:
                import google.generativeai as genai
                genai.configure(api_key=self.gemini_key)
                model = genai.GenerativeModel(self.gemini_model)
                response = model.generate_content(prompt)
                raw_response = response.text

            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if json_match:
                filled_data = json.loads(json_match.group(0))
                filled_data['name'] = profile.name
                print(f"  --> [Re-check & Fill] Successfully filled missing fields via Gemini AI.")
                return CandidateProfile(**filled_data)
        except Exception as e:
            print(f"  --> [Re-check & Fill] AI Error: {e}. Applying heuristic fill.")
            if "visa_status" in null_fields:
                p_dict["visa_status"] = "F1 Visa / Overseas Student"

        return CandidateProfile(**p_dict)

    def _store_in_supabase(self, profile: CandidateProfile):
        if not self.supabase:
            print(f"  --> [Supabase] Info: Supabase not configured. Skipping DB insert for '{profile.name}'.")
            return None
        table_name = os.getenv("SUPABASE_TABLE_NAME", "students")
        try:
            data = profile.model_dump() if hasattr(profile, 'model_dump') else profile.dict()
            res = self.supabase.table(table_name).insert(data).execute()
            print(f"  --> [Supabase] Saved record for '{profile.name}' into table '{table_name}'.")
            return res
        except Exception as e:
            print(f"  --> [Supabase] DB Insert Notice for '{profile.name}': {e}")
            return None

    def _export_to_csv(self, profiles: List[CandidateProfile], filename: str = "candidates.csv"):
        data = [p.model_dump() if hasattr(p, 'model_dump') else p.dict() for p in profiles]
        df = pd.DataFrame(data)
        df.to_csv(filename, index=False)
        print(f"  --> [CSV Export] Successfully exported {len(profiles)} records to '{filename}'.")
