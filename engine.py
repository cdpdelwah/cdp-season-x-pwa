import requests
import pandas as pd
import math
import json
import re
import functools
from pathlib import Path

base_dir = Path(__file__).resolve().parent

# ==========================================
# 1. DICTIONARIES & REGISTRIES
# ==========================================

LEAGUE_PRESETS = {
    "CDP (Crème Dellar Prem)": 63,
    "SDM (Segundo Del Mundo)": 320,
    "BDR (Best De La Rest)": 378,
    "LDE (Liger Del Eager)": 240
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

MANAGER_ALIASES = {
    "Nick Middleton": "Nick", "greg probert": "Greg", "Greg Probert": "Greg",
    "Thomas Foy": "Foy", "Kennedy .": "James", "Kennedy": "James",
    "Andy Dellar": "Andy", "Jimmy Dean": "Jimmy", "Hughben Amorim": "Hugh",
    "Hughben": "Hugh", "Hugh": "Hugh", "Phil Wass": "Phil", "Bungle .": "Bungle",
    "Bungle.": "Bungle", "Bungle": "Bungle", "Gareth Williams": "Garth",
    "Joshua Stammers": "Josh", "Stew Hall": "Stew", "Sam Berry": "Sam",
    "Ali W": "Ali", "Crouch Chris Smith": "Crouch", "Dave Whitcombe": "Dave",
    "Duncan Harrison": "Duncan", "Barney Jones": "Barney", "Rob Carlisle": "Rob",
    "Rackett .": "Rackett", "Rackett.": "Rackett", "Rackett": "Rackett",
    "Mike Wilson": "Wilson", "Culley Will": "Culley", "Bobby Cowsill": "Bobby",
    "Tudor .": "Tudor", "Tudor.": "Tudor", "Tudor": "Tudor", "Adrian Baker": "Adi",
    "Lee Colvin": "Lee", "Jamie Fielding": "Jamie", "Tom Probert": "Tom",
    "Ben Marsden": "Ben", "Will Graham": "Will", "Niall Hession": "Niall",
    "Peter Thompson": "Pete", "Pete Thompson": "Pete", "Peter": "Pete", "Pete": "Pete"
}

POS_ORDER = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}

def get_manager_alias(first_name, last_name):
    fn = str(first_name).strip() if first_name else ""
    ln = str(last_name).strip() if last_name else ""
    full_name = f"{fn} {ln}".strip()
    if full_name in MANAGER_ALIASES: return MANAGER_ALIASES[full_name]
    clean_full = full_name.replace(".", "").strip().lower()
    for key, alias in MANAGER_ALIASES.items():
        if key.replace(".", "").strip().lower() == clean_full: return alias
    for key, alias in MANAGER_ALIASES.items():
        if fn.lower() == key.lower() or ln.lower() == key.lower(): return alias
    return fn if fn else full_name

# ==========================================
# 2. FPL DATA FETCHERS (NO CACHING HERE)
# ==========================================

def fetch_fpl_static():
    url = "https://draft.premierleague.com/api/bootstrap-static"
    resp = requests.get(url)
    return resp.json() if resp.status_code == 200 else None

def fetch_league_data(league_id):
    if not league_id: return None, None
    det_resp = requests.get(f"https://draft.premierleague.com/api/league/{league_id}/details")
    stat_resp = requests.get(f"https://draft.premierleague.com/api/league/{league_id}/element-status")
    if det_resp.status_code != 200 or stat_resp.status_code != 200: return None, None
    return det_resp.json(), stat_resp.json()

def get_all_32_teams_registry():
    registry = {}
    for l_key, l_id in LEAGUE_PRESETS.items():
        details, _ = fetch_league_data(l_id)
        if details:
            for e in details.get("league_entries", []):
                alias = get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
                info = {
                    "entry_id": e.get("entry_id"), "league_entry_id": e.get("id"),
                    "league_id": l_id, "league_key": l_key,
                    "team_name": e.get("entry_name", "Team"),
                    "manager_name": f"{e.get('player_first_name', '')} {e.get('player_last_name', '')}".strip(),
                    "alias": alias
                }
                registry[alias.lower()] = info
                registry[e.get("entry_name", "").strip().lower()] = info
    return registry

def fetch_entry_event(entry_id, event):
    resp = requests.get(f"https://draft.premierleague.com/api/entry/{entry_id}/event/{event}")
    return resp.json() if resp.status_code == 200 else None

def fetch_live_event(event):
    resp = requests.get(f"https://draft.premierleague.com/api/event/{event}/live")
    return resp.json() if resp.status_code == 200 else None

def fetch_epl_fixtures(event):
    resp = requests.get(f"https://fantasy.premierleague.com/api/fixtures/?event={event}")
    return resp.json() if resp.status_code == 200 else []

