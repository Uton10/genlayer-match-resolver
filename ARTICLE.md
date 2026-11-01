# From Zero to GenLayer: A Smart Contract That Reads the Web and Asks an AI

*Building and deploying a football-match resolver on GenLayer's GenVM — in Python, with no oracle.*

---

Every smart contract developer hits the same wall sooner or later:

**Blockchains can't see the outside world.**

An Ethereum contract cannot tell you who won last night's football match. It can't
read a news page, check a price on a website, or judge whether a freelancer's
deliverable matches the brief. So we bolt on oracles — trusted middlemen that fetch
the answer and sign it — and quietly accept a central point of failure in our
"trustless" systems.

GenLayer takes a different route. Its **Intelligent Contracts** are written in
Python and can natively **browse the web** and **call LLMs** from inside the
contract. The obvious objection — *"but every node would get a different answer!"* —
is answered by GenLayer's consensus design, **Optimistic Democracy**, and a rule
you define yourself called the **Equivalence Principle**.

In this tutorial we'll build a complete, working Intelligent Contract: a
**football match resolver** that reads a real results page, asks an AI who won,
and stores the answer on-chain only after a network of AI validators agrees.
By the end you'll understand:

- how Intelligent Contracts are structured,
- how the Equivalence Principle turns non-deterministic AI output into consensus,
- how to deploy and test in **GenLayer Studio** (free, in your browser),
- and how to take the same contract to the **Bradbury testnet**.

No Solidity. No oracle. Just Python.

---

## The mental model in 60 seconds

When a normal contract runs, every node replays it and demands **bit-identical**
results. That works for arithmetic. It fails for "fetch this web page" (pages
change, nodes fetch at different moments) and for "ask an LLM" (two models phrase
answers differently).

GenLayer instead elects a **leader** node to do the non-deterministic work and
*propose* a result. The other **validators** then *independently re-run the same
work* and vote on whether their result is **equivalent** to the leader's,
according to a comparison rule written into your contract.

- Majority agrees → result accepted, state updates.
- Majority disagrees → a new leader is rotated in, process retries.
- Still no agreement → the transaction ends **undetermined** and state is
  left untouched. Nothing incorrect is ever written.

Your job as the developer is to design the output so that honest validators can
agree: compare *decision fields*, not prose. Keep that in mind — it's the single
most important design idea in this ecosystem.

---

## What we're building

`MatchResolver` takes a match — a date and two team names — at deployment time.
After the game, anyone calls `resolve()`. The contract:

1. builds the BBC Sport results URL for that date,
2. fetches the page (`gl.get_webpage`),
3. asks an LLM to extract the winner and the full-time score (`gl.exec_prompt`),
4. reduces the answer to a tiny JSON object — `{"winner": "team1", "score": "2-1"}` —
5. and stores it **only if** the validators' independent runs produce the exact
   same JSON (`gl.eq_principle_strict_eq`).

If the match hasn't been played, the contract stores nothing and `resolve()` can
simply be called again later. Clean, honest, and about 150 lines of Python.

---

## Step 1 — The contract skeleton

Every Intelligent Contract starts with a dependency declaration and a class that
extends `gl.Contract`. State is declared with type annotations, exactly like a
Python dataclass:

```python
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
import typing

from genlayer import *


class MatchResolver(gl.Contract):
    game_date: str        # "YYYY-MM-DD"
    team1: str
    team2: str
    resolution_url: str
    has_resolved: bool
    winner: str           # "team1" | "team2" | "draw"
    final_score: str      # e.g. "2-1"

    def __init__(self, game_date: str, team1: str, team2: str):
        self.game_date = game_date
        self.team1 = team1
        self.team2 = team2
        self.resolution_url = (
            "https://www.bbc.com/sport/football/scores-fixtures/" + game_date
        )
        self.has_resolved = False
        self.winner = ""
        self.final_score = ""
```

Two things to notice:

- **The `Depends` header** tells GenVM which version of the Python SDK to load.
  It's the first line of the file and it's mandatory.
- **Methods are gated by decorators.** `@gl.public.view` marks a read-only
  method (free, instant, no consensus). `@gl.public.write` marks a method that
  can change state — and therefore goes through the validator process.

Views are boring in the best way:

```python
    @gl.public.view
    def get_result(self) -> dict:
        return {
            "has_resolved": self.has_resolved,
            "winner": self.winner,
            "final_score": self.final_score,
        }
```

## Step 2 — The leader function: web + LLM

All non-deterministic work goes into a nested function. This function is what
the leader executes — and what every validator re-executes:

```python
        def get_match_result() -> str:
            page = gl.get_webpage(url)

            prompt = f"""
                The following text is a football results web page for
                {team1} vs {team2}.

                Page content:
                {page}

                Find the finished match between {team1} and {team2} and
                answer with a JSON object and nothing else:
                {{"winner": "<team1|team2|draw>", "score": "<goals team1>-<goals team2>"}}
                ...
            """

            raw = gl.exec_prompt(prompt)
            # ... parse the JSON, keep ONLY the winner + score fields ...
            return json.dumps(decision, sort_keys=True)
```

This is where beginners usually go wrong, so let's be deliberate:

