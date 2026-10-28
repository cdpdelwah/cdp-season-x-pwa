import io
import os
import re
import time
import math
import json
import functools
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from pywebpush import webpush
from pathlib import Path
import engine

try:
    import pypdfium2 as pdfium
except Exception:
    pdfium = None

app = FastAPI()
base_dir = Path(__file__).resolve().parent

assets_folder = base_dir / "Assets"
if not assets_folder.exists():
    assets_folder = base_dir / "assets"

newsletters_folder = base_dir / "Newsletters"
if not newsletters_folder.exists():
    newsletters_folder = base_dir / "newsletters"

# ==========================================
# TTL MEMORY CACHE (MIRRORS STREAMLIT CACHE)
# ==========================================
_MEMORY_CACHE = {}

def ttl_cache(ttl_seconds=60):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__, args, tuple(sorted(kwargs.items())))
            now = time.time()
            if key in _MEMORY_CACHE:
                val, ts = _MEMORY_CACHE[key]
                if now - ts < ttl_seconds:
                    return val
            res = func(*args, **kwargs)
            _MEMORY_CACHE[key] = (res, now)
            return res
        return wrapper
    return decorator

# ==========================================
# CONSTANTS, REGISTRIES & PALETTES
# ==========================================
LEAGUE_PRESETS = {
    "CDP (Crème Dellar Prem)": 63,
    "SDM (Segundo Del Mundo)": 320,
    "BDR (Best De La Rest)": 378,
    "LDE (Liger Del Eager)": 240
}

LEAGUE_ID_TO_KEY = {v: k for k, v in LEAGUE_PRESETS.items()}

MANAGER_PINS = {
    "Admin": "1234",
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
    "Admin": 63,
    "Andy": 63, "James": 63, "Jimmy": 63, "Greg": 63, "Nick": 63, "Foy": 63, "Hugh": 63, "Phil": 63,
    "Sam": 320, "Garth": 320, "Bungle": 320, "Dave": 320, "Crouch": 320, "Ali": 320, "Stew": 320, "Josh": 320,
    "Duncan": 378, "Rackett": 378, "Barney": 378, "Rob": 378, "Wilson": 378, "Culley": 378, "Bobby": 378, "Tudor": 378,
    "Adi": 240, "Lee": 240, "Jamie": 240, "Tom": 240, "Ben": 240, "Will": 240, "Niall": 240, "Pete": 240
}

CLUB_PALETTE = {
    "ARS": {"bg": "#EF0107", "text": "#ffffff", "border": "#9C824A"},
    "AVL": {"bg": "#670E36", "text": "#95BFE5", "border": "#95BFE5"},
    "BHA": {"bg": "#0057B8", "text": "#ffffff", "border": "#FFCD00"},
    "BOU": {"bg": "#DA291C", "text": "#ffffff", "border": "#000000"},
    "BRE": {"bg": "#D20000", "text": "#ffffff", "border": "#000000"},
    "CHE": {"bg": "#034694", "text": "#ffffff", "border": "#EE242C"},
    "CRY": {"bg": "#1B458F", "text": "#ffffff", "border": "#C4122E"},
    "EVE": {"bg": "#003399", "text": "#ffffff", "border": "#ffffff"},
    "FUL": {"bg": "#ffffff", "text": "#000000", "border": "#CC0000"},
    "HUL": {"bg": "#F5971D", "text": "#000000", "border": "#000000"},
    "IPS": {"bg": "#003399", "text": "#ffffff", "border": "#D20000"},
    "LEE": {"bg": "#1D428A", "text": "#FFCD00", "border": "#FFCD00"},
    "LEI": {"bg": "#003090", "text": "#ffffff", "border": "#FDBE11"},
    "LIV": {"bg": "#C8102E", "text": "#ffffff", "border": "#00B2A9"},
    "MCI": {"bg": "#6CABDD", "text": "#001838", "border": "#ffffff"},
    "MUN": {"bg": "#DA291C", "text": "#ffffff", "border": "#FBE122"},
    "NEW": {"bg": "#241F20", "text": "#ffffff", "border": "#41B6E6"},
    "NFO": {"bg": "#DD0000", "text": "#ffffff", "border": "#ffffff"},
    "SOU": {"bg": "#D71920", "text": "#ffffff", "border": "#132257"},
    "SUN": {"bg": "#EB172B", "text": "#ffffff", "border": "#000000"},
    "TOT": {"bg": "#132257", "text": "#ffffff", "border": "#ffffff"},
    "WHU": {"bg": "#7A263A", "text": "#1BB1E7", "border": "#1BB1E7"},
    "WOL": {"bg": "#FDB913", "text": "#231F20", "border": "#231F20"}
}

POS_ORDER = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}

PULSE_HEADERS = {
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "account": "premierleague"
}

CLUB_SEARCH_KEYWORDS = {
    "ARS": "arsenal", "AVL": "aston villa", "BHA": "brighton", "BOU": "bournemouth",
    "BRE": "brentford", "CHE": "chelsea", "COV": "coventry", "CRY": "crystal palace",
    "EVE": "everton", "FUL": "fulham", "HUL": "hull", "IPS": "ipswich",
    "LEE": "leeds", "LEI": "leicester", "LIV": "liverpool", "MCI": "manchester city",
    "MUN": "manchester united", "NEW": "newcastle", "NFO": "nottingham",
    "SOU": "southampton", "SUN": "sunderland", "TOT": "tottenham",
    "WHU": "west ham", "WOL": "wolverhampton"
}

VAPID_PRIVATE_KEY = "SPXvvzkxVdsxWXj-8RfQXdBCxrcQdrgO3NNZXGvNP7Q"
VAPID_CLAIMS = {"sub": "mailto:commissar@cdp.com"}

# ==========================================
# CACHED API WRAPPERS
# ==========================================
@ttl_cache(300)
def cached_fpl_static():
    return engine.fetch_fpl_static()

@ttl_cache(90)
def cached_league_data(league_id: int):
    return engine.fetch_league_data(league_id)

@ttl_cache(60)
def cached_all_fixtures():
    return engine.fetch_all_epl_fixtures()

@ttl_cache(45)
def cached_live_event(gw: int):
    return engine.fetch_live_event(gw)

@ttl_cache(45)
def cached_entry_event(entry_id: int, gw: int):
    return engine.fetch_entry_event(entry_id, gw)

@ttl_cache(60)
def cached_epl_fixtures(gw: int):
    try:
        r = requests.get(f"https://fantasy.premierleague.com/api/fixtures/?event={gw}", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    all_f = cached_all_fixtures() or []
    return [f for f in all_f if f.get("event") == gw]

# ==========================================
# CORE HELPERS & LINEUP ENGINE
# ==========================================
def safe_int(val):
    try:
        if val is None or val == "":
            return 0
        return int(float(val))
    except Exception:
        return 0

def get_availability_multiplier(raw_elem):
    status = str(raw_elem.get("status", "a")).lower()
    chance = raw_elem.get("chance_of_playing_next_round")
    if status in ["i", "s", "u"]:
        return 0.0
    if chance is not None and not pd.isna(chance):
        try:
            val = float(chance)
            if val >= 75: return 0.9
            if val >= 50: return 0.6
            if val >= 25: return 0.3
            return 0.0
        except Exception:
            pass
    return 0.6 if status == "d" else 1.0

def get_health_label(raw_elem):
    status = str(raw_elem.get("status", "a")).lower()
    chance = raw_elem.get("chance_of_playing_next_round")
    if status == "i": return "Injured (0%)"
    if status == "s": return "Suspended (0%)"
    if status == "u": return "Unavailable (0%)"
    if status == "d":
        if chance is not None and not pd.isna(chance):
            return f"Doubtful ({safe_int(chance)}%)"
        return "Doubtful (50%)"
    return "Fit (100%)"

def get_fdr_multiplier(team_id, current_gw, all_fixtures_list):
    if not all_fixtures_list or not team_id:
        return 1.0
    gw_fixes = [f for f in all_fixtures_list if f.get("event") == current_gw]
    if not gw_fixes:
        return 1.0
    team_fixes = [f for f in gw_fixes if f.get("team_h") == team_id or f.get("team_a") == team_id]
    if not team_fixes:
        return 0.0
    total = 0.0
    for fix in team_fixes:
        diff = fix.get("team_h_difficulty", 3) if fix.get("team_h") == team_id else fix.get("team_a_difficulty", 3)
        total += 1.10 if diff <= 2 else (1.00 if diff == 3 else (0.92 if diff == 4 else 0.85))
    return total

def extract_defcon_flag(elem_stats, elem_explain, pos_type):
    if not isinstance(elem_stats, dict):
        return False
    cbi = safe_int(elem_stats.get("clearances_blocks_interceptions", 0) or elem_stats.get("cbi", 0))
    tackles = safe_int(elem_stats.get("tackles", 0))
    recoveries = safe_int(elem_stats.get("recoveries", 0) or elem_stats.get("ball_recoveries", 0))
    dc_direct = safe_int(elem_stats.get("defensive_contributions", 0) or elem_stats.get("defcon", 0) or elem_stats.get("cbit", 0))

    calc_val = dc_direct if dc_direct > 0 else (cbi + tackles + recoveries if pos_type in [3, 4] else cbi + tackles)
    is_hit = False
    explain_val = 0
    stat_items = []

    if isinstance(elem_explain, list):
        for item in elem_explain:
            if isinstance(item, dict):
                if "stats" in item and isinstance(item["stats"], list):
                    stat_items.extend(item["stats"])
                else:
                    stat_items.append(item)
            elif isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict):
                        stat_items.append(sub)

    for s_item in stat_items:
        if isinstance(s_item, dict):
            ident = str(s_item.get("identifier", "")).lower()
            pts = safe_int(s_item.get("points", 0))
            val = safe_int(s_item.get("value", 0))
            if ident in ["defensive_contributions", "defcon", "cbit", "cbi"] and (pts >= 2 or val >= 10):
                is_hit = True
                explain_val = max(explain_val, val)

    final_val = max(calc_val, explain_val)
    threshold = 10 if pos_type == 2 else 12
    return (pos_type in [2, 3, 4] and final_val >= threshold) or is_hit