def fetch_all_epl_fixtures():
    resp = requests.get("https://fantasy.premierleague.com/api/fixtures/")
    return resp.json() if resp.status_code == 200 else []

# ==========================================
# 3. EXTERNAL MATCH SCRAPERS (PULSE / ESPN)
# ==========================================
PULSE_HEADERS = {
    "Origin": "https://www.premierleague.com", "Referer": "https://www.premierleague.com/",
    "User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*", "account": "premierleague"
}
CLUB_SEARCH_KEYWORDS = {
    "ARS": "arsenal", "AVL": "aston villa", "BHA": "brighton", "BOU": "bournemouth",
    "BRE": "brentford", "CHE": "chelsea", "CRY": "crystal palace", "EVE": "everton",
    "FUL": "fulham", "IPS": "ipswich", "LEE": "leeds", "LEI": "leicester",
    "LIV": "liverpool", "MCI": "manchester city", "MUN": "manchester united",
    "NEW": "newcastle", "NFO": "nottingham", "SOU": "southampton", "SUN": "sunderland",
    "TOT": "tottenham", "WHU": "west ham", "WOL": "wolverhampton"
}

def _team_matches_code(short_code, team_obj):
    if not short_code or not isinstance(team_obj, dict): return False
    kw = CLUB_SEARCH_KEYWORDS.get(str(short_code).strip().upper(), str(short_code).strip().lower())
    club_obj = team_obj.get("club", {}) if isinstance(team_obj.get("club"), dict) else {}
    abbr = str(club_obj.get("abbr") or team_obj.get("abbreviation") or "").strip().upper()
    if abbr and abbr == str(short_code).strip().upper(): return True
    names = " ".join([str(team_obj.get(k) or "") for k in ["name", "shortName"]] + [str(club_obj.get(k) or "") for k in ["name", "shortName"]]).lower()
    return kw in names

def get_pulse_active_season_id():
    try:
        r = requests.get("https://footballapi.pulselive.com/football/competitions/1/compseasons?page=0&pageSize=100", headers=PULSE_HEADERS, timeout=4)
        if r.status_code == 200:
            for s in r.json().get("content", []):
                if "2026/27" in str(s.get("label", "")): return int(float(s.get("id")))
    except: pass
    return None

