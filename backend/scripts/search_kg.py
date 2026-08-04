import requests

BASE_URL = "http://127.0.0.1:8000"

LOGIN_URL = f"{BASE_URL}/api/auth/login"
SEARCH_URL = f"{BASE_URL}/api/knowledge/search"

LOGIN_PAYLOAD = {"username": "admin", "password": "ChangeMe@2026"}

SEARCH_PAYLOAD = {"query": "保密协议", "partition": "inbox", "top_k": 3}


def get_access_token() -> str:
    resp = requests.post(LOGIN_URL, json=LOGIN_PAYLOAD)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("未获取到 access_token")
    return token


def search_knowledge(token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(SEARCH_URL, headers=headers, json=SEARCH_PAYLOAD)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    token = get_access_token()
    result = search_knowledge(token)
    print(result)
