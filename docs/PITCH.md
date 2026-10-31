# WarmPath: pitch script

Two formats (from the event deck): a **2-minute Loom** (submitted by 3:30 PM) and, if we're a finalist, a **5-minute live demo
+ 2 minutes of Q&A**. Judges score: end-to-end 25 · facts and verification 20 · robustness 20 · customer value 20 · demo and understanding 15.

> The demo request contains a real person's name, so it lives in `docs/DEMO.local.md` (gitignored). It's written below as
> **[DEMO REQUEST]**: "warm intro to <a VC General Partner> at <their fund>, we're raising our seed round".
> Backups: **[SWIGGY]** `warm intro to the head of data at Swiggy via IIT Bombay alumni` · **[ZEPTO]** `warm intro to the CTO at zepto via iit bombay`

**Roles on stage**
| Member | Role | Owns which criterion |
|---|---|---|
| **Aditya** | opener, problem, service + architecture, close | customer value · understanding |
| **Apurba** | drives the laptop, live demo narration | end-to-end · demo |
| **Vaibhav** | trust: verification, scoring, robustness, eval numbers | facts and verification · robustness |

---

## 1. Finals: 5-minute live demo

### 0:00 – 0:45 · ADITYA: the hook and the problem
> "Raise your hand if you've ever sent a cold message to someone important and got no reply.
>
> Warm intros work far better. But finding one is guesswork: *'I think Rahul knows her, they were both at Flipkart'*,
> where Flipkart has tens of thousands of people.
>
> And people **pay** for this. Founders pay fundraising advisors a share of their round for investor intros. Companies pay
> recruiters. Sales teams pay for warm-path tools. That's a service industry.
>
> We built **WarmPath**, an agent that does that whole job. You say who you want to reach, and it hands you a verified warm
> path and a ready-to-send intro. Every link is proven on Crustdata's identity graph. Apurba?"

### 0:45 – 3:00 · APURBA: live demo (the whole job, end to end)
*(UI already open, dark mode, cache warm)*

1. **Type [DEMO REQUEST]** and press Enter.
   > "We're three students. None of us knows a single VC. Let's ask WarmPath to get us to a General Partner for a seed round."
2. **While the steps stream** (point at each line):
   > "It understood the request, resolved the right fund and the right person, and is now searching the people who actually
   > *worked alongside* them, at the same company and the same time. It loads company size *at that time*, scores every pair,
   > and then re-checks every link against the full profiles."
3. **"Your paths" appear:**
   > "And here's the result: all three of us have a verified route. Route one: me, to a colleague from an
   > **8-person startup**, to the partner. They worked there together too, and the web has articles mentioning both."
4. **Click hop 1 → evidence panel:**
   > "Every number is clickable. Months of overlap, *8 people in that month* from the headcount history, same team. Each
   > citation links to the exact Crustdata call in the audit trail, with its credits and a hash of the response."
5. **Open the Drafts tab:**
   > "The finished work: an intro request addressed to *my* contact, the person I actually know, explaining the rest of the chain,
   > with a note they can forward. Every sentence is fact-checked against the evidence. And nothing is ever sent; a human approves."
6. **Graph tab (5 s):**
   > "Everything it learns goes into our own social graph: 788 people and 3,791 verified relationships, built today. Back to Vaibhav."

### 3:00 – 4:10 · VAIBHAV: why you can trust it
> "Two things matter for a service like this: is it right, and does it survive messy reality.
>
> **Right:** a connection exists only when two Crustdata records share the same company ID with overlapping dates. It's a join,
> not a guess. The score knows that two years at a 30-person startup is a much stronger tie than two years at a 30,000-person
> company, because we use headcount *during* the overlap. We tested this on 11 real startups: WarmPath ranks the founder's
> real co-founder **number one 91% of the time**. A random pick does that 9% of the time.
>
> **Messy reality:** typos like 'teh data guy at swigy', Hindi, five different companies called 'Swiggy', 'CTO' vs 'Chief Technology
> Officer', 'Self-employed' pretending to be a shared employer, people who asked to be removed, rate limits, and the free LLM going down.
> Our eval has 28 scenarios across six edge-case categories: **28 out of 28 pass, with zero silent failures and zero fake connections**."
>
> *(Apurba flashes `eval/scorecard.md` for ~5 s)*

