import requests

def search_jobs(keywords: str):
    """
    Searches live remote job listings using the free Remotive API.
    The LLM decides the keywords based on the user's request and their resume context.
    """
    print(f"Search sent to Remotive: '{keywords}'")
    
    url = "https://remotive.com/api/remote-jobs"
    params = {"search": keywords}
    
    response = requests.get(url, params=params)
    data = response.json()
    
    jobs = data.get("jobs", [])[:5]
    
    results = []
    for job in jobs:
        results.append({
            "id": job["id"],
            "title": job["title"],
            "company": job["company_name"],
            "url": job["url"]
        })
    
    return results
    
def get_job_details(job_id: int):
    """
    Fetches full details for one job from Remotive using its ID.
    """
    url = "https://remotive.com/api/remote-jobs"
    response = requests.get(url)
    data = response.json()
    
    jobs = data.get("jobs", [])
    for job in jobs:
        if job["id"] == job_id:
            return {
                "id": job["id"],
                "title": job["title"],
                "company": job["company_name"],
                "description": job["description"][:800],  # trimmed for now
                "tags": job.get("tags", [])
            }
    
    return {"error": f"No job found with id {job_id}"}

if __name__ == "__main__":
    results = search_jobs("python backend")
    for r in results:
        print(r)