# Product Brainstorm: SDGE Usage Analyzer → Product

**Date:** 2026-04-09  
**Status:** Draft — for review and discussion  
**Participants:** (add names)  
**Next step:** Decide on initial sub-project scope and write implementation plan

---

## Context

The SDGE Usage Analyzer is currently a personal tool / side project: a Python/Flask web app that parses SDGE 15-minute interval electricity exports (CSV/XLSX) and categorizes usage into TOU-DR1 rate periods (Super Off-Peak / Off-Peak / On-Peak). It has no users, no monetization, no deployment, and no data persistence.

This brainstorm explores what it would take to turn it into a real product.

---

## Product & UX

### Core reframe

Shift from one-shot analysis tool to **persistent advisor**.

| Current journey | Target journey |
|---|---|
| Download file → upload → see numbers | Sign up → connect once → get smarter every month → save money |

### Top 5 highest-impact UX improvements

1. **Automated SDGE data fetch** — The manual download step is where most users quit. Complete the `feature-auto-fetch` branch. Green Button OAuth is the right long-term solution; Playwright-based automation (already scaffolded in `debug_login.py`) is an acceptable interim fallback.

2. **Bill reconstruction ("Why is my bill this high?")** — Show dollars, not just kWh. Apply TOU-DR1 rates to categorized usage and surface a single headline: _"74% of your On-Peak usage happens in just 3 hours: 5–8 PM."_ Approximate 2025 rates: Super Off-Peak ~$0.10/kWh, Off-Peak ~$0.28/kWh, On-Peak ~$0.54/kWh.

3. **Heat map calendar visualization** — GitHub-style contribution map, each cell = one day, colored by on-peak usage intensity. Click a day to drill into 15-min interval bars. A secondary chart: stacked bar by hour of day averaged over the month. Answers "which days/weeks are expensive" without explanation.

4. **Shift-and-save calculator** — _"If you ran your dishwasher at 10 PM instead of 6 PM, you'd save ~$4/month."_ Users tag appliances (dishwasher, EV charger, pool pump, laundry), tool models savings from shifting them out of On-Peak. Turns the product from a report into a coach.

5. **Plan comparison** — Retroactively apply TOU-DR2, EV-TOU5, and standard tiered plan rates to historical usage. Tell users which plan would have cost less. SDGE's portal doesn't do this well. This is the feature that makes users share the product.

### Additional ideas (lower priority)

- **Solar owners:** Separate solar export credits from consumption in every view. Show net cost after credits and flag months where export timing was suboptimal.
- **Monthly email digest:** Estimated bill, biggest change vs. last month, one tip. One email/month max.
- **Multi-period comparison:** Simple slider — "compare this month to last month" — overlaid on hour-of-day bar chart.
- **Onboarding:** 3-screen interactive explainer using the user's own data to illustrate On-Peak vs Off-Peak before showing results.
- **Mobile:** Prioritize heat map and shift calculator for small screens first.

### North Star metric

**Dollars saved per active user per year.** Everything else (uploads, sessions, chart views) is a proxy.

---

## Technical & Architecture

### Top 5 highest-impact technical changes

1. **Green Button Connect OAuth integration** — SDGE supports the Green Button standard. Users authorize third-party access via OAuth 2.0 at share.sdge.com. No scraping, no reCAPTCHA, utility-sanctioned. Requires registering as a third-party data recipient with SDGE/CPUC. Ship manual upload as fallback while GBC approval is pending.

2. **PostgreSQL persistence + user accounts** — Core schema:
   - `users` — id, email, created_at, last_login
   - `meters` — id, user_id, meter_number, rate_plan
   - `usage_intervals` — id, meter_id, interval_start (timestamptz), kwh, period_type (enum)
   - `uploads` — id, meter_id, uploaded_at, filename, status
   
   Index on `(meter_id, interval_start)`. Store raw 15-min intervals, aggregate at query time with `date_trunc`. 35K rows/year/meter is not a performance problem.

3. **Declarative rate plan engine** — Replace hardcoded `get_time_periods()` conditionals with YAML-configured schedule rules. Adding TOU-DR2 = new config file, zero code change. Enables plan backcasting.

   ```yaml
   plan: TOU-DR1
   periods:
     - name: super_off_peak
       hours: [0, 6]
       days: all
     - name: super_off_peak
       hours: [6, 10]
       days: [weekend, holiday]
     ...
   ```

4. **Celery + Redis background jobs** — Decouple processing from the request cycle. Key tasks:
   - `fetch_green_button_data(meter_id)` — scheduled daily via Celery Beat
   - `process_upload(upload_id)` — async on file upload
   - `send_monthly_report(user_id)` — email digest

5. **Docker + gunicorn + environment-based secrets** — The current dev server cannot run in production. Stack: gunicorn (4 workers), nginx (SSL termination + rate limiting), Postgres 16, Redis. Deploy to Railway or Render initially.

### Authentication

Magic links (passwordless email) as baseline; Google OAuth as convenience layer. Users visit monthly — passwords create more friction than value. Use `itsdangerous` for signed tokens (15-min expiry), `flask-login` for session management.

