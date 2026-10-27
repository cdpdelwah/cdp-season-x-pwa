import os
import math
import json
import requests
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pywebpush import webpush
from pathlib import Path
import engine

app = FastAPI()
base_dir = Path(__file__).resolve().parent

# THE COMMISSAR'S MASTER KEYRING (32 Managers)
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

# MANAGER DEFAULT LEAGUE ROUTING
MANAGER_LEAGUES = {
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

VAPID_PRIVATE_KEY = "SPXvvzkxVdsxWXj-8RfQXdBCxrcQdrgO3NNZXGvNP7Q"
VAPID_CLAIMS = {"sub": "mailto:commissar@cdp.com"}


def safe_int(val):
    try:
        if val is None or val == "":
            return 0
        return int(float(val))
    except Exception:
        return 0


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

    def get_avail_mult(raw_elem):
        status = str(raw_elem.get("status", "a")).lower()
        chance = raw_elem.get("chance_of_playing_next_round")
        if status in ["i", "s", "u"]:
            return 0.0
        if chance is not None:
            try:
                val = float(chance)
                if val >= 75: return 0.9
                if val >= 50: return 0.6
                if val >= 25: return 0.3
                return 0.0
            except Exception:
                pass
        return 0.6 if status == "d" else 1.0

    def get_fdr_mult(team_id):
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

        avail = get_avail_mult(raw_elem)
        form_val = float(raw_elem.get("form") or 0.0)
        ppg_val = float(raw_elem.get("points_per_game") or 2.0)
        base_exp = ((ppg_val * 0.6) + (form_val * 0.4)) * avail

        season_mins = float(raw_elem.get("minutes") or 0.0)
        if current_gw > 3 and (season_mins / max(1.0, float(current_gw * 60))) < 0.6:
            base_exp *= 0.8
        if base_exp <= 0 and avail > 0:
            base_exp = 2.0
        base_exp *= get_fdr_mult(club_id)

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

    # Optimum score calculation across all valid formations
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

    if g > 0:
        badges.append(f"{g}⚽" if g > 1 else "⚽")
    if a > 0:
        badges.append(f"{a}🎯" if a > 1 else "🎯")
    if cs > 0 and pos in ["GKP", "DEF", "MID"]:
        badges.append("🛡️")
    if bool(r.get("DEFCON_Achieved", False)):
        badges.append("🔰")
    if bonus > 0:
        badges.append(f"{bonus}⭐")
    if p_saved > 0:
        badges.append(f"{p_saved}🧤" if p_saved > 1 else "🧤")
    if p_missed > 0:
        badges.append(f"{p_missed}❌" if p_missed > 1 else "❌")
    return " ".join(badges)


def split_squad_records(s_recs, b_recs):
    active, inactive = [], []
    for r in s_recs:
        (inactive if str(r.get("sub_action", "")).strip() == "Subbed Off" else active).append(r)
    for r in b_recs:
        (active if str(r.get("sub_action", "")).strip() == "Subbed On" else inactive).append(r)
    inactive = sorted(inactive, key=lambda x: POS_ORDER.get(str(x.get("Pos", "")), 99))
    return active, inactive


def make_pitch_payload(active, inactive):
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
            c_num = safe_int(chance_val) if chance_val is not None else 50
            flag = "orange" if c_num <= 25 else "yellow"

        return {
            "name": str(r.get("Player", "Unknown")),
            "pos": str(r.get("Pos", "")),
            "club": club,
            "bg": pal["bg"],
            "text": pal["text"],
            "border": pal["border"],
            "fixture": str(r.get("Opp", "")),
            "pts": safe_int(r.get("Pts", 0)),
            "proj": f"{float(r.get('Proj', 0.0)):.1f}",
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
            "state": str(r.get("State", "FT")).upper(),
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

                if g > 0:
                    cats.append(f"{g}⚽" if g > 1 else "⚽")
                if a > 0:
                    cats.append(f"{a}🎯" if a > 1 else "🎯")
                if cs > 0 and pos in ["GKP", "DEF"]:
                    cats.append("🛡️")
                if bool(p.get("DEFCON_Achieved", False)):
                    cats.append("🔰")
                if bonus > 0:
                    cats.append(f"{bonus}⭐")

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


@app.get("/api/league_data")
def get_league_data():
    teams = engine.get_all_32_teams_registry()
    return {"status": "success", "manager_count": len(teams) if teams else 0, "data": teams}


@app.get("/api/live_scores")
def get_live_scores(league_id: int = 63, gw: str = "0"):
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

    static_data = engine.fetch_fpl_static()
    league_details, _ = engine.fetch_league_data(league_id)
    all_fixtures = engine.fetch_all_epl_fixtures()

    matches = league_details.get("matches", []) if league_details else []
    unplayed = sorted(list({m["event"] for m in matches if not m.get("finished", False)}))
    all_gws = sorted(list({m["event"] for m in matches})) if matches else list(range(1, 39))
    detected_gw = unplayed[0] if unplayed else (all_gws[-1] if all_gws else 1)

    current_gw = target_gw if target_gw > 0 else detected_gw
    gw_matches = [m for m in matches if m["event"] == current_gw]
    gw_fixtures = [f for f in all_fixtures if f.get("event") == current_gw] if all_fixtures else []

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
        except Exception:
            pass

    entries = league_details.get("league_entries", []) if league_details else []
    lentry_map = {e["id"]: e for e in entries}

    def process_match(m):
        e1 = lentry_map.get(m["league_entry_1"], {})
        e2 = lentry_map.get(m["league_entry_2"], {})
        a1 = engine.get_manager_alias(e1.get("player_first_name", ""), e1.get("player_last_name", ""))
        a2 = engine.get_manager_alias(e2.get("player_first_name", ""), e2.get("player_last_name", ""))
        is_fin = m.get("finished", False)

        p1 = engine.fetch_entry_event(e1.get("entry_id"), current_gw)
        p2 = engine.fetch_entry_event(e2.get("entry_id"), current_gw)

        s1_recs, b1_recs, t1_live, t1_proj, t1_inp, t1_ytp, t1_bp, t1_opt = full_evaluate_lineup(
            p1, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures
        )
        s2_recs, b2_recs, t2_live, t2_proj, t2_inp, t2_ytp, t2_bp, t2_opt = full_evaluate_lineup(
            p2, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures
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
        results = list(executor.map(process_match, gw_matches))

    return {"gw": current_gw, "detected_gw": detected_gw, "all_gws": all_gws, "matches": results}


@app.get("/api/match_spotlight")
def get_match_spotlight(m1: str, m2: str, gw: str = "1", league_id: int = 63):
    return {"status": "bundled_in_live_scores"}


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