def get_pulse_active_fixtures_list(event_num = None):
    s_id = get_pulse_active_season_id()
    s_param = f"&compSeasons={s_id}" if s_id else ""
    gw_page = max(0, (int(event_num) - 1) // 4) if event_num else 1
    urls = [
        f"https://footballapi.pulselive.com/football/fixtures?comps=1{s_param}&statuses=U,L&sort=asc&page=0&pageSize=40",
        f"https://footballapi.pulselive.com/football/fixtures?comps=1{s_param}&sort=asc&page={gw_page}&pageSize=40"
    ]
    all_fixes, seen = [], set()
    for u in urls:
        try:
            r = requests.get(u, headers=PULSE_HEADERS, timeout=4)
            if r.status_code == 200:
                for fix in r.json().get("content", []):
                    if fix.get("id") and fix.get("id") not in seen:
                        seen.add(fix.get("id"))
                        all_fixes.append(fix)
        except: continue
    return all_fixes

def get_pulse_fixture_id(home_short, away_short, event_num = None):
    fixes = get_pulse_active_fixtures_list(event_num)
    for fix in fixes:
        teams = fix.get("teams", [])
        if len(teams) == 2 and _team_matches_code(home_short, teams[0].get("team", {})) and _team_matches_code(away_short, teams[1].get("team", {})):
            return int(float(fix.get("id")))
    return None

def fetch_pulse_fixture_details(pulse_id):
    try:
        r = requests.get(f"https://footballapi.pulselive.com/football/fixtures/{pulse_id}", headers=PULSE_HEADERS, timeout=5)
        return r.json() if r.status_code == 200 else None
    except: return None

def _fetch_espn_lineup_backup(home_short, away_short):
    return None # Condensed for pure API processing (we default to PulseLive and Live FPL feeds for the headless backend)

def fetch_premier_league_match_lineup(fpl_fixture_code, home_team_id=None, away_team_id=None, live_elements=None, element_lookup=None, match_minute=90, event_num=None, home_short=None, away_short=None, kickoff_time=None, is_started=False, is_finished=False):
    is_within_window = is_started or is_finished
    if kickoff_time and not is_within_window:
        ko_dt = pd.to_datetime(kickoff_time)
        now_dt = pd.Timestamp.now(tz=ko_dt.tz) if ko_dt.tz else pd.Timestamp.utcnow()
        if (ko_dt - now_dt).total_seconds() <= 5400: is_within_window = True
    elif not kickoff_time: is_within_window = True

    if not is_within_window: return {"has_lineups": False}

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
                    s, u, un = [], [], []
                    pos_order_map = {"GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}
                    for p in sheet.get("lineup", []):
                        pid, raw_pos = p.get("id"), str(p.get("matchPosition", "MID")).upper()
                        clean_pos = "GKP" if "G" in raw_pos else ("DEF" if "D" in raw_pos else ("FWD" if "F" in raw_pos else "MID"))
                        num = f"#{p.get('matchShirtNumber') or p.get('shirtNum')} " if p.get('matchShirtNumber') or p.get('shirtNum') else ""
                        name, capt = p.get("name", {}).get("display", "Unknown"), " (C)" if p.get("captain") else ""
                        sub_tag = f" ▼ {sub_events[pid][1]}" if pid in sub_events and sub_events[pid][0] == "OFF" else ""
                        s.append({"rank": pos_order_map.get(clean_pos, 3), "text": f"{num}**{name}**{capt} • *{clean_pos}*{sub_tag}"})
                    for p in sheet.get("substitutes", []):
                        pid, name = p.get("id"), p.get("name", {}).get("display", "Unknown")
                        num = f"#{p.get('matchShirtNumber') or p.get('shirtNum')} " if p.get('matchShirtNumber') or p.get('shirtNum') else ""
                        if pid in sub_events and sub_events[pid][0] == "ON": u.append(f"{num}**{name}** ▲ {sub_events[pid][1]}")
                        else: un.append(f"{num}{name}")
                    return [x["text"] for x in sorted(s, key=lambda x: x["rank"])], u, un

                h_s, h_u, h_un = format_official_sheet(h_sheet)
                a_s, a_u, a_un = format_official_sheet(a_sheet)
                return {"has_lineups": True, "home_starters": h_s, "home_subs_used": h_u, "home_subs_unused": h_un, "away_starters": a_s, "away_subs_used": a_u, "away_subs_unused": a_un}

    return {"has_lineups": False}

# ==========================================
# 4. PLAYER & SQUAD LOGIC
# ==========================================

def get_availability_multiplier(row):
    status, chance = row.get("status", "a"), row.get("chance_of_playing_next_round")
    if status in ["i", "s", "u"]: return 0.0
    if pd.notna(chance):
        val = float(chance)
        if val >= 75: return 0.9
        if val >= 50: return 0.6
        if val >= 25: return 0.3
        return 0.0
    if status == "d": return 0.6
    return 1.0

def get_fdr_multiplier(team_id, current_gw, all_fixtures_list):
    if not all_fixtures_list or not team_id: return 1.0
    fixes = [f for f in all_fixtures_list if f.get("event") == current_gw and (f.get("team_h") == team_id or f.get("team_a") == team_id)]
    if not fixes: return 0.0
    total = 0.0
    for fix in fixes:
        diff = fix.get("team_h_difficulty", 3) if fix.get("team_h") == team_id else fix.get("team_a_difficulty", 3)
        total += 1.10 if diff <= 2 else (1.00 if diff == 3 else (0.92 if diff == 4 else 0.85))
    return total

def extract_defcon_achieved_flag(elem_stats, elem_explain, pos_type):
    if not isinstance(elem_stats, dict): return False
    dc = elem_stats.get("defensive_contributions", 0) or elem_stats.get("defcon", 0) or elem_stats.get("cbit", 0)
    calc_val = dc if dc > 0 else (elem_stats.get("cbi", 0) + elem_stats.get("tackles", 0) + (elem_stats.get("recoveries", 0) if pos_type in [3, 4] else 0))
    explain_val = max([s.get("value", 0) for sublist in [i.get("stats", [i]) if isinstance(i, dict) else i for i in (elem_explain if isinstance(elem_explain, list) else [])] for s in sublist if isinstance(s, dict) and s.get("identifier", "").lower() in ["defensive_contributions", "defcon", "cbit", "cbi"]], default=0)
    return max(calc_val, explain_val) >= (10 if pos_type == 2 else 12) if pos_type in [2, 3, 4] else False

def evaluate_lineup(picks_list, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures_list=None):
    if not picks_list: return pd.DataFrame(), pd.DataFrame(), 0, 0.0, 0, 0, 0, 0
    raw_players = []
    for p in picks_list.get("picks", []):
        elem_id = p["element"]
        raw_elem = element_lookup.get(elem_id, {})
        e_data = live_elements.get(str(elem_id), {})
        stats = e_data.get("stats", {}) if isinstance(e_data, dict) else {}
        pos_type = raw_elem.get("element_type", 1)
        club_id = raw_elem.get("team")
        
        team_mins = club_minutes.get(club_id, 0)
        mins, pts = stats.get("minutes", 0), stats.get("total_points", 0)
        avail = get_availability_multiplier(raw_elem)
        base_exp = (((float(raw_elem.get("points_per_game") or 2.0) * 0.6) + (float(raw_elem.get("form") or 0.0) * 0.4)) * avail) * get_fdr_multiplier(club_id, current_gw, all_fixtures_list)
        
        if team_mins >= 800:
            state, proj = ("FT", float(pts)) if mins > 0 else ("DNP", 0.0)
        elif team_mins > 0:
            state, match_min = "LIVE", 45
            for fix in (all_fixtures_list or []):
                if fix.get("event") == current_gw and (fix.get("team_h") == club_id or fix.get("team_a") == club_id) and fix.get("started"):
                    match_min = fix.get("minutes", 45)
            rem = max(0.0, (90.0 - float(match_min)) / 90.0)
            proj = round(float(pts) + (1.0 if match_min < 60 else 0.0) + (max(0.0, base_exp - 2.0) * rem), 1) if mins > 0 else round(base_exp * 0.25 * rem, 1)
        else:
            state, proj = "YTP", round(base_exp, 1)

        raw_players.append({
            "id": elem_id, "Player": raw_elem.get("web_name", "Unknown"), "pos_num": pos_type,
            "Pos": pos_map.get(pos_type, ""), "club_id": club_id, "State": state,
            "Mins": mins, "Pts": pts, "Proj": proj, "DEFCON_Achieved": extract_defcon_achieved_flag(stats, e_data.get("explain", []), pos_type),
            "pick_pos": p.get("position", 99), "is_starter": p.get("position", 99) <= 11, "sub_action": ""
        })
        
    starters = [r for r in raw_players if r["is_starter"]]
    bench = sorted([r for r in raw_players if not r["is_starter"]], key=lambda x: x["pick_pos"])
    used_bench = set()

    gk_start = next((s for s in starters if s["Pos"] == "GKP"), None)
    if gk_start and gk_start["State"] == "DNP":
        gk_sub = next((b for b in bench if b["Pos"] == "GKP" and b["State"] != "DNP"), None)
        if gk_sub: gk_start["sub_action"], gk_sub["sub_action"] = "Subbed Off", "Subbed On"; used_bench.add(gk_sub["id"])
            
    for dnp in [s for s in starters if s["Pos"] != "GKP" and s["State"] == "DNP"]:
        for b in [b for b in bench if b["Pos"] != "GKP" and b["id"] not in used_bench and b["State"] != "DNP"]:
            cur = [s["Pos"] for s in starters if s["sub_action"] != "Subbed Off" and s["id"] != dnp["id"]] + [b["Pos"]]
            if cur.count("DEF") >= 3 and cur.count("MID") >= 2 and cur.count("FWD") >= 1:
                dnp["sub_action"], b["sub_action"] = "Subbed Off", "Subbed On"; used_bench.add(b["id"]); break

    active = [s for s in starters if s["sub_action"] != "Subbed Off"] + [b for b in bench if b["sub_action"] == "Subbed On"]
    live_score, proj_score = sum(int(p["Pts"]) for p in active), sum(float(p["Proj"]) for p in active)
    in_p, ytp = sum(1 for p in active if p["State"] == "LIVE"), sum(1 for p in active if p["State"] == "YTP")
    b_pts = sum(int(b["Pts"]) for b in bench if b["sub_action"] != "Subbed On")

    return pd.DataFrame(starters), pd.DataFrame(bench), live_score, round(proj_score, 1), in_p, ytp, b_pts, 0

# ==========================================
# 5. TOURNAMENT LOGIC
# ==========================================

def load_cup_matches():
    for f in [base_dir / "Assets" / "cupmatches.csv", base_dir / "assets" / "cupmatches.csv"]:
        if f.exists(): return pd.read_csv(f)
    return pd.DataFrame()

def calculate_group_standings():
    cup_df = load_cup_matches()
    if cup_df.empty: return []
    group_matches = cup_df[(cup_df["Week"] <= 20) & (cup_df["Stage"].str.lower().str.contains("group"))].copy()
    
    unique_aliases = set()
    for _, r in group_matches.iterrows():
        if str(r.get("Team 1", "")).strip().lower() != "nan": unique_aliases.add(str(r["Team 1"]).strip())
        if str(r.get("Team 2", "")).strip().lower() != "nan": unique_aliases.add(str(r["Team 2"]).strip())
        
    standings = {m: {"Manager": m, "W": 0, "D": 0, "L": 0, "PF": 0, "Pts": 0, "H2H": {}} for m in unique_aliases}
    # Logic is condensed for API return. Actual processing hooks up here via evaluate_lineup loop over events.
    return list(standings.values())