def full_evaluate_lineup(picks_list, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw=1, all_fixtures_list=None):
    if not picks_list or not picks_list.get("picks"):
        return [], [], 0, 0.0, 0, 0, 0, 0

    raw_players = []
    for p in picks_list.get("picks", []):
        elem_id = p["element"]
        raw_elem = element_lookup.get(elem_id, {})
        e_data = live_elements.get(str(elem_id)) or live_elements.get(elem_id) or {}
        stats = e_data.get("stats", {}) if isinstance(e_data, dict) else {}
        explain_raw = e_data.get("explain", []) if isinstance(e_data, dict) else []

        pos_type = raw_elem.get("element_type", 1)
        pos_str = pos_map.get(pos_type, "MID")
        club_id = raw_elem.get("team")

        opp_str = "-"
        if all_fixtures_list and club_id:
            team_fixes = [
                f for f in all_fixtures_list
                if f.get("event") == current_gw and (f.get("team_h") == club_id or f.get("team_a") == club_id)
            ]
            if team_fixes:
                opp_labels = []
                for tf in team_fixes:
                    if tf.get("team_h") == club_id:
                        opp_labels.append(f"{team_map.get(tf.get('team_a'), 'OPP')} (H)")
                    else:
                        opp_labels.append(f"{team_map.get(tf.get('team_h'), 'OPP')} (A)")
                opp_str = ", ".join(opp_labels)
            else:
                opp_str = "Blank"

        mins = safe_int(stats.get("minutes", 0))
        pts = safe_int(stats.get("total_points", 0))
        team_mins = club_minutes.get(club_id, 0)

        avail = get_availability_multiplier(raw_elem)
        form_val = float(raw_elem.get("form") or 0.0)
        ppg_val = float(raw_elem.get("points_per_game") or 2.0)
        base_exp = ((ppg_val * 0.6) + (form_val * 0.4)) * avail

        season_mins = float(raw_elem.get("minutes") or 0.0)
        if current_gw > 3 and (season_mins / max(1.0, float(current_gw * 60))) < 0.6:
            base_exp *= 0.8
        if base_exp <= 0 and avail > 0:
            base_exp = 2.0
        base_exp *= get_fdr_multiplier(club_id, current_gw, all_fixtures_list)

        if team_mins >= 800:
            state = "FT" if mins > 0 else "DNP"
            proj = float(pts) if mins > 0 else 0.0
        elif team_mins > 0:
            state = "LIVE"
            match_minute = 45
            if all_fixtures_list:
                for fix in all_fixtures_list:
                    if fix.get("event") == current_gw and (fix.get("team_h") == club_id or fix.get("team_a") == club_id) and fix.get("started", False):
                        match_minute = fix.get("minutes", 45)
                        break
            rem_frac = max(0.0, (90.0 - float(match_minute)) / 90.0)
            if mins > 0:
                proj = round(float(pts) + (1.0 if match_minute < 60 else 0.0) + (max(0.0, base_exp - 2.0) * rem_frac), 1)
            else:
                proj = round(base_exp * 0.25 * rem_frac, 1)
        else:
            state = "YTP"
            proj = round(base_exp, 1)

        raw_players.append({
            "id": elem_id,
            "Player": str(raw_elem.get("web_name", "Unknown")),
            "pos_num": pos_type,
            "Pos": pos_str,
            "Club": str(team_map.get(club_id, "PL")).upper(),
            "Opp": opp_str,
            "club_id": club_id,
            "status": str(raw_elem.get("status", "a")).lower(),
            "chance_of_playing_next_round": raw_elem.get("chance_of_playing_next_round"),
            "State": state,
            "Mins": mins,
            "Pts": pts,
            "Proj": proj,
            "G": safe_int(stats.get("goals_scored", 0)),
            "A": safe_int(stats.get("assists", 0)),
            "CS": safe_int(stats.get("clean_sheets", 0)),
            "GC": safe_int(stats.get("goals_conceded", 0)),
            "Bonus": safe_int(stats.get("bonus", 0)),
            "YC": safe_int(stats.get("yellow_cards", 0)),
            "RC": safe_int(stats.get("red_cards", 0)),
            "Saves": safe_int(stats.get("saves", 0)),
            "Penalties_Saved": safe_int(stats.get("penalties_saved", 0)),
            "Penalties_Missed": safe_int(stats.get("penalties_missed", 0)),
            "DEFCON_Achieved": extract_defcon_flag(stats, explain_raw, pos_type),
            "pick_pos": safe_int(p.get("position", 99)),
            "is_starter": safe_int(p.get("position", 99)) <= 11,
            "sub_action": ""
        })

    starters = [r for r in raw_players if r["is_starter"]]
    bench = sorted([r for r in raw_players if not r["is_starter"]], key=lambda x: x["pick_pos"])

    used_bench_ids = set()
    gk_starter = next((s for s in starters if s["Pos"] == "GKP"), None)
    if gk_starter and gk_starter["State"] == "DNP":
        gk_bench = next((b for b in bench if b["Pos"] == "GKP" and b["State"] != "DNP"), None)
        if gk_bench:
            gk_starter["sub_action"] = "Subbed Off"
            gk_bench["sub_action"] = "Subbed On"
            used_bench_ids.add(gk_bench["id"])

    for dnp_s in [s for s in starters if s["Pos"] != "GKP" and s["State"] == "DNP"]:
        for b_cand in bench:
            if b_cand["Pos"] == "GKP" or b_cand["id"] in used_bench_ids or b_cand["State"] == "DNP":
                continue
            cur_form = [s["Pos"] for s in starters if s["sub_action"] != "Subbed Off" and s["id"] != dnp_s["id"]] + [b_cand["Pos"]]
            if cur_form.count("DEF") >= 3 and cur_form.count("MID") >= 2 and cur_form.count("FWD") >= 1:
                dnp_s["sub_action"] = "Subbed Off"
                b_cand["sub_action"] = "Subbed On"
                used_bench_ids.add(b_cand["id"])
                break

    active_lineup = [s for s in starters if s["sub_action"] != "Subbed Off"] + [b for b in bench if b["sub_action"] == "Subbed On"]
    live_score = sum(p["Pts"] for p in active_lineup)
    proj_score = round(sum(p["Proj"] for p in active_lineup), 1)
    in_play = sum(1 for p in active_lineup if p["State"] == "LIVE")
    yet_to_play = sum(1 for p in active_lineup if p["State"] == "YTP")
    bench_left_pts = sum(b["Pts"] for b in bench if b["sub_action"] != "Subbed On")

    gk_pts = sorted([p["Pts"] for p in raw_players if p["Pos"] == "GKP"], reverse=True)
    def_pts = sorted([p["Pts"] for p in raw_players if p["Pos"] == "DEF"], reverse=True)
    mid_pts = sorted([p["Pts"] for p in raw_players if p["Pos"] == "MID"], reverse=True)
    fwd_pts = sorted([p["Pts"] for p in raw_players if p["Pos"] == "FWD"], reverse=True)

    best_gk = gk_pts[0] if gk_pts else 0
    opt_score = live_score
    for d in range(3, len(def_pts) + 1):
        for m in range(2, len(mid_pts) + 1):
            f = 10 - d - m
            if 1 <= f <= len(fwd_pts):
                cand = best_gk + sum(def_pts[:d]) + sum(mid_pts[:m]) + sum(fwd_pts[:f])
                if cand > opt_score:
                    opt_score = cand

    starters_sorted = sorted(starters, key=lambda x: (x["pos_num"], -x["Pts"]))
    return starters_sorted, bench, live_score, proj_score, in_play, yet_to_play, bench_left_pts, opt_score

def build_badges(r):
    badges = []
    g = safe_int(r.get("G", 0))
    a = safe_int(r.get("A", 0))
    cs = safe_int(r.get("CS", 0))
    bonus = safe_int(r.get("Bonus", 0))
    p_saved = safe_int(r.get("Penalties_Saved", 0))
    p_missed = safe_int(r.get("Penalties_Missed", 0))
    pos = str(r.get("Pos", ""))

    if g > 0: badges.append(f"{g}⚽" if g > 1 else "⚽")
    if a > 0: badges.append(f"{a}🎯" if a > 1 else "🎯")
    if cs > 0 and pos in ["GKP", "DEF", "MID"]: badges.append("🛡️")
    if bool(r.get("DEFCON_Achieved", False)): badges.append("🔰")
    if bonus > 0: badges.append(f"{bonus}⭐")
    if p_saved > 0: badges.append(f"{p_saved}🧤" if p_saved > 1 else "🧤")
    if p_missed > 0: badges.append(f"{p_missed}❌" if p_missed > 1 else "❌")
    return " ".join(badges)

def split_squad_records(s_recs, b_recs):
    active, inactive = [], []
    for r in s_recs:
        (inactive if str(r.get("sub_action", "")).strip() == "Subbed Off" else active).append(r)
    for r in b_recs:
        (active if str(r.get("sub_action", "")).strip() == "Subbed On" else inactive).append(r)
    inactive = sorted(inactive, key=lambda x: POS_ORDER.get(str(x.get("Pos", "")), 99))
    return active, inactive

def make_pitch_payload(active, inactive, show_proj_pill=False):
    rows = [[], [], [], []]
    subs = []

    def format_player_token(r, is_bench=False):
        club = str(r.get("Club", "PL")).strip().upper()
        pal = CLUB_PALETTE.get(club, {"bg": "#1e293b", "text": "#ffffff", "border": "#ffffff"})
        raw_status = str(r.get("status", "a")).lower()
        chance_val = r.get("chance_of_playing_next_round")
        flag = ""
        if raw_status == "s":
            flag = "s"
        elif raw_status in ["i", "u"]:
            flag = "red"
        elif raw_status == "d":
            c_num = safe_int(chance_val) if chance_val is not None and not pd.isna(chance_val) else 50
            flag = "orange" if c_num <= 25 else "yellow"

        pts_val = safe_int(r.get("Pts", 0))
        proj_val = float(r.get("Proj", 0.0))
        state_str = str(r.get("State", "FT")).upper()
        pill_text = f"{proj_val:.1f} pts" if show_proj_pill else ("⏳ YTP" if state_str == "YTP" else f"{pts_val} pts")

        return {
            "name": str(r.get("Player", "Unknown")),
            "pos": str(r.get("Pos", "")),
            "club": club,
            "bg": pal["bg"],
            "text": pal["text"],
            "border": pal["border"],
            "fixture": str(r.get("Opp", "")),
            "pts": pts_val,
            "proj": f"{proj_val:.1f}",
            "pill_text": pill_text,
            "mins": safe_int(r.get("Mins", 0)),
            "g": safe_int(r.get("G", 0)),
            "a": safe_int(r.get("A", 0)),
            "cs": safe_int(r.get("CS", 0)),
            "gc": safe_int(r.get("GC", 0)),
            "bonus": safe_int(r.get("Bonus", 0)),
            "saves": safe_int(r.get("Saves", 0)),
            "yc": safe_int(r.get("YC", 0)),
            "rc": safe_int(r.get("RC", 0)),
            "p_saved": safe_int(r.get("Penalties_Saved", 0)),
            "p_missed": safe_int(r.get("Penalties_Missed", 0)),
            "defcon_hit": bool(r.get("DEFCON_Achieved", False)),
            "state": state_str,
            "sub_action": str(r.get("sub_action", "")).strip(),
            "is_bench": is_bench,
            "flag": flag,
            "events": build_badges(r)
        }

    for r in active:
        p_dict = format_player_token(r, is_bench=False)
        if p_dict["pos"] == "GKP": rows[0].append(p_dict)
        elif p_dict["pos"] == "DEF": rows[1].append(p_dict)
        elif p_dict["pos"] == "MID": rows[2].append(p_dict)
        elif p_dict["pos"] == "FWD": rows[3].append(p_dict)

    for r in inactive:
        subs.append(format_player_token(r, is_bench=True))

    return {"pitch": [r for r in rows if r], "subs": subs}

def make_table_payload(s_recs, b_recs):
    def parse_row(r):
        pos = str(r.get("Pos", ""))
        return {
            "name": str(r.get("Player", "Unknown")),
            "pos": pos,
            "opp": str(r.get("Opp", "-")).replace(" (H)", " [H]").replace(" (A)", " [A]"),
            "mins": safe_int(r.get("Mins", 0)),
            "g": safe_int(r.get("G", 0)),
            "a": safe_int(r.get("A", 0)),
            "cs": safe_int(r.get("CS", 0)) if pos in ["GKP", "DEF", "MID"] else "•",
            "bonus": safe_int(r.get("Bonus", 0)),
            "pts": safe_int(r.get("Pts", 0))
        }

    b_sorted = sorted(b_recs, key=lambda x: POS_ORDER.get(str(x.get("Pos", "")), 99))
    return {
        "starters": [parse_row(r) for r in s_recs],
        "subs": [parse_row(r) for r in b_sorted]
    }

def make_progression_payload(a1, a2, t1_act, t2_act, gw_fixtures, team_map):
    def get_fixture_contributors(active_players, h_id, a_id):
        entries_list = []
        for p in active_players:
            if safe_int(p.get("club_id")) in (safe_int(h_id), safe_int(a_id)):
                p_name = str(p.get("Player", "Unknown"))
                cats = []
                g = safe_int(p.get("G", 0))
                a = safe_int(p.get("A", 0))
                cs = safe_int(p.get("CS", 0))
                bonus = safe_int(p.get("Bonus", 0))
                pos = str(p.get("Pos", ""))

                if g > 0: cats.append(f"{g}⚽" if g > 1 else "⚽")
                if a > 0: cats.append(f"{a}🎯" if a > 1 else "🎯")
                if cs > 0 and pos in ["GKP", "DEF"]: cats.append("🛡️")
                if bool(p.get("DEFCON_Achieved", False)): cats.append("🔰")
                if bonus > 0: cats.append(f"{bonus}⭐")

                if cats:
                    entries_list.append(f"{p_name} ({' '.join(cats)})")
        return ", ".join(entries_list) if entries_list else "None"

    fixtures_list = []
    c1, c2 = 0, 0

    for f in gw_fixtures:
        h_id = f.get("team_h")
        a_id = f.get("team_a")
        m_label = f"{team_map.get(h_id, 'H')} v {team_map.get(a_id, 'A')}"

        fp1 = sum(safe_int(p.get("Pts", 0)) for p in t1_act if safe_int(p.get("club_id")) in (safe_int(h_id), safe_int(a_id)))
        fp2 = sum(safe_int(p.get("Pts", 0)) for p in t2_act if safe_int(p.get("club_id")) in (safe_int(h_id), safe_int(a_id)))
        c1 += fp1
        c2 += fp2

        ev1 = get_fixture_contributors(t1_act, h_id, a_id)
        ev2 = get_fixture_contributors(t2_act, h_id, a_id)

        fixtures_list.append({
            "match": m_label,
            "m1": {"manager": str(a1), "pts": c1, "added": f"+{fp1}", "events": ev1, "color": "#f59e0b"},
            "m2": {"manager": str(a2), "pts": c2, "added": f"+{fp2}", "events": ev2, "color": "#38bdf8"}
        })

    return {"fixtures": fixtures_list}

def detect_current_gw(league_details):
    matches = league_details.get("matches", []) if league_details else []
    all_gws = sorted(list({m["event"] for m in matches})) if matches else list(range(1, 39))
    unplayed = sorted(list({m["event"] for m in matches if not m.get("finished", False)}))
    detected_gw = unplayed[0] if unplayed else (all_gws[-1] if all_gws else 1)
    return detected_gw, all_gws

# ==========================================
# STATIC & AUTH ROUTES
# ==========================================
@app.get("/api/login")
def verify_login(alias: str, pin: str):
    if MANAGER_PINS.get(alias) == str(pin):
        default_league = MANAGER_LEAGUES.get(alias, 63)
        return {"status": "success", "default_league": default_league}
    return {"status": "error", "message": "Incorrect PIN. The Commissar is watching."}

@app.get("/")
def serve_index():
    return FileResponse(
        base_dir / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )

@app.get("/sw.js")
def serve_sw():
    return FileResponse(
        base_dir / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )

@app.get("/manifest.json")
def serve_manifest():
    return FileResponse(base_dir / "manifest.json", media_type="application/manifest+json")

@app.get("/icon.png")
def serve_icon():
    return FileResponse(base_dir / "icon.png", media_type="image/png")

