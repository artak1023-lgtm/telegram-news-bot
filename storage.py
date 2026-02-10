from collections import defaultdict

user_settings = {}
sent_cache = defaultdict(set)

def get_user(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            "sources": {},
            "keywords": [],
            "active": True
        }
    return user_settings[user_id]
