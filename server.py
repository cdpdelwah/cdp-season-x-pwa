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
        if val is None:
            return 0
        return int(float(val))
    except Exception:
        return 0


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


def split_squad_records(start_df, bench_df):
    s_recs = []
    b_recs = []
    if start_df is not None and not getattr(start_df, "empty", True):
        for _, row in start_df.iterrows():
            s_recs.append(dict(row))
    if bench_df is not None and not getattr(bench_df, "empty", True):
        for _, row in bench_df.iterrows():
            b_recs.append(dict(row))

    active = []
    inactive = []
    for r in s_recs:
        if str(r.get("sub_action", "")).strip() == "Subbed Off":
            inactive.append(r)
        else:
            active.append(r)
    for r in b_recs:
        if str(r.get("sub_action", "")).strip() == "Subbed On":
            active.append(r)
        else:
            inactive.append(r)

    inactive = sorted(inactive, key=lambda x: POS_ORDER.get(str(x.get("Pos", "")), 99))
    return active, inactive, s_recs, b_recs


def make_pitch_payload(active, inactive):
    rows = [[], [], [], []]
    subs = []

    def format_player_token(r):
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
            "state": str(r.get("State", "FT")).upper(),
            "sub_action": str(r.get("sub_action", "")).strip(),
            "flag": flag,
            "events": build_badges(r)
        }

    for r in active:
        p_dict = format_player_token(r)
        if p_dict["pos"] == "GKP":
            rows[0].append(p_dict)
        elif p_dict["pos"] == "DEF":
            rows[1].append(p_dict)
        elif p_dict["pos"] == "MID":
            rows[2].append(p_dict)
        elif p_dict["pos"] == "FWD":
            rows[3].append(p_dict)

    for r in inactive:
        subs.append(format_player_token(r))

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
                if bonus > 0:
                    cats.append(f"{bonus}⭐")

                if cats:
                    entries_list.append(f"{p_name} ({' '.join(cats)})")
        return ", ".join(entries_list) if entries_list else "None"

    labels, m1_data, m1_pts, m1_ev, m2_data, m2_pts, m2_ev = [], [], [], [], [], [], []
    fixtures_list = []
    c1, c2 = 0, 0

    for f in gw_fixtures:
        h_id = f.get("team_h")
        a_id = f.get("team_a")
        m_label = f"{team_map.get(h_id, 'H')} v {team_map.get(a_id, 'A')}"
        labels.append(m_label)

        fp1 = sum(safe_int(p.get("Pts", 0)) for p in t1_act if safe_int(p.get("club_id")) in (safe_int(h_id), safe_int(a_id)))
        fp2 = sum(safe_int(p.get("Pts", 0)) for p in t2_act if safe_int(p.get("club_id")) in (safe_int(h_id), safe_int(a_id)))
        c1 += fp1
        c2 += fp2

        ev1 = get_fixture_contributors(t1_act, h_id, a_id)
        ev2 = get_fixture_contributors(t2_act, h_id, a_id)

        m1_data.append(c1)
        m1_pts.append(fp1)
        m1_ev.append(ev1)
        m2_data.append(c2)
        m2_pts.append(fp2)
        m2_ev.append(ev2)

        fixtures_list.append({
            "match": m_label,
            "m1": {"manager": str(a1), "pts": c1, "added": f"+{fp1}", "events": ev1, "color": "#f59e0b"},
            "m2": {"manager": str(a2), "pts": c2, "added": f"+{fp2}", "events": ev2, "color": "#38bdf8"}
        })

    return {
        "labels": labels,
        "m1_data": m1_data,
        "m1_match_pts": m1_pts,
        "m1_events": m1_ev,
        "m2_data": m2_data,
        "m2_match_pts": m2_pts,
        "m2_events": m2_ev,
        "fixtures": fixtures_list
    }


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

        t1_start, t1_bench, t1_live, t1_proj, t1_inp, t1_ytp, t1_bp, t1_opt = engine.evaluate_lineup(
            p1, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures
        )
        t2_start, t2_bench, t2_live, t2_proj, t2_inp, t2_ytp, t2_bp, t2_opt = engine.evaluate_lineup(
            p2, live_elements, element_lookup, club_minutes, pos_map, team_map, current_gw, all_fixtures
        )

        t1_score = m.get("league_entry_1_points", t1_live) if is_fin else t1_live
        t2_score = m.get("league_entry_2_points", t2_live) if is_fin else t2_live
        prob1, prob2 = calc_win_prob(t1_score, t1_proj, t1_inp + t1_ytp, t2_score, t2_proj, t2_inp + t2_ytp, is_fin)

        def fmt_rem(i, y):
            if i > 0 and y > 0:
                return f"{i} in play, {y} yet to play"
            return f"{i} in play" if i > 0 else (f"{y} yet to play" if y > 0 else "0 to play")

        t1_act, t1_inact, s1_recs, b1_recs = split_squad_records(t1_start, t1_bench)
        t2_act, t2_inact, s2_recs, b2_recs = split_squad_records(t2_start, t2_bench)

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
    try:
        target_gw = int(gw)
    except Exception:
        target_gw = 1

    static_data = engine.fetch_fpl_static()
    all_fixtures = engine.fetch_all_epl_fixtures()

    e1_id, e2_id = None, None
    search_leagues = [league_id] + [lid for lid in [63, 320, 378, 240] if lid != league_id]
    for lid in search_leagues:
        ld, _ = engine.fetch_league_data(lid)
        if ld:
            for e in ld.get("league_entries", []):
                alias = engine.get_manager_alias(e.get("player_first_name", ""), e.get("player_last_name", ""))
                if alias.strip().lower() == m1.strip().lower():
                    e1_id = e.get("entry_id")
                if alias.strip().lower() == m2.strip().lower():
                    e2_id = e.get("entry_id")
        if e1_id and e2_id:
            break

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
        except Exception:
            pass

    p1 = engine.fetch_entry_event(e1_id, target_gw) if e1_id else None
    p2 = engine.fetch_entry_event(e2_id, target_gw) if e2_id else None

    t1_start, t1_bench, t1_live, _, _, _, t1_bp, t1_opt = engine.evaluate_lineup(
        p1, live_elements, element_lookup, club_minutes, pos_map, team_map, target_gw, all_fixtures
    )
    t2_start, t2_bench, t2_live, _, _, _, t2_bp, t2_opt = engine.evaluate_lineup(
        p2, live_elements, element_lookup, club_minutes, pos_map, team_map, target_gw, all_fixtures
    )

    t1_act, t1_inact, s1_recs, b1_recs = split_squad_records(t1_start, t1_bench)
    t2_act, t2_inact, s2_recs, b2_recs = split_squad_records(t2_start, t2_bench)
    gw_fixtures = [f for f in all_fixtures if f.get("event") == target_gw] if all_fixtures else []

    return {
        "m1_meta": {"score": safe_int(t1_live), "bench": safe_int(t1_bp), "opt": safe_int(t1_opt)},
        "m2_meta": {"score": safe_int(t2_live), "bench": safe_int(t2_bp), "opt": safe_int(t2_opt)},
        "progression": make_progression_payload(m1, m2, t1_act, t2_act, gw_fixtures, team_map),
        "pitch_m1": make_pitch_payload(t1_act, t1_inact),
        "pitch_m2": make_pitch_payload(t2_act, t2_inact),
        "table_m1": make_table_payload(s1_recs, b1_recs),
        "table_m2": make_table_payload(s2_recs, b2_recs)
    }


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