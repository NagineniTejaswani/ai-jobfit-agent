import re
import requests

def search_jobs(keywords: str):
    """
    Searches live remote job listings using the Jobicy API.
    Maps candidate role keywords to active Jobicy domain tags and retrieves rich job data.
    """
    print(f"Search query received: '{keywords}'")
    kw_lower = keywords.lower() if keywords else ""
    
    tag_map = {
        'financial': 'finance', 'finance': 'finance', 'accounting': 'accounting', 'investment': 'finance', 'banking': 'finance',
        'hr': 'people', 'human resource': 'people', 'talent': 'recruiter', 'recruiting': 'recruiter', 'recruiter': 'recruiter', 'people ops': 'people',
        'data': 'data', 'analyst': 'analytics', 'analytics': 'analytics', 'bi': 'analytics', 'business intelligence': 'analytics', 'machine learning': 'data', 'ai': 'data',
        'marketing': 'marketing', 'seo': 'seo', 'growth': 'marketing', 'content': 'content', 'copywriter': 'copywriting', 'social media': 'marketing',
        'python': 'python', 'backend': 'dev', 'frontend': 'dev', 'full stack': 'dev', 'developer': 'software', 'engineer': 'software', 'software': 'software', 'devops': 'dev', 'cloud': 'dev',
        'design': 'design', 'ui': 'design', 'ux': 'design', 'product designer': 'design', 'graphic': 'design',
        'sales': 'sales', 'business development': 'sales', 'account executive': 'sales', 'customer success': 'sales',
        'product manager': 'management', 'project manager': 'management', 'scrum': 'management', 'operations': 'management'
    }
    
    selected_tag = None
    for key, tag in tag_map.items():
        if key in kw_lower:
            selected_tag = tag
            break
            
    if not selected_tag:
        # If no explicit keyword matched in the map, use the first word or fallback
        clean_word = re.sub(r'[^a-zA-Z]', '', kw_lower.split()[0]) if kw_lower else 'software'
        selected_tag = clean_word if len(clean_word) >= 3 else 'software'

    print(f"Mapped query '{keywords}' -> Jobicy tag: '{selected_tag}'")
    
    url = "https://jobicy.com/api/v2/remote-jobs"
    params = {"count": 20, "tag": selected_tag}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        jobs = data.get("jobs", [])
    except Exception as e:
        print(f"Jobicy API request failed: {e}")
        jobs = []

    # If tag returned 0 results, fallback to general software/remote feed
    if not jobs:
        try:
            print("Tag query returned 0 jobs, falling back to general remote feed...")
            fallback_resp = requests.get(url, params={"count": 20}, timeout=10)
            jobs = fallback_resp.json().get("jobs", [])
        except Exception as e:
            print(f"Fallback request failed: {e}")
            jobs = []

    results = []
    for job in jobs:
        raw_desc = job.get("jobDescription") or job.get("description") or job.get("jobExcerpt") or ""
        clean_desc = re.sub(r'<[^>]*>', '', raw_desc)
        clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
        
        results.append({
            "id": job.get("id"),
            "title": job.get("jobTitle") or job.get("title") or "Untitled Role",
            "company": job.get("companyName") or job.get("company_name") or job.get("company") or "Unknown Company",
            "url": job.get("url"),
            "description": clean_desc[:250] + ("..." if len(clean_desc) > 250 else ""),
            "full_description": clean_desc[:1200] + ("..." if len(clean_desc) > 1200 else ""),
            "tags": job.get("jobTags") or job.get("tags") or []
        })
    
    print(f"Jobicy returned {len(results)} valid jobs for tag '{selected_tag}'")
    return results

def get_job_details(job_id: int):
    """
    Fetches details for a job (Jobicy descriptions are already provided in search_jobs).
    """
    return {"id": job_id}