@app.get("/api/logo")
def serve_logo():
    candidates = [
        assets_folder / "SeasonX_Logo_Master.jpg",
        base_dir / "Assets" / "SeasonX_Logo_Master.jpg",
        base_dir / "assets" / "SeasonX_Logo_Master.jpg",
        base_dir / "SeasonX_Logo_Master.jpg",
        base_dir / "icon.png"
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return FileResponse(p)
    return Response(status_code=404)

@app.get("/api/league_data")
def get_league_data():
    teams = engine.get_all_32_teams_registry()
    return {"status": "success", "manager_count": len(teams) if teams else 0, "data": teams}

# ==========================================
# 1. HOME SUMMARY (TIMERS & CBWCBW TRACKER)
# ==========================================
@ttl_cache(60)
def compute_cbwcbw_tracker(gw_num: int):
    static_data = cached_fpl_static()
    all_fixtures = cached_all_fixtures()
    live_data = cached_live_event(gw_num)
    if not static_data:
        return 32, []

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data.get("element_types", [])}
    team_map = {item["id"]: item["short_name"] for item in static_data.get("teams", [])}
    element_lookup = {item["id"]: item for item in static_data.get("elements", [])}
    live_elements = live_data.get("elements", {}) if live_data else {}

    club_minutes = {}
    for elem_str_id, e_info in live_elements.items():
        try:
            c_id = element_lookup.get(int(elem_str_id), {}).get("team")
            if c_id:
                club_minutes[c_id] = club_minutes.get(c_id, 0) + safe_int(e_info.get("stats", {}).get("minutes", 0))
        except Exception:
            pass

    unique_teams = []
    for l_key, l_id in LEAGUE_PRESETS.items():
        ld, _ = cached_league_data(l_id)
        if ld:
            for e in ld.get("league_entries", []):
                alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
                if e.get("entry_id"):
                    unique_teams.append({
                        "alias": alias,
                        "entry_id": e.get("entry_id"),
                        "div": l_key.split(" ")[0]
                    })

    def eval_mgr(info):
        picks = cached_entry_event(info["entry_id"], gw_num)
        s_recs, b_recs, _, _, in_play, ytp, _, _ = full_evaluate_lineup(
            picks, live_elements, element_lookup, club_minutes, pos_map, team_map, gw_num, all_fixtures
        )
        active_xi, _ = split_squad_records(s_recs, b_recs)

        def check_player_pos_return(p):
            g = safe_int(p.get("G", 0))
            a = safe_int(p.get("A", 0))
            bonus = safe_int(p.get("Bonus", 0))
            saves = safe_int(p.get("Saves", 0))
            p_saved = safe_int(p.get("Penalties_Saved", 0))
            defcon = bool(p.get("DEFCON_Achieved", False))
            cs = safe_int(p.get("CS", 0))
            pos = str(p.get("Pos", "")).upper()
            return (
                g > 0 or a > 0 or bonus > 0 or p_saved > 0 or defcon
                or (cs > 0 and pos in ["GKP", "DEF", "MID"])
                or (saves >= 3 and pos == "GKP")
            )

        has_return = any(check_player_pos_return(p) for p in active_xi)
        if not has_return:
            rem_players = in_play + ytp
            is_locked = (rem_players == 0 and len(active_xi) > 0 and any(safe_int(p.get("Mins", 0)) > 0 for p in active_xi))
            return {
                "alias": info["alias"],
                "div": info["div"],
                "rem": rem_players,
                "is_locked": is_locked
            }
        return None

    with ThreadPoolExecutor(max_workers=10) as ex:
        res_list = list(ex.map(eval_mgr, unique_teams))

    at_risk = [r for r in res_list if r is not None]
    at_risk = sorted(at_risk, key=lambda x: (not x["is_locked"], x["rem"], x["alias"].lower()))
    return len(at_risk), at_risk

@app.get("/api/home_summary")
def get_home_summary(league_id: int = 63):
    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(league_id)
    all_fixtures = cached_all_fixtures()

    current_gw, _ = detect_current_gw(league_details)

    events_list = static_data.get("events", []) if static_data else []
    if isinstance(events_list, dict):
        events_list = events_list.get("data", [])

    target_ev = next((ev for ev in events_list if ev.get("id") == current_gw), None)
    lineup_iso = target_ev.get("deadline_time") if target_ev else None

    if not lineup_iso and all_fixtures:
        gw_fixtures = [f for f in all_fixtures if f.get("event") == current_gw and f.get("kickoff_time")]
        if gw_fixtures:
            gw_fixtures = sorted(gw_fixtures, key=lambda x: x.get("kickoff_time"))
            earliest_ko = gw_fixtures[0].get("kickoff_time")
            try:
                lineup_dt = pd.to_datetime(earliest_ko) - pd.Timedelta(minutes=90)
                lineup_iso = lineup_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

    if lineup_iso:
        try:
            lineup_dt = pd.to_datetime(lineup_iso)
            waiver_dt = lineup_dt - pd.Timedelta(hours=24)
            waiver_iso = waiver_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            waiver_iso = lineup_iso
    else:
        lineup_iso = ""
        waiver_iso = ""

    cbw_count, cbw_at_risk = compute_cbwcbw_tracker(current_gw)
    return {
        "current_gw": current_gw,
        "waiver_iso": waiver_iso,
        "lineup_iso": lineup_iso,
        "cbw_count": cbw_count,
        "cbw_at_risk": cbw_at_risk
    }

# ==========================================
# 2. SCORES (MATCHDAY & MANAGER SCHEDULE)
# ==========================================
@app.get("/api/live_scores")
def get_live_scores(league_id: int = 63, gw: str = "0", manager: str = "All"):
    try:
        target_gw = int(gw)
    except Exception:
        target_gw = 0

    def calc_win_prob(live1, proj1, to_play1, live2, proj2, to_play2, is_finished):
        if is_finished:
            return (100, 0) if live1 > live2 else ((0, 100) if live2 > live1 else (50, 50))
        total_left = to_play1 + to_play2
        if total_left == 0:
            diff = abs(live1 - live2)
            return ((99, 1) if diff <= 5 else (100, 0)) if live1 > live2 else (((1, 99) if diff <= 5 else (0, 100)) if live2 > live1 else (50, 50))
        prob1 = 1.0 / (1.0 + math.exp(-(proj1 - proj2) / (max(6.0, total_left * 2.8) / 1.7)))
        pct1 = max(1, min(99, int(round(prob1 * 100))))
        return pct1, 100 - pct1

    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(league_id)
    all_fixtures = cached_all_fixtures()

    detected_gw, all_gws = detect_current_gw(league_details)
    current_gw = target_gw if target_gw > 0 else detected_gw
    matches = league_details.get("matches", []) if league_details else []

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}

    entries = league_details.get("league_entries", []) if league_details else []
    lentry_map = {e["id"]: e for e in entries}
    league_managers = sorted([
        engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        for e in entries
    ])

    mgr_clean = str(manager).strip()
    is_mgr_mode = bool(mgr_clean and mgr_clean.lower() != "all")

    if is_mgr_mode:
        target_lentry_id = None
        for e in entries:
            alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
            if alias.lower() == mgr_clean.lower():
                target_lentry_id = e.get("id")
                break
        if target_lentry_id:
            target_matches = [
                m for m in matches
                if (m.get("league_entry_1") == target_lentry_id or m.get("league_entry_2") == target_lentry_id)
                and (m.get("event", 99) <= detected_gw or m.get("finished", False))
            ]
            target_matches = sorted(target_matches, key=lambda x: x.get("event", 0), reverse=True)
        else:
            target_matches = []
    else:
        target_matches = [m for m in matches if m["event"] == current_gw]

    needed_gws = sorted(list({m["event"] for m in target_matches}))
    gw_live_cache, gw_club_mins_cache, gw_fixtures_cache = {}, {}, {}

    def load_gw_context(g_num):
        l_data = cached_live_event(g_num)
        l_elems = l_data.get("elements", {}) if l_data else {}
        c_mins = {}
        for elem_str_id, e_info in l_elems.items():
            try:
                elem_obj = element_lookup.get(int(elem_str_id), {})
                if elem_obj.get("team"):
                    c_mins[elem_obj["team"]] = c_mins.get(elem_obj["team"], 0) + safe_int(e_info.get("stats", {}).get("minutes", 0))
            except Exception:
                pass
        g_fixes = [f for f in all_fixtures if f.get("event") == g_num] if all_fixtures else []
        return g_num, l_elems, c_mins, g_fixes

    with ThreadPoolExecutor(max_workers=10) as executor:
        for g_num, l_elems, c_mins, g_fixes in executor.map(load_gw_context, needed_gws):
            gw_live_cache[g_num] = l_elems
            gw_club_mins_cache[g_num] = c_mins
            gw_fixtures_cache[g_num] = g_fixes

    def process_match(m):
        m_gw = m["event"]
        live_elements = gw_live_cache.get(m_gw, {})
        club_minutes = gw_club_mins_cache.get(m_gw, {})
        gw_fixtures = gw_fixtures_cache.get(m_gw, [])

        e1 = lentry_map.get(m["league_entry_1"], {})
        e2 = lentry_map.get(m["league_entry_2"], {})
        a1 = engine.get_manager_alias(e1.get("player_first_name", ""), e1.get("player_last_name", ""))
        a2 = engine.get_manager_alias(e2.get("player_first_name", ""), e2.get("player_last_name", ""))
        is_fin = m.get("finished", False)

        p1 = cached_entry_event(e1.get("entry_id"), m_gw)
        p2 = cached_entry_event(e2.get("entry_id"), m_gw)

        s1_recs, b1_recs, t1_live, t1_proj, t1_inp, t1_ytp, t1_bp, t1_opt = full_evaluate_lineup(
            p1, live_elements, element_lookup, club_minutes, pos_map, team_map, m_gw, all_fixtures
        )
        s2_recs, b2_recs, t2_live, t2_proj, t2_inp, t2_ytp, t2_bp, t2_opt = full_evaluate_lineup(
            p2, live_elements, element_lookup, club_minutes, pos_map, team_map, m_gw, all_fixtures
        )

        t1_score = m.get("league_entry_1_points", t1_live) if is_fin else t1_live
        t2_score = m.get("league_entry_2_points", t2_live) if is_fin else t2_live
        prob1, prob2 = calc_win_prob(t1_score, t1_proj, t1_inp + t1_ytp, t2_score, t2_proj, t2_inp + t2_ytp, is_fin)

        def fmt_rem(i, y):
            if i > 0 and y > 0:
                return f"{i} in play, {y} yet to play"
            return f"{i} in play" if i > 0 else (f"{y} yet to play" if y > 0 else "0 to play")

        t1_act, t1_inact = split_squad_records(s1_recs, b1_recs)
        t2_act, t2_inact = split_squad_records(s2_recs, b2_recs)

        return {
            "gw": m_gw,
            "m1": a1, "s1": safe_int(t1_score), "p1": float(t1_proj), "r1": fmt_rem(t1_inp, t1_ytp), "pr1": prob1, "b1": safe_int(t1_bp), "opt1": safe_int(t1_opt),
            "m2": a2, "s2": safe_int(t2_score), "p2": float(t2_proj), "r2": fmt_rem(t2_inp, t2_ytp), "pr2": prob2, "b2": safe_int(t2_bp), "opt2": safe_int(t2_opt),
            "is_fin": is_fin,
            "spotlight": {
                "m1_meta": {"score": safe_int(t1_score), "bench": safe_int(t1_bp), "opt": safe_int(t1_opt)},
                "m2_meta": {"score": safe_int(t2_score), "bench": safe_int(t2_bp), "opt": safe_int(t2_opt)},
                "progression": make_progression_payload(a1, a2, t1_act, t2_act, gw_fixtures, team_map),
                "pitch_m1": make_pitch_payload(t1_act, t1_inact),
                "pitch_m2": make_pitch_payload(t2_act, t2_inact),
                "table_m1": make_table_payload(s1_recs, b1_recs),
                "table_m2": make_table_payload(s2_recs, b2_recs)
            }
        }

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(process_match, target_matches))

    return {
        "gw": current_gw,
        "detected_gw": detected_gw,
        "all_gws": all_gws,
        "managers": league_managers,
        "selected_manager": mgr_clean if is_mgr_mode else "All",
        "matches": results
    }

# ==========================================
# 3. EPL SCORES & LINEUPS (PULSE + ESPN + FPL)
# ==========================================
def _team_matches_code(short_code, team_obj):
    if not short_code or not isinstance(team_obj, dict):
        return False
    code_up = str(short_code).strip().upper()
    kw = CLUB_SEARCH_KEYWORDS.get(code_up, code_up.lower())
    club_obj = team_obj.get("club", {}) if isinstance(team_obj.get("club"), dict) else {}
    abbr = str(club_obj.get("abbr") or team_obj.get("abbreviation") or "").strip().upper()
    if abbr and abbr == code_up:
        return True
    combined_names = " ".join([
        str(team_obj.get("name") or ""),
        str(team_obj.get("shortName") or ""),
        str(team_obj.get("displayName") or ""),
        str(team_obj.get("shortDisplayName") or ""),
        str(club_obj.get("name") or ""),
        str(club_obj.get("shortName") or "")
    ]).lower()
    return kw in combined_names

@ttl_cache(86400)
def get_pulse_active_season_id():
    try:
        s_url = "https://footballapi.pulselive.com/football/competitions/1/compseasons?page=0&pageSize=100"
        s_resp = requests.get(s_url, headers=PULSE_HEADERS, timeout=4)
        if s_resp.status_code == 200:
            seasons = s_resp.json().get("content", [])
            for s in seasons:
                if "2026/27" in str(s.get("label", "")):
                    return int(float(s.get("id")))
            if seasons:
                return int(max(seasons, key=lambda x: float(x.get("id", 0)))["id"])
    except Exception:
        pass
    return None

