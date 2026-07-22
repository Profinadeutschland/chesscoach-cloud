#!/usr/bin/env python3
"""
ErtuCoach Cloud – nächtliche Stockfish-Analyse (GitHub Actions).

v2: zusätzlich zur Partie-Zusammenfassung (ACPL, Blunder …) findet das Skript
pro Partie die 1–2 WENDEPUNKTE (größte Eval-Umschwünge), analysiert genau diese
Stellungen extra tief (DEEP_DEPTH, MultiPV) und klassifiziert das taktische
Motiv menschlich (Springergabel, hängende Figur, Grundreihenmatt, Abzug, …),
damit die Live-Seite erklären kann, WOMIT sich die Partie hätte drehen lassen.

Env:
  MAX_GAMES    max. Partien pro Lauf (Default 150)
  DEPTH        Tiefe für die Eval-Kurve (Default 12)
  DEEP_DEPTH   Tiefe für Wendepunkt-Stellungen (Default 20)
  STOCKFISH    Pfad zur Binary (Default "stockfish")
"""
from __future__ import annotations
import io, json, os, sys, time
from datetime import datetime, timezone

import requests
import chess
import chess.engine
import chess.pgn

USER = "airt007"
START_TS = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp())
DATA = os.path.join(os.path.dirname(__file__), "..", "data", "engine.json")
UA = {"User-Agent": "ertucoach-cloud/2.0 (contact: erti.jieez@gmail.com)"}
MAX_GAMES = int(os.environ.get("MAX_GAMES", "150"))
DEPTH = int(os.environ.get("DEPTH", "12"))
DEEP_DEPTH = int(os.environ.get("DEEP_DEPTH", "20"))
MATE_SCORE = 1000

V = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900}


def phase_of(ply: int, board: chess.Board) -> str:
    if ply <= 16:
        return "o"
    np = sum(V[p.piece_type] for p in board.piece_map().values()
             if p.piece_type not in (chess.PAWN, chess.KING))
    return "e" if np <= 1300 else "m"


def load_data() -> dict:
    try:
        with open(DATA) as f:
            d = json.load(f)
            if isinstance(d.get("games"), dict):
                return d
    except Exception:
        pass
    return {"updated": None, "games": {}}