**Return decisions, not essays.** If this function returned the LLM's full
analysis paragraph, no two validators would ever produce the same text and
consensus would be impossible. By extracting only `winner` and `score`, and
serialising them canonically (`json.dumps(..., sort_keys=True)`), we get a
short string that honest validators *can* reproduce exactly. The reasoning is
thrown away; the decision is what's being agreed on.

**Handle the "not played yet" case in the prompt itself.** The prompt instructs
the model to answer `{"winner": "unknown", "score": ""}` if the match isn't on
the page. The contract then refuses to mark itself resolved — an important
detail, because it makes `resolve()` safely retryable.

## Step 3 — The Equivalence Principle

Now the one line that makes this a GenLayer contract instead of a Python script:

```python
        result_json = gl.eq_principle_strict_eq(get_match_result)
        result = json.loads(result_json)

        if result["winner"] == "unknown":
            return "Match not finished yet — try again later"

        self.winner = result["winner"]
        self.final_score = result["score"]
        self.has_resolved = True
        return result
```

`gl.eq_principle_strict_eq(fn)` tells the runtime: *run `fn` on the leader,
re-run it on every validator, and only hand me the result if all outputs match
exactly.* Under the hood it uses the same leader/validator machinery as the
lower-level `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` API, which you
can drop down to when you need custom comparison logic — partial-field matching,
numeric tolerance for prices, and so on.

Strict equality is the right choice **here** because we engineered the output
to be objective. Other output shapes need other rules, all built into the SDK:

- **Free text / rich analysis** → `gl.eq_principle_prompt_comparative(fn, principle)`:
  an LLM judges whether two outputs satisfy your stated principle
  ("the outcomes must match; key facts must agree").
- **Open-ended work judged against its source** (summaries, classifications) →
  `gl.eq_principle_prompt_non_comparative(fn, task, criteria)`: validators check
  the leader's output against the input and criteria instead of writing their own.
- **Numbers that drift** (prices, quality scores) → a custom validator with a
  tolerance band via `run_nondet_unsafe`.

One warning from the docs, worth tattooing on your monitor: **a validator must
verify the substance of the answer, never just its shape.** A validator that
only checks "is this valid JSON with an allowed enum value?" is not performing
consensus — it's letting the leader decide alone. Re-run the task. Compare the
decision. That's the whole game.

## Step 4 — Deploy in GenLayer Studio

Time to run it. **GenLayer Studio** (https://studio.genlayer.com) is a hosted
IDE connected to a simulated validator network on **Studionet** (chain ID
61999). It's gasless — no tokens, no local installation.

1. Open Studio and create a new file, `match_resolver.py`.
2. Paste the full contract (the complete file ships with this article's repo).
3. Click **Deploy** and fill in the constructor:
   - `game_date`: a day with a finished match, e.g. `2025-05-25`
   - `team1` / `team2`: two teams that actually played that day
     (check the BBC page first — the contract can only find what's there).
4. Wait for the deploy transaction to be **Accepted**, and note the contract
   address.
5. Call `get_match_info()` — a view, so it answers instantly.
6. Call **`resolve()`**. This one takes noticeably longer than a normal
   transaction: the leader has to fetch a web page and run an LLM, then the
   validators repeat the work and vote. Watch it move through consensus in
   Studio's transaction view.
7. Call `get_result()`. If everything worked, you'll see
   `"has_resolved": true`, the winner, and the real full-time score — data
   that started life on a BBC web page and is now agreed-upon on-chain state,
   with no oracle in between.

If `resolve()` comes back with *"Match not finished yet"*, your fixture is
wrong (wrong date, misspelled team, match postponed) — redeploy with a correct
one. If a transaction ends **undetermined**, call `resolve()` again; the
validators simply couldn't agree on that attempt.

## Step 5 — Taking it to Bradbury testnet

Studio is a simulator; **Testnet Bradbury** (chain ID 4221) is the real,
production-like public testnet with genuine LLM workloads. The docs' recommended
progression is Localnet → Studionet → Bradbury.

- Claim test GEN from the official faucet:
  https://testnet-faucet.genlayer.foundation
- Point the GenLayer CLI at Bradbury and verify before you sign anything:

  ```bash
  genlayer network set testnet-bradbury
  genlayer network info     # check RPC, chain ID 4221, explorer
  genlayer deploy
  ```

- The contract code doesn't change at all. Same file, same `Depends` header —
  that's the point of building against the SDK rather than the simulator.

---

## What to build next

This resolver pattern — *fetch a source, extract a decision, agree on the
decision* — generalises surprisingly far:

- **Prediction markets** that settle themselves from results pages
  (GenLayer's own boilerplate ships a full football-betting example).
- **Content verification**: did this article/page actually say X?
- **Escrow with judgment**: release payment when an LLM-verified deliverable
  matches the brief, using non-comparative validation against the brief itself.
- **Insurance-style triggers**: settle claims from public incident reports.

Every one of them is the same shape: a leader function that touches the messy
real world, an output reduced to decision fields, and an equivalence rule that
honest validators can actually enforce.

Smart contracts learned to compute. With GenLayer, they're learning to *judge*.
Start with a match result — then go settle something that matters.

---

*Full contract source, README with deploy notes, and references: see the
accompanying repository (`contracts/match_resolver.py`). Documentation:
docs.genlayer.com — "Introduction to Intelligent Contracts" and
"The Equivalence Principle".*
