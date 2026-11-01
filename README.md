# MatchResolver — a GenLayer Intelligent Contract

A small, complete **Intelligent Contract** written in Python for GenLayer's GenVM.
It settles a simple question that normal blockchains cannot answer on their own:

> *"Who won the football match between Team A and Team B on this date — and what was the score?"*

There is no oracle and no off-chain worker. The contract itself **fetches a public
results page from the web**, asks an **LLM** to extract the winner and final score,
and GenLayer's validators agree on the answer through the **Equivalence Principle**
before anything is written on-chain.

Contract source: [`contracts/match_resolver.py`](contracts/match_resolver.py)

---

## What it does

1. You deploy it with a match: a date (`YYYY-MM-DD`) and two team names.
   The contract builds its source URL from the date:
   `https://www.bbc.com/sport/football/scores-fixtures/<date>`
   (the same source used in GenLayer's official examples).
2. Anyone calls **`resolve()`** after the match.
3. A validator (the *leader*) fetches the page with `gl.get_webpage(...)` and asks
   an LLM (`gl.exec_prompt(...)`) to return just two decision fields as JSON:
   `{"winner": "team1" | "team2" | "draw", "score": "2-1"}`.
4. The other validators **independently re-run the exact same function** and the
   result is accepted only if their decision JSON matches the leader's exactly
   (`gl.eq_principle_strict_eq`). The free-text reasoning of the LLMs is never
   compared — only the objective decision fields.
5. If the match hasn't been played yet, the LLM answers `unknown`, nothing is
   stored, and `resolve()` can be called again later. Once a result is accepted,
   `has_resolved` flips to `true` and `get_result()` serves the winner and score
   to anyone, forever, with normal deterministic reads.

### Public interface

| Method | Type | Description |
| --- | --- | --- |
| `__init__(game_date, team1, team2)` | deploy | Sets the match and builds the BBC results URL |
| `resolve()` | `@gl.public.write` | Fetches the result page, runs LLM extraction under consensus, stores winner + score |
| `get_match_info()` | `@gl.public.view` | Teams, date, source URL, resolved flag |
| `get_result()` | `@gl.public.view` | Winner (`team1`/`team2`/`draw`) and final score |

---

## How it works — the Equivalence Principle

Traditional smart contracts must be deterministic: every node replays the code and
must get bit-identical output. Web pages and LLMs are **not** deterministic, so
GenLayer wraps every non-deterministic operation in an *equivalence principle*:

- A **leader** node executes the operation and proposes a result.
- **Validators** independently re-execute the same operation and vote on whether
  their result is *equivalent* to the leader's, according to a rule **you** define
  in the contract.
- Majority agreement → the result is accepted and state changes.
  Majority rejection → a new leader is rotated in and the process retries.
  No consensus → the transaction ends **undetermined** and state is untouched.

This contract uses the strictest rule, **strict equality**, and is designed so that
rule is fair: the leader function strips everything subjective away and returns a
tiny canonical JSON string (`json.dumps(..., sort_keys=True)`) containing only the
winner enum and the score string. Two honest validators reading the same results
page will produce the identical string.

Other rules exist for other shapes of output — the docs' quick guide:

| Pattern | Use when |
| --- | --- |
| `gl.eq_principle_strict_eq(fn)` | Objective results that must match exactly (this contract) |
| `gl.eq_principle_prompt_comparative(fn, principle)` | Complex/text results; an LLM judges equivalence against your principle |
| `gl.eq_principle_prompt_non_comparative(fn, task, criteria)` | Open-ended output (e.g. summaries) judged against source data + criteria |
| Custom validator via `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` | Full control: partial-field matching, numeric tolerance, custom error handling |

> ⚠️ A validator must verify the *substance* of the answer by re-running the task —
> never just check that the leader's output is well-formed JSON. The docs call
> format-only checking "leader-output-only validation", and it is not consensus.

---

## Deploy it in GenLayer Studio (step by step)

GenLayer Studio (<https://studio.genlayer.com>) is the hosted IDE + simulated
validator network. It runs on **Studionet** (chain ID **61999**), which is
**gasless** — you can write, deploy and test there with zero GEN and zero setup.

1. Open <https://studio.genlayer.com> and connect/sign in with your wallet when
   prompted (Studio creates a local dev account flow for testing).
2. Create a new contract file (e.g. `match_resolver.py`) and paste the full
   contents of [`contracts/match_resolver.py`](contracts/match_resolver.py).
   - The first line is the SDK dependency declaration:
     `# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }`
     If Studio flags the pinned version, replace it with the SDK version Studio
     currently offers (the `py-genlayer:test` tag also appears in the docs).
3. Click **Deploy**. In the constructor form enter, for example:
   - `game_date`: `2025-05-25` (any finished match day, `YYYY-MM-DD`)
   - `team1`: `Arsenal`
   - `team2`: `Chelsea`
   (Pick a match that actually appears on that day's BBC scores page.)
4. Wait for the deployment transaction to be **Accepted/Finalized**, then copy the
   contract address Studio shows you — you'll need it for the Portal submission.
5. Test it:
   - Run `get_match_info()` (a view — instant, free) and check the URL and teams.
   - Run `resolve()` (a write). Non-deterministic transactions take longer than
     normal ones: the leader fetches the page, validators re-run and vote. Watch
     the transaction status in Studio until it finalizes.
   - Run `get_result()` — you should see `"has_resolved": true` with the winner
     and score from the real match.
   - Troubleshooting: if `resolve()` returns *"Match not finished yet"*, the date
     or team names don't match a finished game on that BBC page — redeploy with a
     correct fixture. If a transaction ends *undetermined*, just call `resolve()`
     again; it means validators couldn't agree on that attempt.

### Going further: Bradbury testnet

When the contract works in Studio, the production-like public testnet is
**Testnet Bradbury** (chain ID **4221**, shared with the earlier Asimov testnet —
Bradbury is the one currently open for deployment):

- You need test GEN for gas: claim from the official faucet at
  <https://testnet-faucet.genlayer.foundation> (connect the same wallet you will
  deploy with).
- Deploy with the GenLayer CLI (`genlayer network set testnet-bradbury`,
  `genlayer network info` to verify RPC/chain/explorer, then `genlayer deploy`)
  or with the `genlayer-js` SDK.
- Recommended flow from the official docs: **Localnet → Studionet → Bradbury**.
  Studio first, Bradbury when you want persistent, production-like validation
  with real LLM workloads.
- Note (from community guides): the faucet may ask for a GitHub account and/or a
  small mainnet ETH balance check — have a GitHub account ready just in case.

---

## Repository layout

```
genlayer-s2/
├── contracts/
│   └── match_resolver.py   # the Intelligent Contract (this project)
├── README.md                # you are here
├── ARTICLE.md               # publishable tutorial article draft
└── DEPLOY_STEPS.md          # phone checklist for the account owner
```

## Sources

- GenLayer docs — Introduction to Intelligent Contracts:
  https://docs.genlayer.com/developers/intelligent-contracts/introduction
- GenLayer docs — The Equivalence Principle:
  https://genlayer-docs.netlify.app/developers/intelligent-contracts/equivalence-principle
- Python SDK reference (`genlayer.std`):
  https://sdk.genlayer.com/v0.1.0/api/public/genlayer.std.html
- GenLayer docs — Networks (Studionet / Bradbury / faucet):
  https://docs.genlayer.com/developers/networks
- Official example project (football bets):
  https://github.com/genlayerlabs/genlayer-project-boilerplate
