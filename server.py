import os
import requests
import json
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pywebpush import webpush
from pathlib import Path
import engine

app = FastAPI()
base_dir = Path(__file__).resolve().parent

MANAGER_PINS = {
    "Andy": "1234", "Phil": "1235", "James": "1236", "Jimmy": "1237",
    "Greg": "1238", "Nick": "1239", "Foy": "1240", "Hugh": "1241",
    "Bungle": "1242", "Garth": "1243", "Josh": "1244", "Stew": "1245",
    "Sam": "1246", "Ali": "1247", "Crouch": "1248", "Dave": "1249",
    "Duncan": "1250", "Barney": "1251", "Rob": "1252", "Rackett": "1253",
    "Wilson": "1254", "Culley": "1255", "Bobby": "1256", "Tudor": "1257",
    "Adi": "1258", "Lee": "1259", "Jamie": "1260", "Tom": "1261",
    "Ben": "1262", "Will": "1263", "Niall": "1264", "Pete": "1265"
}

MANAGER_LEAGUES = {
    "Andy": 63, "James": 63, "Jimmy": 63, "Greg": 63, "Nick": 63, "Foy": 63, "Hugh": 63,
    "Phil": 63, 
    "Sam": 320, "Garth": 320, "Bungle": 320, "Dave": 320, "Crouch": 320, "Ali": 320,
    "Stew": 320, "Josh": 320, 
    "Duncan": 378, "Rackett": 378, "Barney": 378, "Rob": 378, "Wilson": 378, "Culley": 378,
    "Bobby": 378, "Tudor": 378, 
    "Adi": 240, "Lee": 240, "Jamie": 240, "Tom": 240, "Ben": 240, "Will": 240, "Niall": 240,
    "Pete": 240 
}

VAPID_PRIVATE_KEY = "SPXvvzkxVdsxWXj-8RfQXdBCxrcQdrgO3NNZXGvNP7Q"
VAPID_CLAIMS = {"sub": "mailto:commissar@cdp.com"}

@app.get("/api/login")
def verify_login(alias: str, pin: str):
    if MANAGER_PINS.get(alias) == str(pin):
        default_league = MANAGER_LEAGUES.get(alias, 63)
        return {"status": "success", "default_league": default_league}
    return {"status": "error", "message": "Incorrect PIN. The Commissar is watching."}

@app.get("/")
def serve_index():
    return FileResponse(base_dir / "index.html")

@app.get("/sw.js")
def serve_sw():
    return FileResponse(base_dir / "sw.js", media_type="application/javascript")

@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(base_dir / "manifest.json", media_type="application/manifest+json")

@app.get("/icon.png")
def serve_icon():
    return FileResponse(base_dir / "icon.png", media_type="image/png")

@app.get("/api/league_data")
def get_league_data():
    teams = engine.get_all_32_teams_registry()
    return {"status": "success", "manager_count": len(teams) if teams else 0, "data": teams}

@app.get("/api/live_scores")
def get_live_scores(league_id: int = 63, gw: str = "0"):
    from concurrent.futures import ThreadPoolExecutor
    import math

    try:
        target_gw = int(gw)
    except:
        target_gw = 0

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
    all_gws = sorted(list({m["event"] for m in matches}))
    
    current_gw = target_gw if target_gw > 0 else (unplayed[0] if unplayed else 1)
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

    return {"gw": current_gw, "all_gws": all_gws, "matches": results}

@app.post("/api/save_subscription")
async def save_subscription(request: Request):
    sub_data = await request.json()
    upstash_url = os.getenv("UPSTASH_URL")
    upstash_token = os.getenv("UPSTASH_TOKEN")
    if upstash_url and upstash_token:
        headers = {"Authorization": f"Bearer {upstash_token}"}
        requests.post(f"{upstash_url}/set/latest_sub", data=json.dumps(sub_data), headers=headers)
    return {"status": "saved to cloud database"}

