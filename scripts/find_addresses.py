import requests

usernames = ["S-Works", "1j59y6nk", "Sharky6999", "LlamaEnjoyer"]
for u in usernames:
    try:
        # Some platforms use /profiles/username or the API might differ
        res = requests.get(f"https://gamma-api.polymarket.com/profiles?username={u}")
        if res.status_code == 200:
            print(f"{u}: {res.json()}")
        else:
             print(f"{u}: Status {res.status_code}")
    except Exception as e:
        print(f"Error {u}: {e}")
