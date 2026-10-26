# Application Rules Template

## Task and Recording Boundary

- Recommendations and comparisons are read-only unless recording is explicitly authorized.
- Reuse an existing profile/tracker; do not initialize a duplicate system for a simple search.
- Leads, saved forms and confirmed applications are distinct. Record only the state supported by evidence.
- This template does not authorize browser form filling or final submission.

## Mode

Choose one:

- Precision: fewer applications, more tailoring.
- Volume: more applications, stable resume variants.

Selected mode:

Default: Volume. Promote a specific high-fit role to Precision when it is worth tailoring.

## First Trial Boundary

Choose one:

- Lead finding only: find, screen, classify, and update dashboard. Do not open application flows or submit.
- Review before every apply: ask the user before opening each application flow.
- Limited low-risk apply: apply to 1-3 low-risk roles only after profile, resume, sponsorship, and compensation facts are complete.

Selected first trial boundary:

Default for new users: Lead finding only.

## Prioritize

Apply quickly when a job matches:

- Role families:
- Titles:
- Level:
- Freshness:
- Locations:
- Company types:
- Industries:
- Work authorization:
- Form length:

## Consider

Review before applying when:

- Stretch role:
- Location ambiguity:
- Compensation ambiguity:
- Company fit uncertain:
- Resume variant uncertain:

## Skip

Default skip when:

- Title or level:
- Required years of experience:
- Work authorization:
- Location:
- Company or industry:
- Contract, agency, internship, or part-time:
- Long custom form:
- Missing materials:
- Duplicate or already applied:
- Closed role:

## Hand Off to User

Stop and ask the user when:

- Legal, identity, work authorization, sponsorship, or compensation wording is unclear.
- A posting's sponsorship, authorization, relocation, or compensation requirement conflicts with a `TBD` profile field.
- CAPTCHA, Cloudflare, login, 2FA, or anti-bot appears.
- Resume upload cannot be verified.
- Portfolio, video, writing sample, references, or custom materials are required.
- The final submission should be manually reviewed.

Default form behavior:

- Fill clear basic fields automatically from Candidate Profile.
- Ask focused questions for high-impact missing facts instead of stopping the entire workflow.
- Leave voluntary self-ID blank or choose "Prefer not to say" when allowed unless exact answers are configured.
- Draft custom answers from Answer Bank patterns; ask the user to confirm when no pattern exists.
- Always stop before final submit with a short summary.

Low-friction applications for Volume mode / first tests:

- No new account creation.
- Avoid Workday, Oracle, and long enterprise ATS by default.
- No video, long writing sample, or mandatory portfolio.
- At most one custom question.
- Clear resume upload and confirmation path.

This is a prioritization rule, not a permanent ban. Precision roles may justify long forms or Workday/Oracle after user confirmation.

## Status Classification

- `Pending`: worth later review or application, with no known high-impact blocker.
- `Needs user`: missing user-owned fact or action blocks the decision, such as sponsorship, work authorization, compensation, relocation, login, CAPTCHA, upload, or sensitive answer.
- `Skipped`: does not match rules or is not worth applying.
- `Blocked`: attempted workflow could not safely proceed.
- `Submitted`: explicit confirmation evidence was observed.

## Freshness Policy

Default:

- Campus hiring: prioritize confirmed eligible, active roles, fit and verified deadlines. Older posting dates alone do not disqualify a role.
- Social hiring or a user-requested fresh-posting search: use an appropriate recency filter, optionally 24/48 hours; still verify that the actual role is open.
- Do not infer a deadline or recruiting cohort from a search snippet or a visible Apply button.

Custom policy:

## Account Policy

Use these accounts only:

- LinkedIn:
- Email:
- Job boards:

If a different account appears, stop and ask.
