import os
import requests
import json
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pywebpush import webpush
from pathlib import Path
import engine  # 👈 We are importing your new brain here

app = FastAPI()
base_dir = Path(__file__).resolve().parent

VAPID_PRIVATE_KEY = "SPXvvzkxVdsxWXj-8RfQXdBCxrcQdrgO3NNZXGvNP7Q"
VAPID_CLAIMS = {"sub": "mailto:commissar@cdp.com"}

from fastapi import Response

@app.get("/")
def serve_index(response: Response):
    # This prevents mobile browsers from clinging to old versions of your HTML
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return FileResponse(base_dir / "index.html", headers=headers)

@app.get("/sw.js")
def serve_sw():
    return FileResponse(base_dir / "sw.js", media_type = "application/javascript")

@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(base_dir / "manifest.json", media_type="application/manifest+json")

@app.get("/icon.png")
def serve_icon():
    return FileResponse(base_dir / "icon.png", media_type="image/png")

# 👈 NEW ENDPOINT: This routes web traffic into your Python engine
@app.get("/api/league_data")
def get_league_data():
    print("Fetching the 32-manager registry from the FPL servers...")
    teams = engine.get_all_32_teams_registry()
    return {
        "status": "success",
        "manager_count": len(teams) if teams else 0,
        "data": teams
    }

# 👈 NEW ENDPOINT: Live Scores Matchday Dashboard
@app.get("/api/live_scores")
def get_live_scores(league_id: int = 63):
    from concurrent.futures import ThreadPoolExecutor
    import math

    def calc_win_prob(live1, proj1, to_play1, live2, proj2, to_play2, is_finished):
        if is_finished: return (100, 0) if live1 > live2 else ((0, 100) if live2 > live1 else (50, 50))
        total_left = to_play1 + to_play2
        if total_left == 0:
            diff = abs(live1 - live2)
            return ((99, 1) if diff <= 5 else (100, 0)) if live1 > live2 else (((1, 99) if diff <= 5 else (0, 100)) if live2 > live1 else (50, 50))
        prob1 = 1.0 / (1.0 + math.exp(-(proj1 - proj2) / (max(6.0, total_left * 2.8) / 1.7)))
        pct1 = max(1, min(99, int(round(prob1 * 100))))
        return pct1, 100 - pct1

    static_data = engine.fetch_fpl_static()
    league_details, _ = engine.fetch_league_data(league_id)
    all_fixtures = engine.fetch_all_epl_fixtures()
    
    matches = league_details.get("matches", [])
    unplayed = sorted(list({m["event"] for m in matches if not m.get("finished", False)}))
    current_gw = unplayed[0] if unplayed else 1
    gw_matches = [m for m in matches if m["event"] == current_gw]
    
    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}
    
    live_data = engine.fetch_live_event(current_gw)
    live_elements = live_data.get("elements", {}) if live_data else {}
    
    club_minutes = {}
    for elem_str_id, e_info in live_elements.items():
        try:
            elem_obj = element_lookup.get(int(elem_str_id), {})
            if elem_obj.get("team"):
                club_minutes[elem_obj["team"]] = club_minutes.get(elem_obj["team"], 0) + e_info.get("stats", {}).get("minutes", 0)
        except: pass
        
    entries = league_details.get("league_entries", [])
    lentry_map = {e["id"]: e for e in entries}

    def process_match(m):
        e1 = lentry_map.get(m["league_entry_1"], {})
        e2 = lentry_map.get(m["league_entry_2"], {})
        a1 = engine.get_manager_alias(e1.get("player_first_name", ""), e1.get("player_last_name", ""))
        a2 = engine.get_manager_alias(e2.get("player_first_name", ""), e2.get("player_last_name", ""))
        is_fin = m.get("finished", False)
        
        p1 = engine.fetch_entry_event(e1.get("entry_id"), current_gw)
        p2 = engine.fetch_entry_event(e2.get("entry_id"), current_gw)
        
        _, _, t1_live, t1_proj, t1_inp, t1_ytp, t1_bp, _ = engine.evaluate_lineup(p1, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures)
        _, _, t2_live, t2_proj, t2_inp, t2_ytp, t2_bp, _ = engine.evaluate_lineup(p2, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures)
        
        t1_score = m.get("league_entry_1_points", t1_live) if is_fin else t1_live
        t2_score = m.get("league_entry_2_points", t2_live) if is_fin else t2_live
        prob1, prob2 = calc_win_prob(t1_score, t1_proj, t1_inp + t1_ytp, t2_score, t2_proj, t2_inp + t2_ytp, is_fin)
        
        def fmt_rem(i, y):
            if i>0 and y>0: return f"{i} in play, {y} yet to play"
            return f"{i} in play" if i>0 else (f"{y} yet to play" if y>0 else "0 to play")

        return {
            "m1": a1, "s1": t1_score, "p1": t1_proj, "r1": fmt_rem(t1_inp, t1_ytp), "pr1": prob1, "b1": t1_bp,
            "m2": a2, "s2": t2_score, "p2": t2_proj, "r2": fmt_rem(t2_inp, t2_ytp), "pr2": prob2, "b2": t2_bp,
            "is_fin": is_fin
        }

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_match, gw_matches))

    return {"gw": current_gw, "matches": results}