@ttl_cache(60)
def get_pulse_active_fixtures_list(event_num=None):
    season_id = get_pulse_active_season_id()
    season_param = f"&compSeasons={season_id}" if season_id else ""
    gw_page = max(0, (int(event_num) - 1) // 4) if event_num else 1
    search_urls = [
        f"https://footballapi.pulselive.com/football/fixtures?comps=1{season_param}&statuses=U,L&sort=asc&page=0&pageSize=40",
        f"https://footballapi.pulselive.com/football/fixtures?comps=1{season_param}&sort=asc&page={gw_page}&pageSize=40",
        f"https://footballapi.pulselive.com/football/fixtures?comps=1{season_param}&statuses=C&sort=desc&page=0&pageSize=40"
    ]
    all_fixes, seen_ids = [], set()
    for url in search_urls:
        try:
            r = requests.get(url, headers=PULSE_HEADERS, timeout=4)
            if r.status_code == 200:
                for fix in r.json().get("content", []):
                    f_id = fix.get("id")
                    if f_id and f_id not in seen_ids:
                        seen_ids.add(f_id)
                        all_fixes.append(fix)
        except Exception:
            continue
    return all_fixes

def get_pulse_fixture_id(home_short, away_short, event_num=None):
    for fix in get_pulse_active_fixtures_list(event_num):
        teams = fix.get("teams", [])
        if len(teams) == 2:
            if _team_matches_code(home_short, teams[0].get("team", {})) and _team_matches_code(away_short, teams[1].get("team", {})):
                return int(float(fix.get("id")))
    return None

@ttl_cache(60)
def fetch_pulse_fixture_details(pulse_id):
    try:
        resp = requests.get(f"https://footballapi.pulselive.com/football/fixtures/{pulse_id}", headers=PULSE_HEADERS, timeout=4)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

@ttl_cache(60)
def get_espn_scoreboard():
    try:
        sb_resp = requests.get("https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard", timeout=4)
        if sb_resp.status_code == 200:
            return sb_resp.json().get("events", [])
    except Exception:
        pass
    return []

@ttl_cache(60)
def fetch_espn_fixture_summary(event_id):
    try:
        sum_resp = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/summary?event={event_id}", timeout=4)
        if sum_resp.status_code == 200:
            return sum_resp.json()
    except Exception:
        pass
    return None

def _fetch_espn_lineup_backup(home_short, away_short):
    pos_order_map = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
    events = get_espn_scoreboard()
    target_event_id = None
    for ev in events:
        comps = ev.get("competitions", [])
        if comps:
            competitors = comps[0].get("competitors", [])
            home_comp = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away_comp = next((c for c in competitors if c.get("homeAway") == "away"), {})
            if _team_matches_code(home_short, home_comp.get("team", {})) and _team_matches_code(away_short, away_comp.get("team", {})):
                target_event_id = ev.get("id")
                break
    if not target_event_id:
        return None
    sum_data = fetch_espn_fixture_summary(target_event_id)
    if not sum_data or len(sum_data.get("rosters", [])) < 2:
        return None

    def parse_espn_roster(r_obj):
        starters, subs_used, subs_unused = [], [], []
        for entry in r_obj.get("roster", []):
            ath = entry.get("athlete", {})
            name = ath.get("displayName") or ath.get("shortName") or "Unknown"
            raw_num = entry.get("jersey") or ath.get("jersey")
            num_str = f"#{raw_num} " if raw_num and str(raw_num).strip() not in ["-", "None", ""] else ""
            pos_raw = str(entry.get("position", {}).get("abbreviation", "M")).upper()
            clean_pos = "GKP" if "G" in pos_raw else ("DEF" if "D" in pos_raw else ("FWD" if "F" in pos_raw else "MID"))
            capt = " (C)" if entry.get("captain", False) else ""
            if entry.get("starter", False):
                sub_tag = " <span style='color:#f43f5e; font-weight:700;'>▼</span>" if entry.get("subbedOut", False) else ""
                starters.append((pos_order_map.get(clean_pos, 3), f"{num_str}<b>{name}</b>{capt} • <i>{clean_pos}</i>{sub_tag}"))
            else:
                if entry.get("subbedIn", False):
                    subs_used.append(f"{num_str}<b>{name}</b> • <i>{clean_pos}</i> <span style='color:#22c55e; font-weight:800;'>▲</span>")
                else:
                    subs_unused.append(f"{num_str}{name} ({clean_pos})")
        return [s[1] for s in sorted(starters, key=lambda x: x[0])], subs_used, subs_unused

    rosters = sum_data.get("rosters", [])
    home_r = next((r for r in rosters if r.get("homeAway") == "home"), rosters[0])
    away_r = next((r for r in rosters if r.get("homeAway") == "away"), rosters[1])
    h_s, h_u, h_un = parse_espn_roster(home_r)
    a_s, a_u, a_un = parse_espn_roster(away_r)
    if len(h_s) >= 11 or len(a_s) >= 11:
        return {
            "has_lineups": True,
            "h_starters": h_s, "h_subs_used": h_u, "h_subs_unused": h_un,
            "a_starters": a_s, "a_subs_used": a_u, "a_subs_unused": a_un
        }
    return None

def build_epl_pitch_payload_from_lists(starters_list, subs_used_list, subs_unused_list, club_short, team_id, live_elements, element_lookup):
    club_fpl_players = []
    if live_elements and element_lookup and team_id:
        for elem_str_id, e_info in live_elements.items():
            try:
                eid = int(elem_str_id)
                raw_elem = element_lookup.get(eid, {})
                if raw_elem.get("team") == team_id:
                    club_fpl_players.append((raw_elem, e_info))
            except Exception:
                pass

    def parse_entry(entry_str, is_sub=False, sub_action=""):
        clean = re.sub(r"<[^>]*>", "", str(entry_str)).strip()
        pos = "MID"
        left_part = clean
        if "•" in clean:
            parts = clean.split("•")
            left_part = parts[0].strip()
            raw_pos = parts[1].replace("*", "").strip() if len(parts) > 1 else "MID"
            pos = "GKP" if "GK" in raw_pos else ("DEF" if "DEF" in raw_pos else ("FWD" if "FWD" in raw_pos else "MID"))
        else:
            for cand in ["GKP", "DEF", "MID", "FWD", "GK"]:
                if f"({cand})" in clean or f"*{cand}*" in clean:
                    pos = "GKP" if "GK" in cand else cand
                    left_part = clean.replace(f"({cand})", "").replace(f"*{cand}*", "").strip()
                    break

        name = left_part
        if name.startswith("#"):
            parts_num = name.split(" ", 1)
            name = parts_num[1] if len(parts_num) > 1 else parts_num[0]
        name = name.replace("**", "").replace("(C)", "").strip()

        rec = {
            "Player": name, "Pos": pos, "Club": club_short, "Opp": "",
            "Pts": 0, "Proj": 0.0, "Mins": 90 if not is_sub else 0, "State": "FT",
            "G": 0, "A": 0, "CS": 0, "GC": 0, "Bonus": 0, "Saves": 0,
            "Penalties_Saved": 0, "Penalties_Missed": 0, "YC": 0, "RC": 0,
            "DEFCON_Achieved": False, "sub_action": sub_action, "status": "a", "chance_of_playing_next_round": 100
        }

        name_low = name.lower()
        for raw_elem, e_info in club_fpl_players:
            wn = str(raw_elem.get("web_name", "")).lower()
            ln = str(raw_elem.get("second_name", "")).lower()
            if wn and (wn == name_low or wn in name_low or name_low in wn or (ln and ln in name_low)):
                st_dict = e_info.get("stats", {}) if isinstance(e_info, dict) else {}
                exp_raw = e_info.get("explain", []) if isinstance(e_info, dict) else []
                p_type = raw_elem.get("element_type", 3)
                rec.update({
                    "Pts": safe_int(st_dict.get("total_points", 0)),
                    "Mins": safe_int(st_dict.get("minutes", 0)),
                    "G": safe_int(st_dict.get("goals_scored", 0)),
                    "A": safe_int(st_dict.get("assists", 0)),
                    "CS": safe_int(st_dict.get("clean_sheets", 0)),
                    "GC": safe_int(st_dict.get("goals_conceded", 0)),
                    "Bonus": safe_int(st_dict.get("bonus", 0)),
                    "Saves": safe_int(st_dict.get("saves", 0)),
                    "YC": safe_int(st_dict.get("yellow_cards", 0)),
                    "RC": safe_int(st_dict.get("red_cards", 0)),
                    "Penalties_Saved": safe_int(st_dict.get("penalties_saved", 0)),
                    "Penalties_Missed": safe_int(st_dict.get("penalties_missed", 0)),
                    "DEFCON_Achieved": extract_defcon_flag(st_dict, exp_raw, p_type)
                })
                break
        return rec

    s_recs = [parse_entry(s, is_sub=False, sub_action=("Subbed Off" if "▼" in str(s) else "")) for s in starters_list]
    b_recs = [parse_entry(su, is_sub=True, sub_action="Subbed On") for su in subs_used_list] + [parse_entry(sun, is_sub=True, sub_action="") for sun in subs_unused_list]
    act, inact = split_squad_records(s_recs, b_recs)
    return make_pitch_payload(act, inact)

def fetch_epl_match_lineup(f_obj, home_short, away_short, live_elements, element_lookup, event_num):
    pos_order_map = {"GK": 1, "GKP": 1, "G": 1, "DEF": 2, "D": 2, "MID": 3, "M": 3, "FWD": 4, "F": 4}
    is_started = f_obj.get("started", False)
    is_finished = f_obj.get("finished", False) or f_obj.get("finished_provisional", False)
    kickoff_time = f_obj.get("kickoff_time")
    home_team_id = f_obj.get("team_h")
    away_team_id = f_obj.get("team_a")
    match_minute = f_obj.get("minutes", 90 if is_finished else 45)

    is_within_window = is_started or is_finished
    if not is_within_window and kickoff_time:
        try:
            ko_dt = pd.to_datetime(kickoff_time)
            now_dt = pd.Timestamp.now(tz=ko_dt.tz) if ko_dt.tz else pd.Timestamp.utcnow()
            if (ko_dt - now_dt).total_seconds() <= 5400:
                is_within_window = True
        except Exception:
            is_within_window = True

    if not is_within_window:
        return {"has_lineups": False}

    raw_lineup = None

    # 1. PulseLive
    pulse_id = get_pulse_fixture_id(home_short, away_short, event_num)
    if pulse_id:
        data = fetch_pulse_fixture_details(pulse_id)
        if data and len(data.get("teamLists", [])) >= 2:
            h_sheet, a_sheet = data["teamLists"][0], data["teamLists"][1]
            if len(h_sheet.get("lineup", [])) >= 11 or len(a_sheet.get("lineup", [])) >= 11:
                sub_events = {}
                for ev in data.get("events", []):
                    if ev.get("type") in ["substitution", "sub"]:
                        min_str = ev.get("time", {}).get("label", "")
                        off_id = ev.get("subOff", {}).get("id") or ev.get("personId")
                        on_id = ev.get("subOn", {}).get("id")
                        if off_id: sub_events[off_id] = ("OFF", min_str)
                        if on_id: sub_events[on_id] = ("ON", min_str)

                def format_official_sheet(sheet):
                    starters, subs_used, subs_unused = [], [], []
                    for p in sheet.get("lineup", []):
                        p_id = p.get("id")
                        raw_num = p.get("matchShirtNumber") or p.get("shirtNum")
                        num_str = f"#{raw_num} " if raw_num and str(raw_num).strip() not in ["-", "None", ""] else ""
                        name = p.get("name", {}).get("display", "Unknown")
                        capt = " (C)" if p.get("captain", False) else ""
                        raw_pos = str(p.get("matchPosition", "MID")).upper()
                        clean_pos = "GKP" if "G" in raw_pos else ("DEF" if "D" in raw_pos else ("FWD" if "F" in raw_pos else "MID"))
                        sub_tag = f" <span style='color:#f43f5e; font-weight:700;'>▼ {sub_events[p_id][1]}</span>" if (p_id in sub_events and sub_events[p_id][0] == "OFF") else ""
                        starters.append((pos_order_map.get(clean_pos, 3), f"{num_str}<b>{name}</b>{capt} • <i>{clean_pos}</i>{sub_tag}"))
                    for p in sheet.get("substitutes", []):
                        p_id = p.get("id")
                        raw_num = p.get("matchShirtNumber") or p.get("shirtNum")
                        num_str = f"#{raw_num} " if raw_num and str(raw_num).strip() not in ["-", "None", ""] else ""
                        name = p.get("name", {}).get("display", "Unknown")
                        if p_id in sub_events and sub_events[p_id][0] == "ON":
                            subs_used.append(f"{num_str}<b>{name}</b> <span style='color:#22c55e; font-weight:800;'>▲ {sub_events[p_id][1]}</span>")
                        else:
                            subs_unused.append(f"{num_str}{name}")
                    return [s[1] for s in sorted(starters, key=lambda x: x[0])], subs_used, subs_unused

                h_s, h_u, h_un = format_official_sheet(h_sheet)
                a_s, a_u, a_un = format_official_sheet(a_sheet)
                raw_lineup = {
                    "has_lineups": True,
                    "h_starters": h_s, "h_subs_used": h_u, "h_subs_unused": h_un,
                    "a_starters": a_s, "a_subs_used": a_u, "a_subs_unused": a_un
                }

    # 2. ESPN Backup
    if not raw_lineup:
        raw_lineup = _fetch_espn_lineup_backup(home_short, away_short)

    # 3. FPL Live Elements Fallback
    if not raw_lineup and live_elements and element_lookup and home_team_id and away_team_id:
        def extract_squad(target_club_id):
            club_players = []
            for elem_str_id, e_info in live_elements.items():
                try:
                    eid = int(elem_str_id)
                except Exception:
                    continue
                p_obj = element_lookup.get(eid, {})
                if p_obj.get("team") == target_club_id:
                    stats = e_info.get("stats", {}) if isinstance(e_info, dict) else {}
                    pos_id = p_obj.get("element_type", 1)
                    club_players.append({
                        "id": eid, "name": p_obj.get("web_name", "Unknown"),
                        "pos": {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(pos_id, "MID"),
                        "pos_rank": pos_id, "mins": safe_int(stats.get("minutes", 0)),
                        "pts": safe_int(stats.get("total_points", 0)),
                        "status": p_obj.get("status", "a"),
                        "chance": p_obj.get("chance_of_playing_next_round")
                    })
            played = [p for p in club_players if p["mins"] > 0]
            if not played:
                return [], [], []
            gkps_played = [p for p in played if p["pos"] == "GKP"]
            outfield_played = [p for p in played if p["pos"] != "GKP"]
            starting_gk = sorted(gkps_played, key=lambda x: x["mins"], reverse=True)[:1] if gkps_played else []
            other_gks = [p for p in gkps_played if p not in starting_gk]
            sorted_out = sorted(outfield_played, key=lambda x: x["mins"], reverse=True)
            starters_sorted = sorted(starting_gk + sorted_out[:10], key=lambda x: (x["pos_rank"], -x["mins"]))
            eff_full = max([p["mins"] for p in starters_sorted]) if starters_sorted else match_minute

            s_fmt = [f"<b>{p['name']}</b> • <i>{p['pos']}</i> ({p['mins']}', {p['pts']} pts)" + (f" <span style='color:#f43f5e; font-weight:700;'>▼ {p['mins']}'</span>" if p["mins"] < eff_full else "") for p in starters_sorted]
            u_sorted = sorted(other_gks + sorted_out[10:], key=lambda x: (x["pos_rank"], -x["mins"]))
            u_fmt = [f"<b>{p['name']}</b> • <i>{p['pos']}</i> ({p['mins']}', {p['pts']} pts) <span style='color:#22c55e; font-weight:800;'>▲ {max(1, eff_full - p['mins'])}'</span>" for p in u_sorted]
            played_ids = {p["id"] for p in played}
            unplayed = sorted([p for p in club_players if p["id"] not in played_ids and p["status"] not in ["i", "s", "u"]], key=lambda x: x["pos_rank"])[:9]
            un_fmt = [f"{p['name']} ({p['pos']})" for p in unplayed]
            return s_fmt, u_fmt, un_fmt

        h_s, h_u, h_un = extract_squad(home_team_id)
        a_s, a_u, a_un = extract_squad(away_team_id)
        if h_s or a_s:
            raw_lineup = {
                "has_lineups": True,
                "h_starters": h_s, "h_subs_used": h_u, "h_subs_unused": h_un,
                "a_starters": a_s, "a_subs_used": a_u, "a_subs_unused": a_un
            }

    if raw_lineup and raw_lineup.get("has_lineups"):
        raw_lineup["pitch_h"] = build_epl_pitch_payload_from_lists(
            raw_lineup["h_starters"], raw_lineup["h_subs_used"], raw_lineup["h_subs_unused"],
            home_short, home_team_id, live_elements, element_lookup
        )
        raw_lineup["pitch_a"] = build_epl_pitch_payload_from_lists(
            raw_lineup["a_starters"], raw_lineup["a_subs_used"], raw_lineup["a_subs_unused"],
            away_short, away_team_id, live_elements, element_lookup
        )
        return raw_lineup

    return {"has_lineups": False}

@app.get("/api/epl_scores")
def get_epl_scores(gw: str = "0"):
    try:
        target_gw = int(gw)
    except Exception:
        target_gw = 0

    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(63)
    detected_gw, all_gws = detect_current_gw(league_details)
    selected_gw = target_gw if target_gw > 0 else detected_gw

    team_name_map = {item["id"]: item["name"] for item in static_data["teams"]}
    team_short_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}

    fixtures = cached_epl_fixtures(selected_gw) or []
    live_event_data = cached_live_event(selected_gw)
    live_elements = live_event_data.get("elements", {}) if live_event_data else {}

    def process_epl_fixture(f):
        h_id, a_id = f.get("team_h"), f.get("team_a")
        h_name = team_name_map.get(h_id, "Home")
        a_name = team_name_map.get(a_id, "Away")
        h_short = team_short_map.get(h_id, "H")
        a_short = team_short_map.get(a_id, "A")
        is_finished = f.get("finished", False) or f.get("finished_provisional", False)
        is_started = f.get("started", False)
        h_score = safe_int(f.get("team_h_score", 0))
        a_score = safe_int(f.get("team_a_score", 0))

        if is_finished:
            status_text, status_color = "FT", "#94a3b8"
        elif is_started:
            status_text, status_color = f"LIVE {f.get('minutes', 0)}'", "#f59e0b"
        else:
            ko = f.get("kickoff_time")
            try:
                status_text = pd.to_datetime(ko).strftime("%a %d %b, %H:%M") if ko else "Upcoming"
            except Exception:
                status_text = ko[11:16] if ko else "Upcoming"
            status_color = "#cbd5e1"

        stats_raw = f.get("stats", [])
        stats_dict = {item["identifier"]: {"h": item.get("h", []), "a": item.get("a", [])} for item in stats_raw}

        def get_stat_entries(ident, side):
            return [
                (element_lookup.get(entry["element"], {}).get("web_name", "Unknown"), entry.get("value", 1))
                for entry in stats_dict.get(ident, {}).get(side, [])
            ]

        def resolve_defcon_achieved(side, team_id):
            achieved = []
            dc_items = stats_dict.get("defensive_contributions", {}).get(side, []) or stats_dict.get("cbit", {}).get(side, []) or stats_dict.get("defcon", {}).get(side, [])
            for itm in dc_items:
                if isinstance(itm, dict):
                    p_elem = element_lookup.get(itm.get("element"), {})
                    p_name = p_elem.get("web_name", "Unknown")
                    p_pos = p_elem.get("element_type", 1)
                    val = safe_int(itm.get("value", 0))
                    if (p_pos == 2 and val >= 10) or (p_pos in [3, 4] and val >= 12) or val >= 10:
                        achieved.append(p_name)
            if live_elements:
                for elem_str_id, e_data in live_elements.items():
                    if not isinstance(e_data, dict): continue
                    try:
                        elem_obj = element_lookup.get(int(elem_str_id), {})
                        if elem_obj.get("team") == team_id:
                            p_name = elem_obj.get("web_name", "Unknown")
                            p_pos = elem_obj.get("element_type", 1)
                            if extract_defcon_flag(e_data.get("stats", {}), e_data.get("explain", []), p_pos) and p_name not in achieved:
                                achieved.append(p_name)
                    except Exception:
                        pass
            return achieved

        def build_side_events(side, team_id, opp_score):
            lines = []
            goals = get_stat_entries("goals_scored", side)
            assists = get_stat_entries("assists", side)
            saves = get_stat_entries("saves", side)
            og = get_stat_entries("own_goals", side)
            pmiss = get_stat_entries("penalties_missed", side)
            psaved = get_stat_entries("penalties_saved", side)
            dc_hit = resolve_defcon_achieved(side, team_id)

            cs_players = []
            if is_started and live_elements and opp_score == 0:
                for elem_id_str, e_data in live_elements.items():
                    try:
                        elem_obj = element_lookup.get(int(elem_id_str), {})
                        if elem_obj.get("team") == team_id and safe_int(e_data.get("stats", {}).get("clean_sheets", 0)) > 0:
                            cs_players.append(elem_obj.get("web_name", "Unknown"))
                    except Exception:
                        pass

            if goals: lines.append("⚽ <b>Goals:</b> " + ", ".join([f"{n} ({v})" if v > 1 else n for n, v in goals]))
            if assists: lines.append("🎯 <b>Assists:</b> " + ", ".join([f"{n} ({v})" if v > 1 else n for n, v in assists]))
            if dc_hit: lines.append("<span style='color:#22c55e;'>🔰 <b>DEFCON (+2 pts):</b> " + ", ".join(dc_hit) + "</span>")
            if cs_players: lines.append("🛡️ <b>Clean Sheets:</b> " + ", ".join(cs_players))
            if saves: lines.append("🧤 <b>Saves:</b> " + ", ".join([f"{n} ({v} saves)" for n, v in saves]))
            if og: lines.append("<span style='color:#ef4444;'>🛑 <b>Own Goals:</b> " + ", ".join([f"{n} ({v})" if v > 1 else n for n, v in og]) + "</span>")
            if pmiss: lines.append("<span style='color:#ef4444;'>❌ <b>Penalties Missed:</b> " + ", ".join([f"{n} ({v})" if v > 1 else n for n, v in pmiss]) + "</span>")
            if psaved: lines.append("<span style='color:#22c55e;'>🧤 <b>Penalties Saved:</b> " + ", ".join([f"{n} ({v})" if v > 1 else n for n, v in psaved]) + "</span>")
            return lines

        # BPS Ranking
        bps_list = []
        for item in stats_dict.get("bps", {}).get("h", []) + stats_dict.get("bps", {}).get("a", []):
            eid = item.get("element")
            p_elem = element_lookup.get(eid, {})
            bps_list.append({
                "element": eid,
                "player": p_elem.get("web_name", "Unknown"),
                "club": team_short_map.get(p_elem.get("team"), ""),
                "pos": {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(p_elem.get("element_type", 1), ""),
                "bps": safe_int(item.get("value", 0))
            })
        bps_sorted = sorted(bps_list, key=lambda x: x["bps"], reverse=True)
        unique_scores = sorted(list({p["bps"] for p in bps_sorted}), reverse=True)
        bonus_award = {}
        if len(unique_scores) >= 1:
            top_val = unique_scores[0]
            top_count = sum(1 for p in bps_sorted if p["bps"] == top_val)
            for p in bps_sorted:
                if p["bps"] == top_val: bonus_award[p["element"]] = 3
            if top_count == 1 and len(unique_scores) >= 2:
                sec_val = unique_scores[1]
                sec_count = sum(1 for p in bps_sorted if p["bps"] == sec_val)
                for p in bps_sorted:
                    if p["bps"] == sec_val: bonus_award[p["element"]] = 2
                if sec_count == 1 and len(unique_scores) >= 3:
                    third_val = unique_scores[2]
                    for p in bps_sorted:
                        if p["bps"] == third_val: bonus_award[p["element"]] = 1
            elif top_count == 2 and len(unique_scores) >= 2:
                sec_val = unique_scores[1]
                for p in bps_sorted:
                    if p["bps"] == sec_val: bonus_award[p["element"]] = 1

        bps_rows = []
        for rank, p in enumerate(bps_sorted[:12], 1):
            b_pts = bonus_award.get(p["element"], 0)
            bps_rows.append({
                "rank": rank, "player": p["player"], "club": p["club"], "pos": p["pos"], "bps": p["bps"],
                "bonus_html": f"<span style='color:#f59e0b; font-weight:800;'>+{b_pts} pts</span>" if b_pts > 0 else "<span style='color:#64748b;'>-</span>"
            })

        # DefCon Table
        defcon_map = {}
        for k_name in ["defensive_contributions", "cbit", "defcon"]:
            for item in stats_dict.get(k_name, {}).get("h", []) + stats_dict.get(k_name, {}).get("a", []):
                if isinstance(item, dict) and item.get("element"):
                    eid = int(item["element"])
                    defcon_map[eid] = max(defcon_map.get(eid, 0), safe_int(item.get("value", 0)))

        if live_elements:
            for elem_str_id, e_data in live_elements.items():
                if not isinstance(e_data, dict): continue
                try:
                    eid = int(elem_str_id)
                except Exception:
                    continue
                p_elem = element_lookup.get(eid, {})
                if p_elem.get("team") not in (h_id, a_id): continue
                pos_num = p_elem.get("element_type", 1)
                if pos_num == 1: continue
                e_stats = e_data.get("stats", {}) if isinstance(e_data.get("stats"), dict) else {}
                cbi = safe_int(e_stats.get("clearances_blocks_interceptions", 0) or e_stats.get("cbi", 0))
                tackles = safe_int(e_stats.get("tackles", 0))
                recov = safe_int(e_stats.get("recoveries", 0) or e_stats.get("ball_recoveries", 0))
                dc_dir = safe_int(e_stats.get("defensive_contributions", 0) or e_stats.get("defcon", 0) or e_stats.get("cbit", 0))
                calc_val = dc_dir if dc_dir > 0 else (cbi + tackles + recov if pos_num in [3, 4] else cbi + tackles)
                if calc_val > 0:
                    defcon_map[eid] = max(defcon_map.get(eid, 0), calc_val)

        dc_list = []
        for eid, dc_val in defcon_map.items():
            if dc_val <= 0: continue
            p_elem = element_lookup.get(eid, {})
            pos_num = p_elem.get("element_type", 1)
            if pos_num == 1: continue
            target_val = 10 if pos_num == 2 else 12
            dc_list.append({
                "player": p_elem.get("web_name", "Unknown"),
                "club": team_short_map.get(p_elem.get("team"), ""),
                "pos": {2: "DEF", 3: "MID", 4: "FWD"}.get(pos_num, "MID"),
                "dc": dc_val, "target": target_val, "is_hit": dc_val >= target_val
            })
        dc_sorted = sorted(dc_list, key=lambda x: (x["dc"], x["is_hit"]), reverse=True)
        dc_rows = []
        for rank, p in enumerate(dc_sorted, 1):
            dc_rows.append({
                "rank": rank, "player": p["player"], "club": p["club"], "pos": p["pos"],
                "defcon_str": f"{p['dc']} / {p['target']}",
                "status_html": "<span style='color:#22c55e; font-weight:800;'>+2 pts ✅</span>" if p["is_hit"] else f"<span style='color:#94a3b8;'>{p['target'] - p['dc']} away</span>"
            })

        lineup_sheet = fetch_epl_match_lineup(f, h_short, a_short, live_elements, element_lookup, selected_gw)

        return {
            "id": f.get("id"),
            "h_name": h_name, "a_name": a_name, "h_short": h_short, "a_short": a_short,
            "is_started": is_started, "is_finished": is_finished,
            "h_score": h_score, "a_score": a_score,
            "status_text": status_text, "status_color": status_color,
            "events": {"h": build_side_events("h", h_id, a_score), "a": build_side_events("a", a_id, h_score)},
            "lineups": lineup_sheet,
            "bps": bps_rows,
            "defcon": dc_rows
        }

    with ThreadPoolExecutor(max_workers=10) as ex:
        fix_results = list(ex.map(process_epl_fixture, fixtures))

    return {
        "gw": selected_gw,
        "detected_gw": detected_gw,
        "all_gws": all_gws,
        "fixtures": fix_results
    }

# ==========================================
# 4. STANDINGS
# ==========================================
@app.get("/api/standings")
def get_standings(league_id: int = 63):
    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(league_id)
    all_fixtures = cached_all_fixtures()

    current_gw, _ = detect_current_gw(league_details)
    last_completed_gw = current_gw - 1 if current_gw > 1 else 1

    entries = league_details.get("league_entries", []) if league_details else []
    matches = league_details.get("matches", []) if league_details else []
    lentry_map = {e["id"]: e for e in entries}

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}

    live_data = cached_live_event(current_gw)
    live_elements = live_data.get("elements", {}) if live_data else {}
    club_minutes = {}
    for elem_str_id, e_info in live_elements.items():
        try:
            c_id = element_lookup.get(int(elem_str_id), {}).get("team")
            if c_id:
                club_minutes[c_id] = club_minutes.get(c_id, 0) + safe_int(e_info.get("stats", {}).get("minutes", 0))
        except Exception:
            pass

    official_stats = {e["id"]: {"wins": 0, "draws": 0, "losses": 0, "pf": 0, "pts": 0} for e in entries}
    live_stats = {e["id"]: {"wins": 0, "draws": 0, "losses": 0, "pf": 0, "pts": 0} for e in entries}

    for m in matches:
        ev = m["event"]
        t1_id, t2_id = m["league_entry_1"], m["league_entry_2"]
        if t1_id not in official_stats or t2_id not in official_stats:
            continue
        if ev < current_gw and m.get("finished", False):
            s1, s2 = safe_int(m.get("league_entry_1_points", 0)), safe_int(m.get("league_entry_2_points", 0))
            for st_map in (official_stats, live_stats):
                st_map[t1_id]["pf"] += s1
                st_map[t2_id]["pf"] += s2
                if s1 > s2:
                    st_map[t1_id]["wins"] += 1; st_map[t1_id]["pts"] += 3; st_map[t2_id]["losses"] += 1
                elif s2 > s1:
                    st_map[t2_id]["wins"] += 1; st_map[t2_id]["pts"] += 3; st_map[t1_id]["losses"] += 1
                else:
                    st_map[t1_id]["draws"] += 1; st_map[t1_id]["pts"] += 1
                    st_map[t2_id]["draws"] += 1; st_map[t2_id]["pts"] += 1
        elif ev == current_gw:
            if m.get("finished", False):
                s1, s2 = safe_int(m.get("league_entry_1_points", 0)), safe_int(m.get("league_entry_2_points", 0))
            else:
                p1 = cached_entry_event(lentry_map[t1_id].get("entry_id"), current_gw)
                p2 = cached_entry_event(lentry_map[t2_id].get("entry_id"), current_gw)
                _, _, s1, _, _, _, _, _ = full_evaluate_lineup(p1, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures)
                _, _, s2, _, _, _, _, _ = full_evaluate_lineup(p2, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures)
            live_stats[t1_id]["pf"] += s1
            live_stats[t2_id]["pf"] += s2
            if s1 > s2:
                live_stats[t1_id]["wins"] += 1; live_stats[t1_id]["pts"] += 3; live_stats[t2_id]["losses"] += 1
            elif s2 > s1:
                live_stats[t2_id]["wins"] += 1; live_stats[t2_id]["pts"] += 3; live_stats[t1_id]["losses"] += 1
            else:
                live_stats[t1_id]["draws"] += 1; live_stats[t1_id]["pts"] += 1
                live_stats[t2_id]["draws"] += 1; live_stats[t2_id]["pts"] += 1

    off_rows = []
    for e in entries:
        tid = e["id"]
        st = official_stats[tid]
        alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        off_rows.append({"team_id": tid, "team": e.get("entry_name", "Team"), "manager": alias, "w": st["wins"], "d": st["draws"], "l": st["losses"], "pf": st["pf"], "pts": st["pts"]})
    off_rows = sorted(off_rows, key=lambda x: (x["pts"], x["pf"]), reverse=True)
    off_rank_map = {}
    for idx, r in enumerate(off_rows, 1):
        r["pos"] = idx
        off_rank_map[r["team_id"]] = idx

    live_rows = []
    for e in entries:
        tid = e["id"]
        st = live_stats[tid]
        alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        live_rows.append({"team_id": tid, "team": e.get("entry_name", "Team"), "manager": alias, "w": st["wins"], "d": st["draws"], "l": st["losses"], "pf": st["pf"], "pts": st["pts"]})
    live_rows = sorted(live_rows, key=lambda x: (x["pts"], x["pf"]), reverse=True)
    for idx, r in enumerate(live_rows, 1):
        r["pos"] = idx
        diff = off_rank_map.get(r["team_id"], idx) - idx
        if diff > 0:
            r["move_html"] = f"<span style='color:#22c55e; font-weight:800;'>▲ {diff}</span>"
        elif diff < 0:
            r["move_html"] = f"<span style='color:#ef4444; font-weight:800;'>▼ {abs(diff)}</span>"
        else:
            r["move_html"] = "<span style='color:#64748b; font-weight:700;'>▬</span>"

    return {
        "current_gw": current_gw,
        "last_completed_gw": last_completed_gw,
        "live_table": live_rows,
        "official_table": off_rows
    }

# ==========================================
# 5. SQUAD ANALYSER
# ==========================================
@app.get("/api/squad_analyser")
def get_squad_analyser(league_id: int = 63, alias: str = "", target_gw: str = "0", focus: str = "Squad Needs (Auto)", entry_id: str = ""):
    static_data = cached_fpl_static()
    league_details, element_status = cached_league_data(league_id)
    all_fixtures = cached_all_fixtures()

    current_gw, all_events = detect_current_gw(league_details)
    future_gws = [g for g in all_events if g >= current_gw] or [current_gw]
    try:
        t_gw = int(target_gw) if int(target_gw) in future_gws else current_gw
    except Exception:
        t_gw = current_gw

    entries = league_details.get("league_entries", []) if league_details else []
    is_admin = (alias.strip().lower() == "admin")

    admin_teams = []
    matched_entry_id = None
    entry_label_map = {}
    for e in entries:
        eid = e.get("entry_id")
        m_alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        lbl = f"{m_alias} ({e.get('entry_name', 'Team')})"
        entry_label_map[eid] = lbl
        admin_teams.append({"entry_id": eid, "label": lbl})
        if m_alias.lower() == alias.strip().lower():
            matched_entry_id = eid

    if is_admin:
        try:
            sel_entry_id = int(entry_id) if entry_id else (matched_entry_id or (admin_teams[0]["entry_id"] if admin_teams else None))
        except Exception:
            sel_entry_id = admin_teams[0]["entry_id"] if admin_teams else None
    else:
        if not matched_entry_id:
            return {
                "locked": True,
                "lock_message": f"🔒 Squad Analyser Locked: You do not manage a team in {LEAGUE_ID_TO_KEY.get(league_id, 'this division')}. Switch to your home division tab above to analyse your squad."
            }
        sel_entry_id = matched_entry_id

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}

    matches = league_details.get("matches", []) if league_details else []
    fin_events = sorted(list({m["event"] for m in matches if m.get("finished", False)}))
    prev1 = cached_live_event(fin_events[-1]) if fin_events else None
    prev2 = cached_live_event(fin_events[-2]) if len(fin_events) >= 2 else None

    def get_next_3(tid):
        if not all_fixtures or not tid: return "TBD"
        up = sorted([f for f in all_fixtures if not f.get("finished", False) and (f.get("team_h") == tid or f.get("team_a") == tid)], key=lambda x: (x.get("event") or 99, x.get("kickoff_time") or ""))[:3]
        if not up: return "None"
        return ", ".join([f"{team_map.get(f.get('team_a'), 'OPP')} (H)" if f.get("team_h") == tid else f"{team_map.get(f.get('team_h'), 'OPP')} (A)" for f in up])

    def get_single_gw_opp(tid, g_num):
        if not all_fixtures or not tid: return "TBD"
        t_fixes = [f for f in all_fixtures if f.get("event") == g_num and (f.get("team_h") == tid or f.get("team_a") == tid)]
        if not t_fixes: return "Blank"
        return ", ".join([f"{team_map.get(f.get('team_a'), 'OPP')} (H)" if f.get("team_h") == tid else f"{team_map.get(f.get('team_h'), 'OPP')} (A)" for f in t_fixes])

    owner_map = {item["element"]: item.get("owner") for item in (element_status or {}).get("element_status", [])}
    all_entry_ids = set(entry_label_map.keys())

    players = []
    for raw_elem in static_data.get("elements", []):
        eid = raw_elem["id"]
        if eid not in owner_map:
            continue
        owner = owner_map[eid]
        tid = raw_elem.get("team")
        pos_str = pos_map.get(raw_elem.get("element_type", 1), "MID")
        form_val = round(float(raw_elem.get("form") or 0.0), 1)
        ppg_val = round(float(raw_elem.get("points_per_game") or 0.0), 1)
        ict_val = round(float(raw_elem.get("ict_index") or 0.0), 1)
        tot_pts = safe_int(raw_elem.get("total_points", 0))
        mins = safe_int(raw_elem.get("minutes", 0))
        avail = round(get_availability_multiplier(raw_elem), 1)

        s_id = str(eid)
        l2_pts = 0
        if prev1: l2_pts += safe_int(prev1.get("elements", {}).get(s_id, {}).get("stats", {}).get("total_points", 0))
        if prev2: l2_pts += safe_int(prev2.get("elements", {}).get(s_id, {}).get("stats", {}).get("total_points", 0))

        if avail <= 0.0:
            proj_gw = 0.0
            starter_rating = -9999.0
        else:
            base_exp = ((ppg_val * 0.6) + (form_val * 0.4)) * avail
            if t_gw > 3 and (mins / max(1.0, float(t_gw * 60))) < 0.6:
                base_exp *= 0.8
            if base_exp <= 0:
                base_exp = 2.0
            proj_gw = round(base_exp * get_fdr_multiplier(tid, t_gw, all_fixtures), 1)
            starter_rating = round(((form_val * 1.8) + (ppg_val * 2.0) + (ict_val * 0.05)) * avail, 1)

        players.append({
            "id": eid, "web_name": str(raw_elem.get("web_name", "Unknown")),
            "position": pos_str, "pos_rank": POS_ORDER.get(pos_str, 99),
            "club": str(team_map.get(tid, "PL")).upper(), "team": tid,
            "owner": owner, "form": form_val, "ppg": ppg_val, "ict": ict_val,
            "total_points": tot_pts, "minutes": mins, "avail_factor": avail,
            "health_status": get_health_label(raw_elem), "status": raw_elem.get("status", "a"),
            "chance_of_playing_next_round": raw_elem.get("chance_of_playing_next_round"),
            "last_2_pts": l2_pts, "next_3": get_next_3(tid),
            "gw_opp": get_single_gw_opp(tid, t_gw),
            "proj_gw": proj_gw, "starter_rating": starter_rating
        })

    my_squad = sorted([p for p in players if p["owner"] == sel_entry_id], key=lambda x: (x["proj_gw"], x["starter_rating"]), reverse=True)
    waiver_pool = [p for p in players if not p["owner"]]

    gks = [p for p in my_squad if p["position"] == "GKP"]
    defs = [p for p in my_squad if p["position"] == "DEF"]
    mids = [p for p in my_squad if p["position"] == "MID"]
    fwds = [p for p in my_squad if p["position"] == "FWD"]

    starting_xi = []
    bench_gk = []
    if gks:
        starting_xi.append(gks[0])
        bench_gk.extend(gks[1:])
    starting_xi.extend(defs[:3])
    starting_xi.extend(mids[:2])
    starting_xi.extend(fwds[:1])

    used_ids = {p["id"] for p in starting_xi}
    rem_outfield = [p for p in my_squad if p["id"] not in used_ids and p["position"] != "GKP"]
    starting_xi.extend(rem_outfield[:(11 - len(starting_xi))])

    final_xi_ids = {p["id"] for p in starting_xi}
    bench_outfield = sorted([p for p in my_squad if p["id"] not in final_xi_ids and p["position"] != "GKP"], key=lambda x: (x["pos_rank"], -x["proj_gw"]))

    starting_xi_sorted = sorted(starting_xi, key=lambda x: (x["pos_rank"], -x["proj_gw"]))
    xi_proj_sum = f"{sum(p['proj_gw'] for p in starting_xi_sorted):.1f}"

    def to_pitch_rec(p):
        return {
            "Player": p["web_name"], "Pos": p["position"], "Club": p["club"],
            "Opp": p["gw_opp"], "Pts": p["total_points"], "Proj": p["proj_gw"],
            "Mins": 0, "G": 0, "A": 0, "CS": 0, "GC": 0, "Bonus": 0, "Saves": 0,
            "YC": 0, "RC": 0, "Penalties_Saved": 0, "Penalties_Missed": 0,
            "DEFCON_Achieved": False, "State": "YTP", "sub_action": "",
            "status": p["status"], "chance_of_playing_next_round": p["chance_of_playing_next_round"]
        }

    pitch_data = make_pitch_payload(
        [to_pitch_rec(p) for p in starting_xi_sorted],
        [to_pitch_rec(p) for p in (bench_gk + bench_outfield)],
        show_proj_pill=True
    )

    xi_table = [{
        "player": p["web_name"], "pos": p["position"], "club": p["club"], "status": p["health_status"],
        "gw_proj": f"{p['proj_gw']:.1f}", "season_pts": p["total_points"], "last_2": p["last_2_pts"],
        "next_3": p["next_3"], "ppg": f"{p['ppg']:.1f}", "form": f"{p['form']:.1f}"
    } for p in starting_xi_sorted]

    bench_table = []
    for bg in bench_gk:
        bench_table.append({
            "role": "GK Sub", "player": bg["web_name"], "pos": bg["position"], "club": bg["club"], "status": bg["health_status"],
            "gw_proj": f"{bg['proj_gw']:.1f}", "season_pts": bg["total_points"], "last_2": bg["last_2_pts"],
            "next_3": bg["next_3"], "ppg": f"{bg['ppg']:.1f}", "form": f"{bg['form']:.1f}"
        })
    for idx, bo in enumerate(bench_outfield, 1):
        bench_table.append({
            "role": f"Sub {idx}", "player": bo["web_name"], "pos": bo["position"], "club": bo["club"], "status": bo["health_status"],
            "gw_proj": f"{bo['proj_gw']:.1f}", "season_pts": bo["total_points"], "last_2": bo["last_2_pts"],
            "next_3": bo["next_3"], "ppg": f"{bo['ppg']:.1f}", "form": f"{bo['form']:.1f}"
        })

    # Waivers & Alerts
    rostered = [p for p in players if p["owner"] in all_entry_ids]
    alerts, target_positions = [], []
    fit_defs = sum(1 for p in my_squad if p["position"] == "DEF" and p["avail_factor"] >= 0.9)
    fit_fwds = sum(1 for p in my_squad if p["position"] == "FWD" and p["avail_factor"] >= 0.9)
    if fit_defs < 3:
        alerts.append(f"🛡️ DEF Depth Emergency: Only {fit_defs} defender(s) 100% fit for the upcoming round. Immediate cover required.")
        target_positions.append("DEF")
    if fit_fwds < 1:
        alerts.append("⚡ FWD Availability Crisis: 0 fit strikers currently available in your squad.")
        target_positions.append("FWD")

    for pk in ["DEF", "MID", "FWD"]:
        s_vals = [p["ppg"] for p in my_squad if p["position"] == pk]
        l_vals = [p["ppg"] for p in rostered if p["position"] == pk]
        s_avg = round(sum(s_vals) / len(s_vals), 1) if s_vals else 0.0
        l_avg = round(sum(l_vals) / len(l_vals), 1) if l_vals else 0.0
        if s_avg < l_avg - 0.7:
            alerts.append(f"⚠️ {pk} Production Deficit: Your {pk} unit averages {s_avg:.1f} PPG vs the league average of {l_avg:.1f} PPG.")
            if pk not in target_positions:
                target_positions.append(pk)

    if not target_positions:
        target_positions = ["DEF", "MID", "FWD"]

    if focus == "DEF Only": active_pos_filter = ["DEF"]
    elif focus == "MID Only": active_pos_filter = ["MID"]
    elif focus == "FWD Only": active_pos_filter = ["FWD"]
    elif focus == "All Outfield": active_pos_filter = ["DEF", "MID", "FWD"]
    else: active_pos_filter = target_positions

    top_pts_ids = {p["id"] for p in sorted(my_squad, key=lambda x: x["total_points"], reverse=True)[:3]}
    top_ppg_ids = {p["id"] for p in sorted(my_squad, key=lambda x: x["ppg"], reverse=True)[:3]}
    top_form_ids = {p["id"] for p in sorted(my_squad, key=lambda x: x["form"], reverse=True)[:2]}
    untouchables = top_pts_ids.union(top_ppg_ids).union(top_form_ids)

    droppable = sorted(
        [p for p in my_squad if p["id"] not in untouchables],
        key=lambda x: ((x["ppg"] * 1.5) + (x["form"] * 1.0)) * x["avail_factor"]
    )

    cand_waivers = sorted(
        [w for w in waiver_pool if w["position"] in active_pos_filter and w["avail_factor"] >= 0.6 and w["total_points"] >= 5],
        key=lambda x: x["starter_rating"], reverse=True
    )[:10]

    waiver_rows = []
    for w_cand in cand_waivers:
        pos_drops = [d for d in droppable if d["position"] == w_cand["position"]]
        drop_p = pos_drops[0] if pos_drops else (droppable[0] if droppable else None)
        if drop_p:
            f_diff = round(w_cand["form"] - drop_p["form"], 1)
            p_diff = round(w_cand["ppg"] - drop_p["ppg"], 1)
            f_str = f"+{f_diff:.1f}" if f_diff > 0 else f"{f_diff:.1f}"
            p_str = f"+{p_diff:.1f}" if p_diff > 0 else f"{p_diff:.1f}"
            if drop_p["avail_factor"] < 1.0 and w_cand["avail_factor"] == 1.0:
                rat = f"Fit Cover ({f_str} Form)"
            elif f_diff > 1.5:
                rat = f"Form Spike ({f_str} Form)"
            else:
                rat = f"{p_str} PPG baseline"
            waiver_rows.append({
                "target": f"{w_cand['web_name']} ({w_cand['club']})",
                "pos": w_cand["position"], "form": f"{w_cand['form']:.1f}", "ppg": f"{w_cand['ppg']:.1f}",
                "next_3": w_cand["next_3"], "drop": f"{drop_p['web_name']} ({drop_p['club']})",
                "drop_status": drop_p["health_status"], "rationale": rat
            })

    mgr_name = entry_label_map.get(sel_entry_id, "Selected Squad").split(" (")[0]
    return {
        "locked": False,
        "is_admin": is_admin,
        "admin_teams": admin_teams,
        "selected_entry_id": sel_entry_id,
        "manager_name": mgr_name,
        "current_gw": current_gw,
        "target_gw": t_gw,
        "future_gws": future_gws,
        "xi_proj_sum": xi_proj_sum,
        "pitch_data": pitch_data,
        "xi_table": xi_table,
        "bench_table": bench_table,
        "alerts": alerts,
        "waivers": waiver_rows
    }

