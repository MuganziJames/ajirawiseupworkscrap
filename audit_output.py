"""Quick audit script to verify scraper output matches backend schema."""
import json

with open("output/test_run.json", "r", encoding="utf-8") as f:
    jobs = json.load(f)

print(f"Total jobs: {len(jobs)}\n")

# Check a salary job
for j in jobs:
    if j["salary_disclosed"]:
        print("=== SALARY JOB ===")
        print(f"  salary_min:       {j['salary_min']} (type={type(j['salary_min']).__name__})")
        print(f"  salary_max:       {j['salary_max']} (type={type(j['salary_max']).__name__})")
        print(f"  salary_currency:  {j['salary_currency']}")
        print(f"  salary_disclosed: {j['salary_disclosed']}")
        break
print()

# Remote job
for j in jobs:
    if j["location_type"] == "remote":
        print("=== REMOTE JOB ===")
        print(f"  location_type:      {j['location_type']}")
        print(f"  specific_location:  {j['specific_location']}")
        break
print()

# Full field audit on first job
j = jobs[0]
print("=== ALL FIELDS (job 1) ===")
for k, v in j.items():
    t = type(v).__name__
    preview = str(v)[:80] if v is not None else "None"
    print(f"  {k:25s} | {t:8s} | {preview}")
print()

# Aggregate values
loc_types = set(j["location_type"] for j in jobs if j["location_type"])
platforms = set(j["source_platform"] for j in jobs)
currencies = set(j["salary_currency"] for j in jobs if j["salary_currency"])
print(f"location_types: {loc_types}")
print(f"platforms:      {platforms}")
print(f"currencies:     {currencies}")

# Check bullet format
for j in jobs:
    if j["responsibilities"]:
        lines = j["responsibilities"].split("\n")[:3]
        print(f"\nresponsibilities (first 3 lines):")
        for l in lines:
            print(f"  {l}")
        break

# Check job_metadata structure
j0 = jobs[0]
md = j0["job_metadata"]
print(f"\njob_metadata keys: {list(md.keys())}")
if "scraped_data" in md:
    print(f"scraped_data keys: {list(md['scraped_data'].keys())}")

# Check view_count / application_count types
print(f"\nview_count type:        {type(jobs[0]['view_count']).__name__} = {jobs[0]['view_count']}")
print(f"application_count type: {type(jobs[0]['application_count']).__name__} = {jobs[0]['application_count']}")
print(f"extracted_skills:       {jobs[0]['extracted_skills']}")
print(f"ai_summary:             {jobs[0]['ai_summary']}")
print(f"expires_at:             {jobs[0]['expires_at']}")
