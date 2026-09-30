"""All prompts in one place, so they are easy to tweak.
string.Template ($name placeholders) is used so JSON braces need no escaping."""
from string import Template

PLANNER_SYSTEM = ("You are a research planner. You turn a topic into focused questions "
                  "and effective web search queries.")

PLAN = Template("""Today's date: $today
Research topic: "$topic"

1. Break the topic into 3-5 sub-questions that a thorough, balanced report must answer.
2. Write $n web search queries that together cover those sub-questions. Vary the angle:
   overview, latest developments ($year), data and statistics, expert or academic
   analysis, and criticism or opposing views. Keep each query short (3-8 words).

Return JSON: {"sub_questions": ["..."], "queries": ["..."]}""")

EXTRACT_SYSTEM = ("You are a careful research analyst. You report only what the given "
                  "source says. You never add outside knowledge.")

EXTRACT = Template("""Research topic: "$topic"
Sub-questions:
$sub_questions

Source $sid: "$title" ($site, $url)
<source>
$text
</source>

Extract what this source says that is relevant to the topic. Return JSON:
{
  "relevant": true,
  "summary": "2-3 sentences on what this source contributes",
  "source_type": "academic | government | news | industry report | company | blog | forum | other",
  "credibility": 3,
  "credibility_reason": "one sentence: who published it, quality of evidence, possible bias",
  "author": "author name(s) if stated, else empty string",
  "published": "publication date if stated (YYYY-MM-DD or YYYY), else empty string",
  "claims": [
    {"claim": "one specific factual claim, in your own words",
     "quote": "exact words copied from the source that support the claim (max 40 words)",
     "sub_question": 0}
  ]
}
Rules:
- credibility is an integer from 1 (unreliable) to 5 (highly reliable).
- Up to 8 claims. Prefer specific facts: numbers, dates, study results, named organisations.
- "quote" must be copied character-for-character from the source; it is checked automatically.
- "sub_question" is the 0-based index of the sub-question the claim helps answer, or -1.
- If the source is off-topic, return "relevant": false and an empty claims list.""")

COMPARE_SYSTEM = ("You are a fact-checker who compares sources. You are precise about "
                  "which sources support which statement.")

COMPARE = Template("""Research topic: "$topic"
Sub-questions:
$sub_questions

Verified claims from $count sources. Format: (source id, credibility/5) claim
$claims

Compare the sources: group claims that say the same thing and find where they conflict.
Return JSON:
{
  "consensus": [{"finding": "statement supported by 2+ sources", "sources": ["S1", "S4"], "confidence": "high | medium"}],
  "disagreements": [{"issue": "what the sources disagree on",
                     "positions": [{"view": "...", "sources": ["S2"]}],
                     "likely_reason": "e.g. different years, methods, definitions, or incentives"}],
  "single_source": [{"finding": "important claim made by only one source", "sources": ["S3"]}],
  "gaps": ["a sub-question or aspect the sources do not answer well"]
}
Use only the source ids listed above. Different numbers for the same quantity count as a
disagreement unless they clearly measure different things or different years.""")

REPORT_SYSTEM = ("You are an expert research writer. You write clear, neutral, well-structured "
                 "reports in your own words, and you cite every factual statement.")

REPORT = Template("""Today's date: $today
Topic: "$topic"

Sub-questions:
$sub_questions

Sources (id - title, site, date, type, credibility/5):
$sources

Verified evidence (source id, credibility/5):
$claims

Cross-source comparison:
$comparison

Write a research report in Markdown with this structure:
# <a clear title>
## Executive summary        (4-6 sentences answering the topic directly)
## Key findings             (one ### subsection per sub-question)
## Where sources agree
## Where sources disagree   (explain each disagreement and its likely reason)
## Limitations and open questions
Do not write a references section; it is added automatically.

Citation rules:
- Put source ids in square brackets right after the sentence they support, like
  "... rose 40% in 2025 [S2]." or "[S1, S4]".
- Every factual sentence needs at least one citation, and only from the evidence above.
- Give more weight to findings backed by several or high-credibility sources. Say so when a
  claim rests on a single source or a low-credibility source.
- Use your own words; do not copy long passages from the evidence.""")
