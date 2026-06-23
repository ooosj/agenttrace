import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from urllib.parse import urlparse

def fetch_json(url, token):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
        sys.exit(1)

def fetch_readme(owner, repo, token):
    url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    try:
        data = fetch_json(url, token)
        if "content" in data:
            return base64.b64decode(data["content"]).decode('utf-8', errors='replace')
    except Exception:
        return ""
    return ""

def main():
    parser = argparse.ArgumentParser(description="Create a repository snapshot for AgentTrace testing.")
    parser.add_argument("--url", required=True, help="GitHub repository URL (e.g., https://github.com/owner/repo)")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--token", help="GitHub token (defaults to GITHUB_TOKEN env var)")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Warning: GITHUB_TOKEN not provided. API rate limits will apply.", file=sys.stderr)
    
    parsed = urlparse(args.url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        print("Invalid GitHub URL")
        sys.exit(1)
    
    owner, repo = parts[0], parts[1].removesuffix(".git")
    
    print(f"Fetching repository metadata for {owner}/{repo}...")
    repo_info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}", token)
    
    default_branch = repo_info.get("default_branch", "main")
    
    print(f"Fetching commit SHA for branch '{default_branch}'...")
    commit_info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/commits/{default_branch}", token)
    commit_sha = commit_info.get("sha")
    
    print("Fetching README...")
    readme = fetch_readme(owner, repo, token)
    
    print("Fetching file tree...")
    tree_info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1", token)
    
    file_tree = []
    for item in tree_info.get("tree", []):
        if item.get("type") == "blob":
            file_tree.append({
                "path": item.get("path"),
                "size": item.get("size", 0),
                "type": "file"
            })
            
    snapshot = {
        "repository_id": str(repo_info.get("id", f"{owner}/{repo}")),
        "full_name": repo_info.get("full_name", f"{owner}/{repo}"),
        "github_url": repo_info.get("html_url", args.url),
        "commit_sha": commit_sha,
        "metadata": {
            "stars": repo_info.get("stargazers_count", 0),
            "language": repo_info.get("language"),
            "topics": repo_info.get("topics", []),
            "description": repo_info.get("description"),
            "default_branch": default_branch
        },
        "readme": readme,
        "file_tree": file_tree,
        "external_ingest": {"enabled": False, "provider": "gitingest"}
    }
    
    out_path = args.out
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        
    print(f"\nSnapshot saved to {out_path} ({len(file_tree)} files)")

if __name__ == "__main__":
    main()