### 4:10 – 5:00 · ADITYA: what's underneath, what's next, close
> "Under the hood it's infrastructure for agents. One pipeline serves the web app, a CLI, and an **MCP server**, so Claude or
> any agent can call `find_warm_paths` before it writes outreach.
>
> What's next: watchers that alert you the day a new path to your target appears, account maps for whole sales lists, and an
> alumni-office mode for IIT Bombay.
>
> Cold outreach is a numbers game. WarmPath makes it a **relationship** game, with proof. Thank you."

---

## 2. Q&A: likely questions and who answers

| Question | Owner | Answer in one breath |
|---|---|---|
| "How is this different from LinkedIn's 'mutual connections'?" | Aditya | Mutual connections are self-reported clicks with no strength. Ours are proven co-employment with dates, size at the time and team, scored and cited. A connection request ≠ having worked together. |
| "What's the hardest case?" | Vaibhav | Same-name people and huge employers. Exact-name matching + company + an ambiguity warning for the first; size-during-overlap + a team signal for the second ("both at Google" isn't a tie). |
| "How do you know it works?" | Vaibhav | Co-founder recovery on 11 real startups (91% #1 vs 9% random), 28/28 gold scenarios, 204 tests, and a scorecard with history on every change. |
| "What if the data is stale?" | Aditya | A verification pass re-fetches full profiles and drops vanished ties. Freshness is shown; an old profile triggers a warning. Next: Crustdata watchers. |
| "What failed along the way?" | Vaibhav | "Self-employed" built fake cliques (1,135 fake relationships → fixed); exact-title search found nobody ("Head of Data" doesn't exist at Swiggy); the free LLM leaked the target's company into the network filter. All are in NOTES.md. |
| "Why would a business pay?" | Aditya | Fundraising advisors charge a share of the round; recruiters charge a share of salary; SDR hours are expensive. We deliver the intro request for a few credits (~0.35 credits per verified path when cached). |
| "Privacy?" | Apurba | No contact details are fetched, nothing is sent, drafts need approval, and real data is never committed. Only professional history Crustdata already holds. |
| "Why not just ask an LLM?" | Vaibhav | An LLM can't know who worked with whom in which month. The LLM only helps parse messy requests, and it's optional: switch it off and every scenario still passes. |
| "How much does a run cost?" | Apurba | ~20–40 credits fresh, ~5 or less when the graph and cache already know the people, and the graph memory makes every next query cheaper. |

---

## 3. The 2-minute Loom (Apurba records, everyone reviews)

| Time | Screen | Voice (Apurba, or split: Aditya opens/closes) |
|---|---|---|
| 0:00–0:10 | Title card / UI home | "People pay brokers and recruiters for warm intros. WarmPath does the whole job and proves every link." |
| 0:10–0:45 | type [DEMO REQUEST] → steps stream | "Three students, no VC network. It resolves the fund and the partner, finds who really worked alongside them, sizes each company at the time, scores and verifies." |
| 0:45–1:10 | "Your paths" → click hop → evidence + audit row | "All three of us have a verified route. Every reason is clickable down to the exact Crustdata call." |
| 1:10–1:25 | Drafts tab | "Finished work: an intro to my own contact, fact-checked. Nothing is sent without approval." |
| 1:25–1:40 | type `teh data guy at swigy pls` → still resolves | "Messy input still works: typos, Hindi, acronyms, lookalike companies." |
| 1:40–1:52 | Graph tab | "Everything goes into our own verified social graph: 788 people, 3,791 relationships." |
| 1:52–2:00 | `eval/scorecard.md` | "28 of 28 scenarios, zero fake connections, co-founder found number one 91% of the time. WarmPath." |

**Before recording:** warm the cache (run all three requests once), close other tabs, zoom the browser to 110%, and **blur or
crop strangers' names** (keep the team's names readable). **After recording:** open the Loom link in a private window and check it plays.

---

## 4. If the live demo breaks

1. Rerun the same request: it's cached, so it replays in ~2 s.
2. Switch to **[SWIGGY]** or **[ZEPTO]** (also cached).
3. No network at all: `WARMPATH_FAKE=1 uv run warmpath serve` (offline world) and say *"this is our offline test world"*.
4. Last resort: play the Loom.

## 5. Rehearsal checklist

- [ ] Full 5-minute run-through twice, timed (target 4:45)
- [ ] Each person knows their handoff line ("Apurba?" / "Back to Vaibhav." / "Thank you.")
- [ ] Cache warmed for all three requests on the demo laptop; `.env` present; charger plugged in
- [ ] Scorecard open in a second tab
- [ ] Q&A: each owner says their answers out loud once