@app.post("/api/trigger_push")
def trigger_push():
    upstash_url = os.getenv("UPSTASH_URL")
    upstash_token = os.getenv("UPSTASH_TOKEN")
    if not (upstash_url and upstash_token): return {"error": "Database not configured"}
        
    headers = {"Authorization": f"Bearer {upstash_token}"}
    response = requests.get(f"{upstash_url}/get/latest_sub", headers=headers)
    data = response.json()
    if not data.get("result"): return {"error": "No device registered"}
        
    sub_data = json.loads(data["result"])
    payload = json.dumps({"title": "🚨 LIVE FROM THE CLOUD", "body": "Your permanent database is working!"})
    
    try:
        webpush(subscription_info=sub_data, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims=VAPID_CLAIMS)
        return {"status": "Push sent!"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/match_spotlight")
def get_match_spotlight(m1: str, m2: str, gw: str = "1"):
    try:
        target_gw = int(gw)
    except:
        target_gw = 1
        
    static_data = engine.fetch_fpl_static()
    all_fixtures = engine.fetch_all_epl_fixtures()
    teams_reg = engine.get_all_32_teams_registry()
    
    e1_id = teams_reg.get(m1.lower(), {}).get("entry_id")
    e2_id = teams_reg.get(m2.lower(), {}).get("entry_id")
    
    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}
    
    live_data = engine.fetch_live_event(target_gw)
    live_elements = live_data.get("elements", {}) if live_data else {}
    
    club_minutes = {}
    for elem_str_id, e_info in live_elements.items():
        try:
            club_id = element_lookup.get(int(elem_str_id), {}).get("team")
            if club_id: 
                club_minutes[club_id] = club_minutes.get(club_id, 0) + e_info.get("stats", {}).get("minutes", 0)
        except: pass

    p1 = engine.fetch_entry_event(e1_id, target_gw) if e1_id else None
    p2 = engine.fetch_entry_event(e2_id, target_gw) if e2_id else None
    
    t1_start, t1_bench, _, _, _, _, _, _ = engine.evaluate_lineup(p1, live_elements, element_lookup, club_minutes, pos_map, team_map, target_gw, all_fixtures)
    t2_start, t2_bench, _, _, _, _, _, _ = engine.evaluate_lineup(p2, live_elements, element_lookup, club_minutes, pos_map, team_map, target_gw, all_fixtures)
    
    def format_pitch(start_df, bench_df):
        rows = [[], [], [], []]
        subs = []
        
        active = engine.get_active_players_from_dfs(start_df, bench_df)
        for r in active:
            events = []
            if int(r.get("G", 0)) > 0: events.append("⚽" * int(r["G"]))
            if int(r.get("A", 0)) > 0: events.append("🎯" * int(r["A"]))
            if int(r.get("CS", 0)) > 0 and str(r.get("Pos", "")) in ["GKP", "DEF"]: events.append("🛡️")
            if int(r.get("Bonus", 0)) > 0: events.append(f"{int(r['Bonus'])}⭐")
            
            p_dict = {
                "name": str(r.get("Player", "Unknown")),
                "pos": str(r.get("Pos", "")),
                "club": str(r.get("Club", "")).upper()[:3],
                "fixture": str(r.get("Opp", "")),
                "pts": int(r.get("Pts", 0)),
                "events": " ".join(events)
            }
            if p_dict["pos"] == "GKP": rows[0].append(p_dict)
            elif p_dict["pos"] == "DEF": rows[1].append(p_dict)
            elif p_dict["pos"] == "MID": rows[2].append(p_dict)
            elif p_dict["pos"] == "FWD": rows[3].append(p_dict)

        inactive = []
        if start_df is not None and not start_df.empty:
            inactive.extend(start_df[start_df["sub_action"] == "Subbed Off"].to_dict("records"))
        if bench_df is not None and not bench_df.empty:
            inactive.extend(bench_df[bench_df["sub_action"] != "Subbed On"].to_dict("records"))
            
        for r in inactive:
            subs.append({
                "name": str(r.get("Player", "Unknown")),
                "pos": str(r.get("Pos", "")),
                "club": str(r.get("Club", "")).upper()[:3],
                "fixture": str(r.get("Opp", "")),
                "pts": int(r.get("Pts", 0)),
                "events": ""
            })
            
        return {"pitch": [r for r in rows if r], "subs": subs}

    def format_table(start_df, bench_df):
        def parse_row(r):
            return {
                "name": str(r.get("Player", "Unknown")),
                "pos": str(r.get("Pos", "")),
                "opp": str(r.get("Opp", "")),
                "mins": int(r.get("Mins", 0)),
                "g": int(r.get("G", 0)),
                "a": int(r.get("A", 0)),
                "cs": int(r.get("CS", 0)) if str(r.get("Pos", "")) in ["GKP", "DEF", "MID"] else "-",
                "bonus": int(r.get("Bonus", 0)),
                "pts": int(r.get("Pts", 0))
            }
        starters = [parse_row(r) for _, r in start_df.iterrows()] if start_df is not None and not start_df.empty else []
        subs = [parse_row(r) for _, r in bench_df.iterrows()] if bench_df is not None and not bench_df.empty else []
        return {"starters": starters, "subs": subs}

    gw_fixtures = [f for f in all_fixtures if f.get("event") == target_gw] if all_fixtures else []
    labels, m1_data, m1_pts, m1_events, m2_data, m2_pts, m2_events = [], [], [], [], [], [], []
    
    t1_active = engine.get_active_players_from_dfs(t1_start, t1_bench)
    t2_active = engine.get_active_players_from_dfs(t2_start, t2_bench)
    curr1, curr2 = 0
    
    for f in gw_fixtures:
        h_id, a_id = f.get("team_h"), f.get("team_a")
        labels.append(f"{team_map.get(h_id, 'H')} v {team_map.get(a_id, 'A')}")
        
        f_pts1 = sum(int(p["Pts"]) for p in t1_active if p.get("club_id") in (h_id, a_id))
        curr1 += f_pts1
        m1_data.append(curr1)
        m1_pts.append(f_pts1)
        ev1 = [str(p.get("Player")) for p in t1_active if p.get("club_id") in (h_id, a_id) and int(p.get("Pts", 0)) >= 4]
        m1_events.append(", ".join(ev1))
        
        f_pts2 = sum(int(p["Pts"]) for p in t2_active if p.get("club_id") in (h_id, a_id))
        curr2 += f_pts2
        m2_data.append(curr2)
        m2_pts.append(f_pts2)
        ev2 = [str(p.get("Player")) for p in t2_active if p.get("club_id") in (h_id, a_id) and int(p.get("Pts", 0)) >= 4]
        m2_events.append(", ".join(ev2))

    return {
        "progression": {
            "labels": labels,
            "m1_data": m1_data, "m1_match_pts": m1_pts, "m1_events": m1_events,
            "m2_data": m2_data, "m2_match_pts": m2_pts, "m2_events": m2_events
        },
        "pitch_m1": format_pitch(t1_start, t1_bench),
        "pitch_m2": format_pitch(t2_start, t2_bench),
        "table_m1": format_table(t1_start, t1_bench),
        "table_m2": format_table(t2_start, t2_bench)
    }