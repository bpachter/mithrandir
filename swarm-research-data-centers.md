Task: 

Produce a comprehensive dataset of every large language model (LLM) released publicly from January 1, 2020 through today by the labs listed below. Include all known model sizes/variants within each model family (e.g., for Llama 3: 8B, 70B, 405B; for Claude 3: Haiku, Sonnet, Opus; for GPT-4: base, Turbo, 4o, etc.). Include both open-weight and closed/API-only models. Exclude non-LLM models (image generators, video models, speech/TTS, embedding-only models, pure vision models, robotics policies). Multimodal models are in-scope only if they are primarily LLMs with vision/audio added (e.g., GPT-4o, Gemini, Claude 3+).


Labs to cover (include every model family from each):
OpenAI
Google DeepMind (including pre-merger Google Brain and DeepMind)
Anthropic
xAI (Grok family)
Mistral AI
Meta AI (LLaMA, Llama 2/3/4, OPT, Galactica, etc.)
NVIDIA (Nemotron, Megatron, etc.)
Moonshot AI (Kimi)
Alibaba (Qwen family)
ByteDance (Doubao / Seed family)
DeepSeek
Ant Group (Ling, Bailing, etc.)
MiniMax
Zhipu AI (GLM / ChatGLM)


Output format — REQUIRED:
Deliver the result as a single downloadable CSV file. Do not output the data as a Markdown table, prose, or inline code block. 

Use standard RFC 4180 CSV formatting:
Comma-separated
UTF-8 encoded
Double-quote any field containing commas, quotes, or newlines; escape internal quotes by doubling them
First row is the header
One row per model variant
No merged cells, no multi-row headers, no trailing summary rows

Columns (in this exact order):

lab_name
model_name — full variant name (e.g., "Claude 3.5 Sonnet", "Qwen2.5-72B-Instruct")
release_date — ISO 8601 (YYYY-MM-DD); if only month is known, use the first of the month and note in notes
context_window_tokens — integer, max input tokens
input_cost_usd_per_1m — decimal; if tiered by volume, cache, or context length, report the blended simple average across tiers
output_cost_usd_per_1m — decimal; same blending rule
throughput_tokens_per_sec — decimal; median reported output throughput; prefer Artificial Analysis, fall back to lab-published or third-party benchmarks
swe_bench_verified_pct — decimal (e.g., 49.0); blank if not reported
mmlu_pct — decimal, 5-shot standard MMLU; if only MMLU-Pro or MMLU-Redux exists, record that value and specify which variant in notes
weights — one of: open, closed, gated
status — one of: active, deprecated, retired
source_url — primary citation (model card, blog post, paper, or official pricing page)
notes — free text for caveats, assumptions, pricing conversions, benchmark variants, etc.

Data rules:

Use N/A for fields that are genuinely unknown or never published. Do not estimate silently.
For open-weight models with no official API pricing, use the median price across major hosted providers (Together, Fireworks, DeepInfra, Groq) and note the source in notes.
For tiered pricing (e.g., Gemini 1.5 Pro ≤128K vs >128K), report the simple average and note tiers in notes.
For RMB-denominated pricing from Chinese labs, convert to USD using the exchange rate on the release date and record the rate in notes.
Include deprecated and retired models (GPT-3, text-davinci-003, Claude 1, Claude Instant, PaLM, PaLM 2, Gemini 1.0, etc.) with status set accordingly.
Sort rows by release_date ascending, then by lab_name, then by model_name.
Aim for completeness — expect 200+ rows.

Also deliver (as a separate short text block, after the CSV file):
A brief methodology note (≤300 words) listing primary sources consulted, the exchange rate(s) used for currency conversion, and any systematic data gaps.
Do not embed the CSV inside prose. The CSV must be a standalone attached/downloadable file named llm_releases_2020_present.csv.