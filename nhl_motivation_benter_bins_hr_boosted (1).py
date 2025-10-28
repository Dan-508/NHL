
# nhl_motivation_benter_bins_hr_boosted.py
# Regular-season only, require full 6 prior games, normalize team names.
# IMPORTANT: Motivation % DIFF = |Away% - (Home% + HomeBoost)| (boost INCLUDED).

import sys, time
from datetime import datetime
from collections import defaultdict, deque

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "lxml"])
    import requests
    from bs4 import BeautifulSoup

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (HR-backtest; +paste-and-run)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

START_END_YEAR = 2010
END_END_YEAR   = 2025
LOOKBACK = 6

def step1_points(consecutive_losses: int) -> int:
    if consecutive_losses <= 1: return 0
    if consecutive_losses == 2: return 5
    if consecutive_losses == 3: return 10
    if consecutive_losses == 4: return 5
    if consecutive_losses == 5: return -5
    return -10

def step2_points(one_goal_losses: int) -> int:
    if one_goal_losses <= 0: return 0
    if one_goal_losses == 1: return 5
    if one_goal_losses == 2: return 8
    return 10

def step3_points(opp_one_goal_wins: int) -> int:
    if opp_one_goal_wins <= 0: return 0
    if opp_one_goal_wins == 1: return 5
    if opp_one_goal_wins == 2: return 8
    return 10

def step4_points(team_losses_6: int) -> int:
    if team_losses_6 <= 2: return 0
    if team_losses_6 == 3: return 5
    if 4 <= team_losses_6 <= 5: return 10
    return 0

def step5_points(opp_losses_6: int) -> int:
    if opp_losses_6 == 0: return 2
    if 1 <= opp_losses_6 <= 2: return 0
    if 3 <= opp_losses_6 <= 4: return 3
    if opp_losses_6 == 5: return 8
    return 10 if opp_losses_6 >= 6 else 0

def home_boost(pct: float) -> float:
    if 70 <= pct <= 79: return 0.0
    if 60 <= pct <= 69: return 5.0
    if 50 <= pct <= 59: return 4.2
    if 40 <= pct <= 49: return 4.3
    if 30 <= pct <= 39: return 3.0
    if 20 <= pct <= 29: return 2.2
    if 10 <= pct <= 19: return 1.8
    if  0 <= pct <=   9: return 2.1
    return 0.0

NAME_MAP = {
    "Phoenix Coyotes": "Arizona Coyotes",
    "Montréal Canadiens": "Montreal Canadiens",
    "Mighty Ducks of Anaheim": "Anaheim Ducks",
    "Atlanta Thrashers": "Winnipeg Jets",
}
def norm_name(s: str) -> str:
    s = s.strip()
    return NAME_MAP.get(s, s)

def net_get(url, retries=3, sleep_s=0.6, timeout=30):
    last = None
    for _ in range(retries):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(sleep_s)
    raise last

def safe_text(el):
    return (el.get_text(strip=True) if el else "").strip()

def parse_int(x):
    try:
        return int(x)
    except:
        return None

def scrape_season_games_regular(end_year):
    url = f"https://www.hockey-reference.com/leagues/NHL_{end_year}_games.html"
    try:
        r = net_get(url)
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    games = []
    for tbl in soup.find_all("table"):
        tid = (tbl.get("id") or "").lower()
        if "playoffs" in tid:
            continue
        tbody = tbl.find("tbody")
        if not tbody:
            continue
        for tr in tbody.find_all("tr"):
            if tr.get("class") and "thead" in tr.get("class"):
                continue
            c_date = tr.find(["th","td"], attrs={"data-stat":"date_game"})
            c_vtm  = tr.find("td", attrs={"data-stat":"visitor_team_name"})
            c_vg   = tr.find("td", attrs={"data-stat":"visitor_goals"})
            c_htm  = tr.find("td", attrs={"data-stat":"home_team_name"})
            c_hg   = tr.find("td", attrs={"data-stat":"home_goals"})
            if not (c_date and c_vtm and c_vg and c_htm and c_hg):
                continue
            dstr = safe_text(c_date)
            vtm  = norm_name(safe_text(c_vtm).replace("*",""))
            htm  = norm_name(safe_text(c_htm).replace("*",""))
            vg   = parse_int(safe_text(c_vg))
            hg   = parse_int(safe_text(c_hg))
            if not dstr or vg is None or hg is None:
                continue
            try:
                d = datetime.strptime(dstr, "%Y-%m-%d").date()
            except:
                continue
            games.append({"date": d, "away": vtm, "home": htm, "away_goals": vg, "home_goals": hg})
    games.sort(key=lambda x: x["date"])
    return games