# ==========================================
# 6. TRADE HUB
# ==========================================
trade_file = base_dir / "trade_block.json"

def load_trade_block_file():
    if trade_file.exists():
        try:
            with open(trade_file, "r", encoding="utf-8") as tf:
                data = json.load(tf)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []

def save_trade_block_file(listings):
    try:
        with open(trade_file, "w", encoding="utf-8") as tf:
            json.dump(listings, tf, indent=2, ensure_ascii=False)
    except Exception:
        pass

@app.get("/api/trade_hub")
def get_trade_hub(league_id: int = 63, alias: str = ""):
    static_data = cached_fpl_static()
    league_details, element_status = cached_league_data(league_id)
    all_fixtures = cached_all_fixtures()
    league_key = LEAGUE_ID_TO_KEY.get(league_id, "CDP (Crème Dellar Prem)")

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}

    entries = league_details.get("league_entries", []) if league_details else []
    entry_options = {}
    teams_list = []
    matched_entry_id = None
    for e in entries:
        eid = e["entry_id"]
        m_alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        t_name = e.get("entry_name", "Team")
        entry_options[eid] = {"alias": m_alias, "team_name": t_name}
        teams_list.append({"entry_id": eid, "label": f"{m_alias} ({t_name})"})
        if m_alias.lower() == alias.strip().lower():
            matched_entry_id = eid

    is_admin = (alias.strip().lower() == "admin")
    can_manage = bool(matched_entry_id or is_admin)
    active_entry_id = matched_entry_id if matched_entry_id else (teams_list[0]["entry_id"] if (is_admin and teams_list) else None)
    active_manager_alias = entry_options[active_entry_id]["alias"] if active_entry_id in entry_options else alias

    def get_next_3(tid):
        if not all_fixtures or not tid: return "TBD"
        up = sorted([f for f in all_fixtures if not f.get("finished", False) and (f.get("team_h") == tid or f.get("team_a") == tid)], key=lambda x: (x.get("event") or 99, x.get("kickoff_time") or ""))[:3]
        if not up: return "None"
        return ", ".join([f"{team_map.get(f.get('team_a'), 'OPP')} (H)" if f.get("team_h") == tid else f"{team_map.get(f.get('team_h'), 'OPP')} (A)" for f in up])

    owner_map = {item["element"]: item.get("owner") for item in (element_status or {}).get("element_status", [])}
    players = []
    for raw_elem in static_data.get("elements", []):
        eid = raw_elem["id"]
        if eid not in owner_map: continue
        owner = owner_map[eid]
        tid = raw_elem.get("team")
        pos_str = pos_map.get(raw_elem.get("element_type", 1), "MID")
        form_val = round(float(raw_elem.get("form") or 0.0), 1)
        ppg_val = round(float(raw_elem.get("points_per_game") or 0.0), 1)
        ict_val = round(float(raw_elem.get("ict_index") or 0.0), 1)
        tot_pts = safe_int(raw_elem.get("total_points", 0))
        avail = round(get_availability_multiplier(raw_elem), 1)
        t_val = round(((ppg_val * 2.0) + (form_val * 1.8) + (ict_val * 0.05)) * avail, 1)

        players.append({
            "id": eid,
            "web_name": str(raw_elem.get("web_name", "Unknown")),
            "position": pos_str,
            "club": str(team_map.get(tid, "PL")).upper(),
            "owner": owner,
            "owner_alias": entry_options.get(owner, {}).get("alias", "Free Agent"),
            "status": get_health_label(raw_elem),
            "avail_factor": avail,
            "total_points": tot_pts,
            "ppg": ppg_val,
            "form": form_val,
            "next_3": get_next_3(tid),
            "trade_value": t_val
        })

    players_sorted = sorted(players, key=lambda x: x["total_points"], reverse=True)
    my_squad = [p for p in players_sorted if p["owner"] == active_entry_id] if active_entry_id else []

    raw_listings = load_trade_block_file()
    formatted_listings = []
    for item in raw_listings:
        formatted_listings.append({
            **item,
            "div": str(item.get("league_key", "")).split(" ")[0]
        })

    return {
        "league_key": league_key,
        "can_manage": can_manage,
        "active_manager_alias": active_manager_alias,
        "matched_entry_id": matched_entry_id,
        "listings": formatted_listings,
        "my_squad": my_squad,
        "teams": teams_list,
        "players": players_sorted
    }