@app.post("/api/save_subscription")
async def save_subscription(request: Request):
    sub_data = await request.json()
    
    upstash_url = os.getenv("UPSTASH_URL")
    upstash_token = os.getenv("UPSTASH_TOKEN")
    
    if upstash_url and upstash_token:
        headers = {"Authorization": f"Bearer {upstash_token}"}
        # Save the phone's token to the cloud database permanently
        requests.post(f"{upstash_url}/set/latest_sub", data=json.dumps(sub_data), headers=headers)
        
    return {"status": "saved to cloud database"}

@app.post("/api/trigger_push")
def trigger_push():
    upstash_url = os.getenv("UPSTASH_URL")
    upstash_token = os.getenv("UPSTASH_TOKEN")
    
    if not (upstash_url and upstash_token):
        return {"error": "Database not configured"}
        
    # Retrieve the saved token from the database
    headers = {"Authorization": f"Bearer {upstash_token}"}
    response = requests.get(f"{upstash_url}/get/latest_sub", headers=headers)
    data = response.json()
    
    if not data.get("result"):
        return {"error": "No device registered"}
        
    sub_data = json.loads(data["result"])
    
    payload = json.dumps({
        "title": "🚨 LIVE FROM THE CLOUD",
        "body": "Your permanent database is working!"
    })
    
    try:
        webpush(
            subscription_info=sub_data,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        return {"status": "Push sent!"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/match_spotlight")
def get_match_spotlight(m1: str, m2: str):
    return {
        "progression": {
            "labels": ['IPS v NFO', 'AVL v MCI', 'ARS v EVE', 'COV v FUL', 'CHE v TOT', 'CRY v NEW', 'HUL v BRE', 'LIV v BHA', 'MUN v BOU', 'SUN v LEE'],
            "m1_data": [0, 0, 15, 15, 15, 23, 29, 42, 44, 56],
            "m2_data": [0, 0, 0, 15, 18, 19, 21, 31, 37, 43]
        },
        "pitch_m1": [
            [{"pos": "GKP", "name": "Leno", "fixture": "COV (A)", "pts": 8, "events": "⭐"}],
            [{"pos": "DEF", "name": "Robinson", "fixture": "COV (A)", "pts": 7, "events": ""}, {"pos": "DEF", "name": "Justin", "fixture": "SUN (A)", "pts": 6, "events": ""}, {"pos": "DEF", "name": "F.Kadioglu", "fixture": "LIV (A)", "pts": 1, "events": ""}],
            [{"pos": "MID", "name": "Barcola", "fixture": "BHA (H)", "pts": 6, "events": "🎯"}, {"pos": "MID", "name": "Kluivert", "fixture": "MUN (A)", "pts": 6, "events": ""}, {"pos": "MID", "name": "Rogers", "fixture": "TOT (H)", "pts": 1, "events": ""}, {"pos": "MID", "name": "Gross", "fixture": "LIV (A)", "pts": 0, "events": ""}],
            [{"pos": "FWD", "name": "Thiago", "fixture": "HUL (A)", "pts": 5, "events": ""}, {"pos": "FWD", "name": "Marmoush", "fixture": "CHE (A)", "pts": 2, "events": ""}, {"pos": "FWD", "name": "Wissa", "fixture": "CRY (A)", "pts": 1, "events": ""}]
        ],
        "pitch_m2": [
            [{"pos": "GKP", "name": "Trafford", "fixture": "SUN (A)", "pts": 10, "events": "⭐"}],
            [{"pos": "DEF", "name": "Konsa", "fixture": "EVE (H)", "pts": 14, "events": "⚽"}, {"pos": "DEF", "name": "Jacquet", "fixture": "BHA (H)", "pts": 8, "events": ""}, {"pos": "DEF", "name": "Calafiori", "fixture": "EVE (H)", "pts": 1, "events": ""}, {"pos": "DEF", "name": "Palestra", "fixture": "TOT (H)", "pts": 0, "events": ""}],
            [{"pos": "MID", "name": "Wirtz", "fixture": "BHA (H)", "pts": 6, "events": "🎯"}, {"pos": "MID", "name": "Belloumi", "fixture": "BRE (H)", "pts": 4, "events": ""}, {"pos": "MID", "name": "Cunha", "fixture": "BOU (H)", "pts": 1, "events": ""}, {"pos": "MID", "name": "Kroupi", "fixture": "MUN (A)", "pts": 1, "events": ""}],
            [{"pos": "FWD", "name": "Osula", "fixture": "CRY (A)", "pts": 9, "events": "⭐"}, {"pos": "FWD", "name": "Brobbey", "fixture": "LEE (H)", "pts": 2, "events": ""}]
        ]
    }
