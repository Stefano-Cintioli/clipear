# clipear — analysis prompt

Reusable rubric for turning a transcript into a chapter map + ranked highlight
candidates. Applies to every video.

## Inputs & rules
- **Read ONLY the compact segments file** `work/<slug>.segments.txt`
  (`start | end | Speaker X | text`). NEVER load the word-level JSON — that exists
  only for refining cut boundaries later, at the cut stage.
- **Output language = the video's language** (auto-detected). Topics, summaries,
  quotes, and "why it works" are all written in that language. Quotes must be
  **verbatim** from the transcript.
- **Speaker labels in the file are a heuristic guess** (gap-based, approximate).
  Do not trust them; attribute by content when confident, otherwise stay neutral.
- Produce **two views**. The **CHAPTER MAP is the primary output.**

## View 1 — CHAPTER MAP (primary)
- Topic segments covering the **full runtime with no gaps** (each chapter's end = next chapter's start).
- Any length. Numbered **C1..Cn** (stable IDs — never renumber across re-runs; append if needed).
- Each: `start`, `end`, `topic`, one-line summary.

## View 2 — HIGHLIGHT CANDIDATES (secondary)
- **15–20**, ranked best-first. Numbered **H1..Hn** (stable IDs).
- Target social shorts: cut range **≤60s**, **snapped to sentence boundaries**.
- Each candidate has:
  - suggested cut range (mm:ss–mm:ss)
  - score **1–10**
  - strongest **verbatim** quote
  - one line on **why it works**
  - target audience (define your own tags, e.g. marketing / sales / technical / community)
  - **compliance flag** (mandatory — see below)

## Judgment rubric (encode exactly)
**High value:** concrete builder/practitioner stories; specific numbers with named
sources; contrarian / counterintuitive takes; audience-specific pain points and how
the thing being discussed solves them; genuine human or funny moments; quotable
one-liners; practical how-tos.

**Low value:** generic intros; pleasantries; long meta-discussion; anything needing
minutes of prior context to land.

## Compliance flag (mandatory per candidate)
Every candidate MUST carry a flag: `YES` + a one-line reason, or `NO`. Flagged
segments can still be clipped — the flag just has to be visible before the human
chooses.

<!-- ============================================================= -->
<!-- ADD YOUR ORG'S COMPLIANCE RULES HERE                          -->
<!--                                                               -->
<!-- List the conditions that force a YES flag for your context.   -->
<!-- Examples you might include (edit for your org):               -->
<!--   - price talk / speculation                                  -->
<!--   - return / APR / performance numbers                        -->
<!--   - investment, legal, medical, or financial advice           -->
<!--   - unverifiable or absolute claims                           -->
<!--   - promotion of a partner / third-party product              -->
<!--   - PII, confidential, or embargoed information                -->
<!-- If you have no rules yet, still flag anything that could need  -->
<!-- a second look before publishing.                              -->
<!-- ============================================================= -->

## Selection reply (what the human sends back)
Chapter IDs (`C4`), highlight IDs (`H2, H9`), and/or raw ranges (`12:30-18:45`).
Then the cut stage takes over.