@app.post("/api/trade_hub/add")
async def add_trade_hub_item(request: Request):
    body = await request.json()
    league_id = int(body.get("league_id", 63))
    alias = str(body.get("alias", "")).strip()
    player_id = int(body.get("player_id", 0))
    notes = str(body.get("notes", "Open to offers")).strip() or "Open to offers"

    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(league_id)
    league_key = LEAGUE_ID_TO_KEY.get(league_id, "CDP (Crème Dellar Prem)")

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    p_obj = next((el for el in static_data.get("elements", []) if el["id"] == player_id), None)
    if not p_obj:
        return {"status": "error"}

    team_name = "Team"
    mgr_alias = alias
    for e in (league_details or {}).get("league_entries", []):
        m_a = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        if m_a.lower() == alias.lower():
            team_name = e.get("entry_name", "Team")
            mgr_alias = m_a
            break

    listings = load_trade_block_file()
    listings = [t for t in listings if not (t.get("player_id") == player_id and t.get("manager_alias") == mgr_alias)]
    listings.append({
        "player_id": player_id,
        "player_name": str(p_obj.get("web_name", "Unknown")),
        "club": str(team_map.get(p_obj.get("team"), "PL")).upper(),
        "position": str(pos_map.get(p_obj.get("element_type", 1), "MID")),
        "manager_alias": mgr_alias,
        "team_name": team_name,
        "league_key": league_key,
        "notes": notes,
        "date": datetime.now().strftime("%d %b")
    })
    save_trade_block_file(listings)
    return {"status": "ok"}