class TeamWindow:
    __slots__ = ("dq",)
    def __init__(self):
        self.dq = deque(maxlen=LOOKBACK)
    def add(self, res_char, diff):
        self.dq.append((res_char, diff))
    def snap(self):
        return list(self.dq)

def consecutive_losses(entries):
    c = 0
    for r, _ in reversed(entries):
        if r == "L": c += 1
        else: break
    return c

def one_goal_losses(entries):
    return sum(1 for r, d in entries if r == "L" and abs(d) == 1)

def one_goal_wins(entries):
    return sum(1 for r, d in entries if r == "W" and abs(d) == 1)

def losses(entries):
    return sum(1 for r, _ in entries if r == "L")

def motivation_pct(team_entries, opp_entries):
    s1 = step1_points(consecutive_losses(team_entries))
    s2 = step2_points(one_goal_losses(team_entries))
    s3 = step3_points(one_goal_wins(opp_entries))
    s4 = step4_points(losses(team_entries))
    s5 = step5_points(losses(opp_entries))
    return (s1 + s2 + s3 + s4 + s5) * 2.0

BINS = [(90,100),(80,89),(70,79),(60,69),(50,59),(40,49),(30,39),(20,29),(10,19),(0,9)]
def bin_key(p):
    if p is None: return None
    p = max(0.0, min(100.0, float(p)))
    for lo, hi in BINS:
        if lo <= p <= hi:
            return (lo, hi)
    return (0, 9)

def print_bins(header, totals, wins):
    print(header)
    for lo, hi in BINS:
        t = totals.get((lo,hi), 0)
        w = wins.get((lo,hi), 0)
        if t > 0:
            pct = round(100.0 * w / t, 2)
            print(f"{lo:02d}-{hi:02d}% : {pct}% ({w}/{t})")
        else:
            print(f"{lo:02d}-{hi:02d}% : N/A (0/0)")
    print("")

def run_backtest(start_end_year, end_end_year):
    windows = defaultdict(TeamWindow)
    level_totals = defaultdict(int)
    level_wins   = defaultdict(int)
    diff_totals  = defaultdict(int)
    diff_wins    = defaultdict(int)
    picks_made = 0
    wins_count = 0
    skipped_for_history = 0

    for end_year in range(start_end_year, end_end_year + 1):
        games = scrape_season_games_regular(end_year)
        if not games:
            continue
        for g in games:
            an = g["away"]; hn = g["home"]
            as_ = g["away_goals"]; hs = g["home_goals"]
            a_prev = windows[an].snap()
            h_prev = windows[hn].snap()

            if len(a_prev) < LOOKBACK or len(h_prev) < LOOKBACK:
                windows[hn].add("W" if hs > as_ else "L", hs - as_)
                windows[an].add("W" if as_ > hs else "L", as_ - hs)
                skipped_for_history += 1
                continue

            a_pct = motivation_pct(a_prev, h_prev)
            b_pct = motivation_pct(h_prev, a_prev)
            b_pct_final = b_pct + home_boost(b_pct)   # BOOST INCLUDED
            if a_pct == b_pct_final:
                windows[hn].add("W" if hs > as_ else "L", hs - as_)
                windows[an].add("W" if as_ > hs else "L", as_ - hs)
                continue

            pick = an if a_pct > b_pct_final else hn
            pick_pct = a_pct if pick == an else b_pct_final
            diff_pct = abs(a_pct - b_pct_final)       # DIFF uses boosted HOME

            actual = hn if hs > as_ else an
            picks_made += 1
            if pick == actual:
                wins_count += 1

            lb = bin_key(pick_pct)
            if lb:
                level_totals[lb] += 1
                if pick == actual:
                    level_wins[lb] += 1
            db = bin_key(diff_pct)
            if db:
                diff_totals[db] += 1
                if pick == actual:
                    diff_wins[db] += 1

            windows[hn].add("W" if hs > as_ else "L", hs - as_)
            windows[an].add("W" if as_ > hs else "L", as_ - hs)

    print("Motivation Level Bins (picked team) — descending: (Home boost not applied here)")
    print_bins("", level_totals, level_wins)
    print("Motivation Difference Bins — descending: (DIFF uses boosted HOME: |Away% - (Home% + Boost)|)")
    print_bins("", diff_totals, diff_wins)
    if picks_made > 0:
        acc = round(100.0 * wins_count / picks_made, 2)
        print(f"Overall Accuracy: {acc}% ({wins_count}/{picks_made})")
    else:
        print("Overall Accuracy: N/A (0 picks)")
    print(f"Matchups skipped (insufficient 6-game history): {skipped_for_history}")

if __name__ == "__main__":
    run_backtest(START_END_YEAR, END_END_YEAR)
