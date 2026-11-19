# Optimize Workflow

Use for latency, throughput, memory use, or a specific efficiency question.

## Target And Baseline

Pin the metric and unit, representative input, and relevant environment. Identify the correctness constraints and stop rule, such as a target time or a budget already agreed with the user. Reuse trustworthy existing measurements for the same workload. Respect project restrictions on additional experiments.

Trace plausible costs through the full path, including queue or wait time, I/O, repeated input construction, serialization, locking, or rendering. Prefer an existing trace or measurement at the suspected bottleneck. If measurement falls outside scope, label suggested gains as hypotheses.

## Optimization Loop

Change one cause at a time when practical. Compare the same workload, versioned inputs and settings. Account for warmup, caching, noise, or tradeoffs with memory and output quality when they matter. Keep the user-defined correctness and run limits in force.

Stop when the agreed target is reached, the budget is exhausted, or the evidence no longer supports the next change. Report actual before-and-after values with units and conditions when measured. Distinguish a local measurement from a user's end-to-end experience.