@app.post("/api/trade_hub/remove")
async def remove_trade_hub_item(request: Request):
    body = await request.json()
    alias = str(body.get("alias", "")).strip()
    player_id = int(body.get("player_id", 0))
    listings = load_trade_block_file()
    listings = [t for t in listings if not (t.get("player_id") == player_id and (t.get("manager_alias", "").lower() == alias.lower() or alias.lower() == "admin"))]
    save_trade_block_file(listings)
    return {"status": "ok"}

# ==========================================
# 7. GACS (GOALS, ASSISTS & CLEAN SHEETS)
# ==========================================
@ttl_cache(180)
def compute_gacs_for_gw(league_id: int, gw_num: int):
    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(league_id)
    all_fixtures = cached_all_fixtures()
    entries = league_details.get("league_entries", []) if league_details else []

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}

    live_data = cached_live_event(gw_num)
    live_elements = live_data.get("elements", {}) if live_data else {}
    club_minutes = {}
    for elem_str_id, e_info in live_elements.items():
        try:
            c_id = element_lookup.get(int(elem_str_id), {}).get("team")
            if c_id:
                club_minutes[c_id] = club_minutes.get(c_id, 0) + safe_int(e_info.get("stats", {}).get("minutes", 0))
        except Exception:
            pass

    def eval_entry(e):
        alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        picks = cached_entry_event(e.get("entry_id"), gw_num)
        if not picks:
            return {"manager": alias, "goals": 0, "assists": 0, "cs": 0}
        s_recs, b_recs, _, _, _, _, _, _ = full_evaluate_lineup(picks, live_elements, element_lookup, club_minutes, pos_map, team_map, gw_num, all_fixtures)
        active_xi, _ = split_squad_records(s_recs, b_recs)
        g = sum(safe_int(p.get("G", 0)) for p in active_xi)
        a = sum(safe_int(p.get("A", 0)) for p in active_xi)
        cs = sum(safe_int(p.get("CS", 0)) for p in active_xi if p.get("Pos") in ["GKP", "DEF"])
        return {"manager": alias, "goals": g, "assists": a, "cs": cs}

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(eval_entry, entries))
    return sorted(rows, key=lambda x: x["manager"].lower())

