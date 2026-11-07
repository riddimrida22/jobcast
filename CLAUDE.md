# AI/Robot Job-Replacement App

Consumer app that tells a person whether, and when, AI or robots are likely to replace
their job, with the reasoning shown and guidance on what to do. See SPEC.md for the
concept and the open questions to settle with Bertrand before building.

## Ground rules specific to this project
- **Defensible methodology only.** Scores come from a transparent model built on published
  research and real occupation/task data (O*NET, Frey & Osborne, Eloundou et al., McKinsey/
  OECD/WEF), with sources cited in-app. Never let an LLM invent a risk number; use it to
  explain, not to score.
- **Frame as ranges, not verdicts.** This touches people's livelihoods. Probabilities and
  timelines, with uncertainty, never a flat "your job is gone."
- Greenfield: confirm audience, platform, geography, monetisation, and name before coding.

(Global and user working-style rules in ~/.claude/CLAUDE.md still apply.)
