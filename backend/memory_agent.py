"""
memory_insights_agent.py
LLM narration layer over the Memory Agent's deterministic statistics.

Same boundary as antibiotic_specialist_agent.py: the LLM never computes a
number and never invents a correlation. It is given the *complete* output of
MemoryAnalyticsAgent.full_statistics() and asked to write a plain-language
summary of what's already there — nothing else. If the LLM's narration ever
cites a number or a pattern not present in that dict, that is a bug in the
prompt, not an acceptable feature.

This exists because "3 cases, 1 cluster, 1 device association" read as raw
JSON doesn't give a physician or infection-control reviewer the same quick
orientation a written briefing does — but the briefing must be describing
the deterministic layer below it, not replacing it.
"""
import os

try:
    from anthropic import AsyncAnthropic
except ImportError:  # pragma: no cover
    AsyncAnthropic = None

client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY")) if AsyncAnthropic else None

INSIGHTS_SYSTEM_PROMPT = """You are an infection-control epidemiologist \
reviewing case data for a physician. You are given the complete case-level \
data this system has recorded (case_records), plus statistics already \
computed from it (aggregate, pattern_signals, breakdowns). Your job is open \
analysis: look across case_records yourself for anything worth flagging —
timing clusters, repeated organisms, unexpected severity patterns, shared \
device exposures, repeat patients, or anything else you notice — not just \
the two pre-computed pattern_signals categories. Nosocomial spread has many \
possible vectors (shared equipment, staff, ward, environmental source, TB \
and other atypical organisms, admission timing, etc.) and you should reason \
about plausible ones, not limit yourself to ventilators and catheters.

CRITICAL — never settle on a single explanation. Documented failure mode in \
published LLM infection-control benchmarks: a model saw one positive test \
result and immediately recommended treatment for one diagnosis, without \
considering equally plausible alternatives, and that overconfidence was \
rated as a real safety failure by clinical reviewers. You must not repeat \
that mistake. For every pattern you raise, list AT LEAST 2-3 distinct \
possible explanations side by side (e.g., a shared device, a shared \
ward/staff exposure this system doesn't record, coincidence given the \
sample size, or an unrelated common community source) — never present just \
one story as if it were the likely one.

You MUST separate two kinds of statements and label them clearly:
1. "Observed in your data" — only for things you can point to specific \
case_ids/counts/dates for, directly from case_records or the precomputed \
statistics. Never state a count or pattern here that isn't literally \
verifiable in the given JSON.
2. "Possible explanations to investigate" — multiple plausible \
epidemiological hypotheses (ward, staff, environmental source, TB exposure, \
equipment other than what this system tracks, coincidence, etc.) that this \
system's data CANNOT confirm or rule out on its own, because it doesn't \
collect that information (see fields_not_collected_by_this_system). List \
more than one. Frame these explicitly as directions for the physician/\
infection-control team to investigate manually — never as findings.

Hard rules:
- Never state a specific cause as confirmed, and never rank one hypothesis \
as "most likely" unless the data itself (not your intuition) shows why. \
Use "may share", "could suggest", "consider investigating" — never "caused \
by" or "the source is".
- Never invent a specific case_id, count, date, ward, or name that isn't in \
the provided data.
- Organism-name clustering (what pattern_signals detects) is a simple \
frequency-count signal — in published evaluations, this class of detector \
has high sensitivity but only moderate specificity (roughly 60% in one \
MRSA study), well below genomic/molecular typing. Say plainly that this is \
a low-specificity screening trigger, not a confirmed outbreak — confirming \
relatedness would require laboratory typing this system does not perform.
- If case_count is small (under ~10), say explicitly that the sample is too \
small for a reliable signal.
- If there's nothing notable, say so plainly rather than manufacturing a \
pattern to fill space.
- Plain language, 6-9 sentences, no headers. The physician makes the final \
call — you are surfacing things to look at, not concluding anything.
"""


def _fallback_summary(stats: dict) -> str:
    """Used if the Claude API call fails — plain templated summary from the
    same stats dict, so a narration outage never hides the underlying data."""
    agg = stats.get("aggregate", {})
    clusters = stats.get("pattern_signals", {}).get("organism_clusters", [])
    assocs = stats.get("pattern_signals", {}).get("device_associations", [])
    parts = [f"{agg.get('case_count', 0)} cases recorded."]
    if clusters:
        parts.append(
            "Organism clusters: " + "; ".join(
                f"{c['organism']} ({c['case_count']} cases)" for c in clusters
            ) + "."
        )
    else:
        parts.append("No organism clusters detected.")
    if assocs:
        parts.append(
            "Device-association hypotheses for review: " + "; ".join(
                f"{a['matching_case_count']}/{a['total_organism_case_count']} {a['organism']} cases shared {a['device']}"
                for a in assocs
            ) + "."
        )
    else:
        parts.append("No device-association hypotheses detected.")
    parts.append("Note: organism-name clustering is a low-specificity screening signal (not confirmed relatedness — that would require lab typing this system doesn't perform).")
    parts.append("(Automated narration unavailable; showing structured summary only.)")
    return " ".join(parts)


async def narrate_insights(stats: dict) -> str:
    if client is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return _fallback_summary(stats)
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=350,
            system=INSIGHTS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": str(stats)}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
    except Exception as exc:  # noqa: BLE001 — narration failure must not hide the stats
        import logging
        logging.getLogger("sepsis_bundle.memory_insights").error(
            "Insights narration call failed, falling back to templated summary: %s", exc,
        )
        return _fallback_summary(stats)
