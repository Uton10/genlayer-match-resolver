# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
#
# MatchResolver — a GenLayer Intelligent Contract (Python / GenVM)
# ----------------------------------------------------------------
# Resolves the outcome of a real football match by reading a public
# results page on the web and asking an LLM to extract the winner and
# the final score. No oracle, no API key, no off-chain worker: the
# contract itself browses the web, and GenLayer's validators reach
# consensus on the answer through the Equivalence Principle.
#
# Pattern follows the official GenLayer documentation example
# ("PredictionMarket") and the official genlayer-project-boilerplate
# contract `football_bets.py`:
#   - state is declared with type annotations on the class body
#   - the non-deterministic work (web fetch + LLM call) lives in a
#     nested "leader" function
#   - the leader function is wrapped in an equivalence principle so
#     every validator re-runs it independently and the network only
#     accepts the result when the validators agree
#
# Deploy it in GenLayer Studio (studio.genlayer.com), then interact:
#   resolve()        -> fetches the result page and settles the match
#   get_match_info() -> view: teams, date, source URL, resolved flag
#   get_result()     -> view: winner + final score once resolved

import json
import typing

from genlayer import *


class MatchResolver(gl.Contract):
    # --- Persistent state (declared with type annotations) -------------
    game_date: str        # match date, format "YYYY-MM-DD"
    team1: str            # home team name, e.g. "Arsenal"
    team2: str            # away team name, e.g. "Chelsea"
    resolution_url: str   # web page the result is read from
    has_resolved: bool    # flips to True once consensus settles the match
    winner: str           # "team1" | "team2" | "draw" | "" while unresolved
    final_score: str      # e.g. "2-1", "" while unresolved

    def __init__(self, game_date: str, team1: str, team2: str):
        self.game_date = game_date
        self.team1 = team1
        self.team2 = team2
        # BBC Sport publishes one results page per day. This is the same
        # source used by the official GenLayer examples.
        self.resolution_url = (
            "https://www.bbc.com/sport/football/scores-fixtures/" + game_date
        )
        self.has_resolved = False
        self.winner = ""
        self.final_score = ""

    # --- Views (read-only, no consensus needed) ------------------------

    @gl.public.view
    def get_match_info(self) -> dict:
        return {
            "game_date": self.game_date,
            "team1": self.team1,
            "team2": self.team2,
            "resolution_url": self.resolution_url,
            "has_resolved": self.has_resolved,
        }

    @gl.public.view
    def get_result(self) -> dict:
        return {
            "has_resolved": self.has_resolved,
            "winner": self.winner,
            "final_score": self.final_score,
        }

    # --- The intelligent part ------------------------------------------

    @gl.public.write
    def resolve(self) -> typing.Any:
        """Fetch the match result from the web and settle it on-chain.

        The web fetch and the LLM extraction are non-deterministic:
        different nodes may load the page at slightly different times
        and different LLMs phrase their reasoning differently. That is
        why the actual work happens inside `get_match_result()` and is
        wrapped in an equivalence principle below.
        """
        if self.has_resolved:
            return "Already resolved"

        # Snapshot the state the leader function needs. (Inside GenVM,
        # the nested function captures these local values.)
        url = self.resolution_url
        team1 = self.team1
        team2 = self.team2

        def get_match_result() -> str:
            """Leader function: fetch the page, ask the LLM, and return
            ONLY the decision fields as a canonical JSON string.

            Two LLMs will never produce identical reasoning text, so we
            deliberately reduce the output to the two objective fields
            that must agree across validators: `winner` and `score`.
            Returning a compact, sorted JSON string lets us use strict
            equality as the equivalence rule.
            """
            page = gl.get_webpage(url)

            prompt = f"""
                The following text is a football results web page for
                {team1} vs {team2}.

                Page content:
                {page}

                Find the finished match between {team1} and {team2} and
                answer with a JSON object and nothing else:
                {{"winner": "<team1|team2|draw>", "score": "<goals team1>-<goals team2>"}}

                Rules:
                - "winner" is "team1" if {team1} won, "team2" if
                  {team2} won, "draw" if the match ended level.
                - "score" uses the full-time score, e.g. "2-1".
                - If the match has not been played yet or cannot be
                  found on the page, answer:
                  {{"winner": "unknown", "score": ""}}
            """

            raw = gl.exec_prompt(prompt)

            # exec_prompt may return a dict or a string depending on the
            # model; normalise both to the decision fields only.
            if isinstance(raw, dict):
                data = raw
            else:
                text = str(raw)
                start = text.find("{")
                end = text.rfind("}")
                data = json.loads(text[start : end + 1])

            decision = {
                "winner": str(data.get("winner", "unknown")).strip().lower(),
                "score": str(data.get("score", "")).strip(),
            }
            # Canonical form: sorted keys, no extra whitespace — this is
            # the exact string validators compare with strict equality.
            return json.dumps(decision, sort_keys=True)

        # EQUIVALENCE PRINCIPLE — strict equality.
        #
        # The leader runs get_match_result() and proposes its JSON.
        # Every validator independently re-runs the SAME function
        # (fetching the page and asking its own LLM) and the result is
        # only accepted if the decision JSON matches exactly. If the
        # majority disagrees, a new leader is picked and the process
        # retries; if no consensus forms, the transaction ends
        # "undetermined" and state is left untouched.
        #
        # Strict equality is the right rule here because the output was
        # designed to be objective and tiny (a winner enum + a score).
        # For free-text outputs you would use
        # gl.eq_principle_prompt_comparative(fn, principle) instead.
        result_json = gl.eq_principle_strict_eq(get_match_result)
        result = json.loads(result_json)

        if result["winner"] == "unknown":
            # Match not played yet (or not found). Do NOT mark resolved,
            # so resolve() can simply be called again later.
            return "Match not finished yet — try again later"

        self.winner = result["winner"]
        self.final_score = result["score"]
        self.has_resolved = True
        return result
