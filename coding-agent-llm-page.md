Objective: Build an interactive analytics dashboard for 300+ AI model entries with the following schema:

    lab_name, model_name, release_date, context_window_tokens, input_cost_usd_per_1m, output_cost_usd_per_1m, throughput_tokens_per_sec, swe_bench_verified_pct, mmlu_pct, weights, status, source_url, notes

Tech Stack (suggested): React/Next.js + TypeScript + Tailwind + Recharts/Visx + Framer Motion for transitions. Use CSV/JSON as the data source.
Tab 1: Main Timeline (The "Release History" View)

    A horizontal scrollable timeline (or vertical if better for density) showing all 300+ models chronologically by release_date
    Each model is a card/node on the timeline
    Color-code nodes by lab_name (distinct palette per lab: OpenAI=green, Anthropic=purple, Google=blue, etc.)
    Node size should encode context_window_tokens (larger context = larger node)
    On hover/click: tooltip or side panel showing all metrics, status, and source_url link
    Filter bar at top: Multi-select dropdown for labs, date range picker, search by model name
    Zoom controls: Allow collapsing to "year clusters" when zoomed out, expanding to individual models when zoomed in
    Density indicator: Show a subtle histogram above the timeline showing release velocity (models per month/quarter)

Tab 2: Lab Breakout (The "Competitive Landscape" View)

    Vertical accordion or grid layout, one section per lab_name
    Each lab section contains its own mini-timeline showing only their models
    Sort labs by: Total models released, average MMLU score, or latest release date (toggleable)
    Per-lab summary cards at the top of each section showing:
        Total models
        Average cost (input+output)
        Best MMLU score
        Average throughput
    Sparklines within each lab section showing their progression on MMLU and cost over time
    Comparison mode: Allow selecting 2-3 labs to overlay their timelines for direct comparison

Tab 3: Benchmarks (The "Performance Matrix" View)

    Scatter plot matrix (SPLOM) or individual scatter plots:
        X-axis: release_date, Y-axis: mmlu_pct, bubble size: context_window_tokens, color: lab_name
        Second chart: X-axis: input_cost_usd_per_1m, Y-axis: swe_bench_verified_pct (cost vs. coding ability)
        Third chart: throughput_tokens_per_sec vs. mmlu_pct (speed vs. smarts)
    Quadrant labels on scatter plots (e.g., "Cheap & Smart", "Fast but Dumb", "Expensive Specialists")
    Benchmark leaderboard: Sortable table showing top performers per metric with lab badges
    Correlation heatmap: Show which metrics correlate (e.g., does higher cost = higher MMLU?)
    Time animation: A "play" button that animates models appearing by release date to show the industry evolving

Tab 4: Creative Dashboard (The "Market Intelligence" View)
Designer's choice—implement 3-5 of these creative visualizations:

    "Arms Race" Racing Bar Chart: Animated bar chart showing cumulative models released per lab over time (like those YouTube racing charts)
    Capability/Cost Efficiency Frontier: Pareto frontier curve showing the best models at each price point. Highlight which models are "dominated" (worse and more expensive than another)
    Model "Family Trees": If models share naming patterns (e.g., GPT-3, GPT-3.5, GPT-4), attempt to infer lineages and draw a tree/flow diagram
    "Open vs. Closed" Battlefield: Pie/donut charts over time showing the shift in weights availability (open vs. closed). Timeline showing when major open-weight releases happened
    Context Window Wars: Area chart showing the maximum context window per lab over time—emphasize the "race" to 1M+ tokens
    Price Crash Tracker: Line chart showing the cheapest model at each capability tier (MMLU bracket) over time—demonstrating democratization
    Lab "Vital Signs": For each lab, a "health monitor" style display showing their last release date (are they stale?), average time between releases, and trajectory (improving or plateauing on benchmarks)
    Prediction Market: Based on release cadence, project when each lab might hit MMLU 90%, 95%, or 100%

Global Requirements:

    Responsive: Must work on desktop (primary) and tablet. Mobile can be read-only simplified view.
    Performance: Virtualize lists/timelines for 300+ items. Lazy load charts.
    Data quality handling: Handle missing values gracefully (gray out, interpolate, or show "N/A"). Parse dates robustly.
    Export: Button to download filtered data as CSV, and PNG export for each chart.
    Dark mode: Support both light/dark themes.
    Deep linking: URL should encode active tab and filters so views are shareable.

Deliverables:

    Working Next.js app with the 4 tabs
    Sample data loader (I will replace with my real 300-row CSV)
    README with setup instructions and how to swap data sources