def save_data(d: dict) -> None:
    d["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))


def fetch_new(done: set) -> list:
    archives = requests.get(
        f"https://api.chess.com/pub/player/{USER}/games/archives", headers=UA, timeout=30
    ).json()["archives"]
    out = []
    for url in archives:
        y, m = url.rstrip("/").split("/")[-2:]
        if int(y) * 12 + int(m) < 2026 * 12 + 4:
            continue
        games = requests.get(url, headers=UA, timeout=60).json().get("games", [])
        for g in games:
            gid = g.get("url", "").split("/")[-1]
            if (g.get("rules") == "chess" and g.get("end_time", 0) >= START_TS
                    and gid and gid not in done):
                out.append(g)
        time.sleep(0.6)
    out.sort(key=lambda g: g["end_time"])
    return out


# ---------------------------------------------------------------- Motive
def is_defended(board: chess.Board, sq: int, by: chess.Color) -> bool:
    return bool(board.attackers(by, sq))


def classify_motif(board: chess.Board, move: chess.Move, pv: list,
                   mate_in: int | None, pov: chess.Color) -> str:
    """Menschliches Motiv des BESTEN Zugs `move` in `board` (pov am Zug)."""
    opp = not pov
    # Matt-Motive
    if mate_in is not None and mate_in > 0:
        b2 = board.copy()
        for mv in pv[:mate_in * 2 - 1]:
            if not b2.is_legal(mv):
                break
            b2.push(mv)
        ksq = b2.king(opp)
        if b2.is_checkmate() and ksq is not None:
            krank = chess.square_rank(ksq)
            if (opp == chess.WHITE and krank == 0) or (opp == chess.BLACK and krank == 7):
                return "grundreihe"
        return "matt"
    if move.promotion:
        return "umwandlung"
    b2 = board.copy()
    captured = board.piece_at(move.to_square)
    b2.push(move)
    # Abzugsschach: Schach, aber nicht (nur) durch die gezogene Figur
    if b2.is_check():
        checkers = b2.checkers()
        if any(sq != move.to_square for sq in checkers):
            return "abzug"
    # Freies Material schlagen
    if captured and captured.piece_type != chess.PAWN:
        if not is_defended(b2, move.to_square, opp):
            return "haengend"
        if board.is_pinned(opp, move.to_square):
            return "fesselung"
        mover = board.piece_at(move.from_square)
        if mover and V.get(captured.piece_type, 0) > V.get(mover.piece_type, 0):
            return "guenstiger_abtausch"
    # Gabel / Doppelangriff: gezogene Figur greift >= 2 wertvolle Ziele an
    mover_p = b2.piece_at(move.to_square)
    if mover_p:
        targets = 0
        for sq in b2.attacks(move.to_square):
            p = b2.piece_at(sq)
            if p and p.color == opp and (p.piece_type == chess.KING or V.get(p.piece_type, 0) >= 300):
                if p.piece_type == chess.KING or not is_defended(b2, sq, opp) \
                   or V.get(p.piece_type, 0) > V.get(mover_p.piece_type, 0):
                    targets += 1
        if targets >= 2:
            return "gabel" if mover_p.piece_type == chess.KNIGHT else "doppelangriff"
    if b2.is_check():
        return "schach_angriff"
    if captured:
        return "guenstiger_abtausch"
    return "technik"


def deep_moment(engine, board: chess.Board, played: chess.Move, pov: chess.Color) -> dict | None:
    """Tiefe Analyse einer Wendepunkt-Stellung (pov am Zug)."""
    try:
        infos = engine.analyse(board, chess.engine.Limit(depth=DEEP_DEPTH), multipv=2)
    except Exception:
        return None
    if isinstance(infos, dict):
        infos = [infos]
    if not infos or not infos[0].get("pv"):
        return None
    best_info = infos[0]
    best = best_info["pv"][0]
    sc = best_info["score"].pov(pov)
    mate_in = sc.mate() if sc.is_mate() and sc.mate() > 0 else None
    best_cp = sc.score(mate_score=MATE_SCORE)
    best_cp = max(-MATE_SCORE, min(MATE_SCORE, best_cp))
    # "Nur-Zug"-Charakter: Abstand zum zweitbesten Zug
    gap = None
    if len(infos) > 1 and infos[1].get("score") is not None:
        sc2 = infos[1]["score"].pov(pov).score(mate_score=MATE_SCORE)
        gap = best_cp - max(-MATE_SCORE, min(MATE_SCORE, sc2))
    pv = best_info["pv"][:4]
    motif = classify_motif(board, best, pv, mate_in, pov)
    b2 = board.copy()
    pv_san, pv_uci = [], []
    for mv in pv:
        if not b2.is_legal(mv):
            break
        pv_san.append(b2.san(mv)); pv_uci.append(mv.uci()); b2.push(mv)
    return {
        "fen": board.fen(),
        "played": board.san(played), "playedUci": played.uci(),
        "best": pv_san[0] if pv_san else "", "bestUci": pv_uci[0] if pv_uci else "",
        "pvSan": pv_san, "pvUci": pv_uci,
        "evalBest": best_cp, "mateIn": mate_in, "gap": gap,
        "motif": motif,
    }


def analyze_game(engine, rec: dict) -> dict | None:
    game = chess.pgn.read_game(io.StringIO(rec["pgn"]))
    if game is None:
        return None
    my_white = rec["white"]["username"].lower() == USER
    my_col = chess.WHITE if my_white else chess.BLACK
    moves = list(game.mainline_moves())
    if not moves:
        return None

    # Eval-Kurve (Weiß-Sicht, cp, gedeckelt)
    evals = []
    b = game.board()
    limit = chess.engine.Limit(depth=DEPTH)
    for i in range(len(moves) + 1):
        if b.is_game_over(claim_draw=False):
            sc = (-MATE_SCORE if b.turn == chess.WHITE else MATE_SCORE) if b.is_checkmate() else 0
            evals.append(sc)
        else:
            info = engine.analyse(b, limit)
            sc = info["score"].white().score(mate_score=MATE_SCORE)
            evals.append(max(-MATE_SCORE, min(MATE_SCORE, sc)))
        if i < len(moves):
            b.push(moves[i])

    acpl_sum = 0; n_my = 0
    inac = mist = blun = missed_mate = 0
    ph_sum = {"o": [0, 0], "m": [0, 0], "e": [0, 0]}
    worst = None
    candidates = []  # (swing, i, before, after, kind)
    b = game.board()
    boards = []      # Stellung vor Zug i (nur für meine Züge gebraucht -> fen)
    for i, mv in enumerate(moves):
        ply = i + 1
        if b.turn == my_col:
            before = evals[i] if my_white else -evals[i]
            after = evals[i + 1] if my_white else -evals[i + 1]
            cpl = max(0, min(1000, before - after))
            acpl_sum += cpl; n_my += 1
            ph = phase_of(ply, b)
            ph_sum[ph][0] += cpl; ph_sum[ph][1] += 1
            if 50 <= cpl < 100: inac += 1
            elif 100 <= cpl < 200: mist += 1
            elif cpl >= 200: blun += 1
            if before >= MATE_SCORE - 50 and after < MATE_SCORE - 50:
                missed_mate += 1
            if worst is None or cpl > worst["cpl"]:
                worst = {"cpl": cpl, "ply": ply, "fen": b.fen(),
                         "san": b.san(mv), "uci": mv.uci(), "bestUci": "", "bestSan": ""}
            # Wendepunkt-Kandidaten: Spiel gedreht (gewonnen->weg / haltbar->verloren)
            if cpl >= 300:
                if before >= 250 and after <= 50:
                    candidates.append((cpl, i, before, after, "missedWin"))
                elif before >= -80 and after <= -250:
                    candidates.append((cpl, i, before, after, "collapse"))
        b.push(mv)

    # Top-2 Wendepunkte tief analysieren
    tps = []
    candidates.sort(reverse=True)
    for cpl, i, before, after, kind in candidates[:2]:
        b2 = game.board()
        for mv in moves[:i]:
            b2.push(mv)
        dm = deep_moment(engine, b2, moves[i], my_col)
        if dm:
            dm.update({"ply": i + 1, "before": before, "after": after,
                       "swing": cpl, "kind": kind, "ph": phase_of(i + 1, b2)})
            tps.append(dm)
            if not worst["bestSan"] and dm["ply"] == worst["ply"]:
                worst["bestSan"], worst["bestUci"] = dm["best"], dm["bestUci"]
    tps.sort(key=lambda t: t["ply"])

    res_raw = rec["white"]["result"] if my_white else rec["black"]["result"]
    res = "w" if res_raw == "win" else ("d" if res_raw in (
        "agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient") else "l")
    return {
        "d": datetime.fromtimestamp(rec["end_time"], timezone.utc).strftime("%Y-%m-%d"),
        "ts": rec["end_time"],
        "tc": {"bullet": "u", "blitz": "b", "rapid": "r", "daily": "d"}.get(rec.get("time_class"), "?"),
        "col": "w" if my_white else "b",
        "res": res,
        "acpl": round(acpl_sum / n_my) if n_my else None,
        "i": inac, "m": mist, "b": blun, "mm": missed_mate,
        "aO": round(ph_sum["o"][0] / ph_sum["o"][1]) if ph_sum["o"][1] else None,
        "aM": round(ph_sum["m"][0] / ph_sum["m"][1]) if ph_sum["m"][1] else None,
        "aE": round(ph_sum["e"][0] / ph_sum["e"][1]) if ph_sum["e"][1] else None,
        "w": (worst if worst and worst["cpl"] >= 200 else None),
        "tp": tps,
        "opp": rec["black"]["username"] if my_white else rec["white"]["username"],
    }


def main() -> int:
    data = load_data()
    done = set(data["games"].keys())
    print(f"Bereits analysiert: {len(done)} Partien")
    fresh = fetch_new(done)
    print(f"Neue Partien gefunden: {len(fresh)}")
    if not fresh:
        save_data(data)
        return 0
    fresh = fresh[:MAX_GAMES]
    print(f"Analysiere in diesem Lauf: {len(fresh)} (Kurve T{DEPTH}, Wendepunkte T{DEEP_DEPTH})")

    engine = chess.engine.SimpleEngine.popen_uci(os.environ.get("STOCKFISH", "stockfish"))
    engine.configure({"Threads": 2, "Hash": 128})
    t0 = time.time()
    try:
        for k, rec in enumerate(fresh, 1):
            gid = rec["url"].split("/")[-1]
            try:
                r = analyze_game(engine, rec)
            except chess.engine.EngineError as e:
                print(f"  Engine-Fehler bei {gid}: {e} – Neustart")
                try: engine.quit()
                except Exception: pass
                engine = chess.engine.SimpleEngine.popen_uci(os.environ.get("STOCKFISH", "stockfish"))
                continue
            if r:
                data["games"][gid] = r
            if k % 10 == 0:
                save_data(data)
                el = time.time() - t0
                print(f"  {k}/{len(fresh)} · {el:.0f}s · Ø {el/k:.1f}s/Partie")
    finally:
        try: engine.quit()
        except Exception: pass
    save_data(data)
    print(f"Fertig: {len(data['games'])} Partien in engine.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