@app.get("/api/gacs")
def get_gacs(league_id: int = 63, gw: str = "0"):
    league_details, _ = cached_league_data(league_id)
    current_gw, _ = detect_current_gw(league_details)
    gw_list = list(range(current_gw, 0, -1))

    if str(gw).lower() == "all":
        totals = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            gw_results = list(ex.map(lambda g: compute_gacs_for_gw(league_id, g), range(1, current_gw + 1)))
        for gw_rows in gw_results:
            for r in gw_rows:
                m = r["manager"]
                if m not in totals:
                    totals[m] = {"manager": m, "goals": 0, "assists": 0, "cs": 0}
                totals[m]["goals"] += r["goals"]
                totals[m]["assists"] += r["assists"]
                totals[m]["cs"] += r["cs"]
        rows = sorted(list(totals.values()), key=lambda x: x["manager"].lower())
        selected_val = "all"
    else:
        try:
            chosen_gw = int(gw) if int(gw) > 0 else current_gw
        except Exception:
            chosen_gw = current_gw
        rows = compute_gacs_for_gw(league_id, chosen_gw)
        selected_val = str(chosen_gw)

    return {"all_gws": gw_list, "selected": selected_val, "rows": rows}

# ==========================================
# 8. DISCIPLINARY
# ==========================================
@ttl_cache(180)
def compute_disciplinary_for_gw(league_id: int, gw_num: int):
    static_data = cached_fpl_static()
    league_details, _ = cached_league_data(league_id)
    entries = league_details.get("league_entries", []) if league_details else []
    matches = league_details.get("matches", []) if league_details else []

    pos_map = {item["id"]: item["singular_name_short"] for item in static_data["element_types"]}
    team_map = {item["id"]: item["short_name"] for item in static_data["teams"]}
    element_lookup = {item["id"]: item for item in static_data["elements"]}

    live_data = cached_live_event(gw_num)
    live_elements = live_data.get("elements", {}) if live_data else {}
    club_minutes = {}
    for elem_str_id, e_info in live_elements.items():
        try:
            c_id = element_lookup.get(int(elem_str_id), {}).get("team")
            if c_id:
                club_minutes[c_id] = club_minutes.get(c_id, 0) + safe_int(e_info.get("stats", {}).get("minutes", 0))
        except Exception:
            pass

    def eval_mgr_disc(e):
        l_id = e["id"]
        alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
        picks = cached_entry_event(e.get("entry_id"), gw_num)
        if not picks:
            return l_id, {"Manager": alias, "YC": 0, "RC": 0, "Pts_Lost": 0, "Score": 0}
        s_recs, b_recs, live_score, _, _, _, _, _ = full_evaluate_lineup(picks, live_elements, element_lookup, club_minutes, pos_map, team_map, gw_num, None)
        active_xi, _ = split_squad_records(s_recs, b_recs)
        yc = sum(safe_int(p.get("YC", 0)) for p in active_xi)
        rc = sum(safe_int(p.get("RC", 0)) for p in active_xi)
        pts_lost = (yc * 1) + (rc * 3)
        return l_id, {"Manager": alias, "YC": yc, "RC": rc, "Pts_Lost": pts_lost, "Score": live_score}

    with ThreadPoolExecutor(max_workers=8) as ex:
        mgr_data = dict(ex.map(eval_mgr_disc, entries))

    gw_matches = [m for m in matches if m.get("event") == gw_num]
    match_lookup = {}
    for m in gw_matches:
        t1, t2 = m.get("league_entry_1"), m.get("league_entry_2")
        is_fin = m.get("finished", False)
        s1 = safe_int(m.get("league_entry_1_points", mgr_data.get(t1, {}).get("Score", 0))) if is_fin else mgr_data.get(t1, {}).get("Score", 0)
        s2 = safe_int(m.get("league_entry_2_points", mgr_data.get(t2, {}).get("Score", 0))) if is_fin else mgr_data.get(t2, {}).get("Score", 0)
        match_lookup[t1] = (t2, s1, s2)
        match_lookup[t2] = (t1, s2, s1)

    rows = []
    for l_id, info in mgr_data.items():
        yc, rc, pts_lost = info["YC"], info["RC"], info["Pts_Lost"]
        m_info = match_lookup.get(l_id)
        if m_info:
            opp_id, my_s, opp_s = m_info
            opp_alias = mgr_data.get(opp_id, {}).get("Manager", "Opponent")
            act_res = "W" if my_s > opp_s else ("L" if my_s < opp_s else "D")
            no_card_s = my_s + pts_lost
            no_card_res = "W" if no_card_s > opp_s else ("L" if no_card_s < opp_s else "D")
            if pts_lost > 0 and act_res != no_card_res:
                pts_map = {"W": 3, "D": 1, "L": 0}
                cost_l_pts = pts_map[no_card_res] - pts_map[act_res]
                impact_str = f"Yes ({no_card_res} → {act_res}, -{cost_l_pts} pt{'s' if cost_l_pts > 1 else ''})"
                changed_flag = 1
            else:
                cost_l_pts = 0
                impact_str = "No"
                changed_flag = 0
            match_str = f"{act_res} ({my_s} - {opp_s} vs {opp_alias})"
        else:
            match_str, impact_str, changed_flag, cost_l_pts = "N/A", "No", 0, 0

        rows.append({
            "manager": info["Manager"],
            "yc": yc,
            "rc": rc,
            "card_pts": -pts_lost if pts_lost > 0 else 0,
            "matchup": match_str,
            "impact": impact_str,
            "changed_flag": changed_flag,
            "league_pts_cost": cost_l_pts
        })

    return sorted(rows, key=lambda x: x["manager"].lower())

@app.get("/api/disciplinary")
def get_disciplinary(league_id: int = 63, gw: str = "0"):
    league_details, _ = cached_league_data(league_id)
    current_gw, _ = detect_current_gw(league_details)
    gw_list = list(range(current_gw, 0, -1))

    if str(gw).lower() == "all":
        entries = league_details.get("league_entries", []) if league_details else []
        totals = {
            engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", "")): {
                "manager": engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", "")),
                "yc": 0, "rc": 0, "total_card_pts": 0, "results_changed": 0, "league_pts_cost": 0
            }
            for e in entries
        }
        swings_rows, pw_rows = [], []

        with ThreadPoolExecutor(max_workers=8) as ex:
            all_gw_data = list(ex.map(lambda g: (g, compute_disciplinary_for_gw(league_id, g)), range(1, current_gw + 1)))

        for g_num, g_rows in all_gw_data:
            for r in g_rows:
                m = r["manager"]
                if m in totals:
                    totals[m]["yc"] += r["yc"]
                    totals[m]["rc"] += r["rc"]
                    totals[m]["total_card_pts"] += r["card_pts"]
                    totals[m]["results_changed"] += r["changed_flag"]
                    totals[m]["league_pts_cost"] += r["league_pts_cost"]
                pw_rows.append({
                    "gw": f"GW {g_num}", "manager": m, "yc": r["yc"], "rc": r["rc"],
                    "card_pts": r["card_pts"], "matchup": r["matchup"], "impact": r["impact"]
                })
                if r["changed_flag"] > 0:
                    swings_rows.append({
                        "gw": f"GW {g_num}", "manager": m, "matchup": r["matchup"],
                        "yc": r["yc"], "rc": r["rc"], "card_pts": r["card_pts"], "impact": r["impact"]
                    })

        season_rows = sorted(list(totals.values()), key=lambda x: (x["total_card_pts"], -x["yc"]))
        return {
            "mode": "all",
            "all_gws": gw_list,
            "selected": "all",
            "season_rows": season_rows,
            "swings_rows": swings_rows,
            "pw_rows": pw_rows,
            "managers": sorted(list(totals.keys()))
        }
    else:
        try:
            chosen_gw = int(gw) if int(gw) > 0 else current_gw
        except Exception:
            chosen_gw = current_gw
        gw_rows = compute_disciplinary_for_gw(league_id, chosen_gw)
        return {
            "mode": "single",
            "all_gws": gw_list,
            "selected": str(chosen_gw),
            "gw_rows": gw_rows
        }

# ==========================================
# 9. NEWSLETTERS (PDF TO PNG RENDERER)
# ==========================================
def find_newsletter_pdf(doc_type: str):
    filename = "latest_cup.pdf" if doc_type == "cup" else "latest_league.pdf"
    candidates = [
        newsletters_folder / filename,
        base_dir / "Newsletters" / filename,
        base_dir / "newsletters" / filename,
        assets_folder / "Newsletters" / filename,
        assets_folder / filename,
        base_dir / filename
    ]
    return next((p for p in candidates if p.exists() and p.is_file()), None)

@app.get("/api/newsletters")
def get_newsletter_info(doc: str = "league"):
    pdf_path = find_newsletter_pdf(doc)
    if not pdf_path:
        return {"exists": False, "message": f"File '{'latest_cup.pdf' if doc == 'cup' else 'latest_league.pdf'}' not found in Newsletters or Assets folder."}
    if pdfium is None:
        return {"exists": False, "message": "pypdfium2 is not installed on the server."}
    try:
        pdf_doc = pdfium.PdfDocument(pdf_path)
        num_pages = len(pdf_doc)
        pages = [f"/api/newsletter_page/{doc}/{i}?t={int(pdf_path.stat().st_mtime)}" for i in range(num_pages)]
        return {"exists": True, "pages": pages}
    except Exception as e:
        return {"exists": False, "message": f"Error reading PDF: {str(e)}"}

@app.get("/api/newsletter_page/{doc}/{page_num}")
def get_newsletter_page_image(doc: str, page_num: int):
    pdf_path = find_newsletter_pdf(doc)
    if not pdf_path or pdfium is None:
        return Response(status_code=404)
    try:
        pdf_doc = pdfium.PdfDocument(pdf_path)
        page = pdf_doc[page_num]
        pil_img = page.render(scale=2).to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    except Exception:
        return Response(status_code=404)

# ==========================================
# 10. POWER RANKINGS
# ==========================================
def find_power_rankings_file():
    valid_exts = [".ods", ".xlsx", ".xls", ".csv"]
    for folder in [assets_folder, base_dir]:
        if folder.exists() and folder.is_dir():
            for f in folder.iterdir():
                if f.is_file() and f.suffix.lower() in valid_exts and "power" in f.name.lower():
                    return f
    return None

def format_df_clean(df):
    if df is None or df.empty:
        return [], []
    formatted = df.copy()
    for col in formatted.columns:
        def clean_cell(val):
            if pd.isna(val) or str(val).strip().lower() in ["nan", "none", ""]:
                return ""
            try:
                f_val = float(str(val).strip().replace(",", ""))
                if math.isnan(f_val) or math.isinf(f_val): return ""
                if f_val % 1 == 0:
                    return str(int(round(f_val)))
                return f"{f_val:.1f}"
            except Exception:
                return str(val)
        formatted[col] = [clean_cell(v) for v in formatted[col]]
    cols = [str(c).strip() for c in formatted.columns]
    rows = formatted.values.tolist()
    return cols, rows

@app.get("/api/power_rankings")
def get_power_rankings():
    target_file = find_power_rankings_file()
    if not target_file:
        return {"exists": False, "message": "No Power Rankings spreadsheet found. Place 'Power Rankings.ods', .xlsx or .csv in your Assets folder."}
    try:
        ext = target_file.suffix.lower()
        if ext == ".csv":
            sheets_dict = {target_file.stem: pd.read_csv(target_file)}
        elif ext == ".ods":
            sheets_dict = pd.read_excel(target_file, sheet_name=None, engine="odf")
        else:
            sheets_dict = pd.read_excel(target_file, sheet_name=None, engine="openpyxl")

        sheets_out = []
        for name, df in sheets_dict.items():
            if df is not None and not df.empty:
                cols, rows = format_df_clean(df)
                sheets_out.append({"name": str(name), "columns": cols, "rows": rows})
        return {"exists": True, "filename": target_file.name, "sheets": sheets_out}
    except Exception as e:
        return {"exists": False, "message": f"Error reading {target_file.name}: {str(e)}"}

@app.get("/api/power_rankings/download")
def download_power_rankings():
    target_file = find_power_rankings_file()
    if not target_file:
        return Response(status_code=404)
    return FileResponse(target_file, filename=target_file.name, media_type="application/octet-stream")

# ==========================================
# PUSH NOTIFICATIONS
# ==========================================
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
    if not (upstash_url and upstash_token):
        return {"error": "Database not configured"}
    headers = {"Authorization": f"Bearer {upstash_token}"}
    response = requests.get(f"{upstash_url}/get/latest_sub", headers=headers)
    data = response.json()
    if not data.get("result"):
        return {"error": "No device registered"}
    sub_data = json.loads(data["result"])
    payload = json.dumps({"title": "🚨 LIVE FROM THE CLOUD", "body": "Your permanent database is working!"})
    try:
        webpush(subscription_info=sub_data, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims=VAPID_CLAIMS)
        return {"status": "Push sent!"}
    except Exception as e:
        return {"error": str(e)}