### Cost calculation

Requires: per-period $/kWh rates (seasonal), fixed charges, baseline tier allocation. Source from SDGE tariff sheets (public, manually maintained) or OpenEI Utility Rate Database API. Store in a `rate_schedules` table: `(plan, effective_date, period_type, rate_cents_per_kwh)`.

### API design (REST)

```
POST   /api/auth/magic-link
GET    /api/auth/verify?token=

GET    /api/meters
POST   /api/meters/{id}/upload
GET    /api/meters/{id}/usage?start=&end=&granularity=day|month
GET    /api/meters/{id}/cost?start=&end=
GET    /api/meters/{id}/compare?plan=TOU-DR2
```

### Testing gaps

Current tests only cover `get_time_periods()`. Missing:
- Integration tests for `process()` with real fixture files (XLSX + CSV)
- Edge cases: DST transitions, leap years, holidays on weekends
- Rate engine tests: one per plan per season
- API endpoint tests via Flask test client
- Cost calculation tests with known rate inputs and expected dollar outputs

Target: 85%+ coverage on `sdge_usage.py` and rate engine using `pytest` + `pytest-cov`.

---

## Business & Market

### Target market

**Ideal early adopters:** SDGE residential customers on TOU-DR1 with rooftop solar who got hit by NEM-3 (April 2023 cut export compensation ~75%). Typically homeowners, 35–65, San Diego suburbs. They already downloaded their SDGE data export once out of frustration.

**TAM:**
- SDGE: ~110–140K highly motivated users (solar owners on TOU plans)
- California-wide (SCE + PG&E + SDGE): 800K–1.2M high-pain customers
- National: real but thinner outside California — do not expand nationally first

### Problem severity

High. NEM-3 customers expected $0 bills and are getting $80–150/month. SDGE's portal gives no actionable rate-period breakdown. This is a $500–2,000/year problem per household. Strong willingness to pay exists.

### Top 3 business directions

1. **Freemium SaaS — $7/month or $59/year** — highest pain, clearest product-market fit.
   - Free: basic upload + kWh breakdown
   - Paid: historical trends, bill forecasting, shift-and-save calculator, plan comparison

2. **Solar installer white-label B2B — $99/month per installer** — faster path to revenue, higher ACV. Installers embed it in post-install welcome emails. 50+ solar installers in San Diego alone.

3. **One-time PDF report — $12** — lowest friction entry product. Proves willingness to pay with no subscription commitment. Funnel into subscription tier. Ship this first.

### Competitive landscape

| Competitor | Gap |
|---|---|
| SDGE portal | No rate-period breakdown, no forecasting, no actionable advice |
| OhmConnect | Pays for curtailment, doesn't do bill analysis |
| Arcadia | Focuses on community solar, not TOU optimization |
| Sense | Requires $300 hardware |
| Google Nest / Tesla app | Appliance-centric, not bill-centric |

**The gap:** software-only, upload-and-understand TOU bill analyzer. Zero hardware required.

### Go-to-market

- **First 100 users:** r/sandiego, r/solar, San Diego Facebook solar groups. One well-written post about NEM-3 frustration = 100 signups in a week.
- **First 1,000 users:** Partner with 2–3 local solar installers. One YouTube video from a San Diego solar creator. Guest post on EnergySage.

### Expansion path

1. Add SCE (Southern California Edison) — same TOU structure, 5M customers
2. Add PG&E — 5.5M customers, most active solar community in the US
3. Rebrand as California-wide tool (e.g., "SolarBill.io")
4. National only after proving subscription model in California

### Risk factors

| Risk | Mitigation |
|---|---|
| SDGE changes export format, parser silently breaks | Robust format versioning + validation tests on fixture files |
| SDGE builds a real tool | Unlikely given utility incentives; double down on plan comparison and advisor features |
| Rate plan changes | Support multiple plans from day one via config-driven engine |
| Low willingness to pay | One-time report model hedges this; prove it before building subscription |
| Data privacy concerns | Clear no-storage policy for free tier is both ethical and a marketing asset |

---

## Cross-Cutting Themes

All three angles converged on the same three priorities:

| Priority | Product | Tech | Business |
|---|---|---|---|
| **Automate data fetch** | Biggest friction point | Green Button OAuth | Enables the subscription model |
| **Show dollars not kWh** | "Why is my bill this high?" | Rate engine + cost calc layer | Core value prop vs. SDGE portal |
| **Plan comparison** | Retroactive plan comparison | Config-driven backcasting | Clearest differentiator; SDGE won't build this |

---

## Open Questions for Discussion

- [ ] Is the one-time PDF report or the freemium subscription the right first product to ship?
- [ ] Green Button Connect registration with SDGE/CPUC — what's the timeline and process?
- [ ] Who are the 2–3 solar installers to approach for the B2B pilot?
- [ ] What's the right domain/brand name if expanding beyond SDGE?
- [ ] Data privacy policy: process-and-discard vs. opt-in storage for history features?
- [ ] Which SDGE rate plans to support at launch besides TOU-DR1? (TOU-DR2? EV-TOU5?)
