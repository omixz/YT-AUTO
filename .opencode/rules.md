# AI Collaboration Rules - Context Management & Auto-Optimization Protocol

As the AI collaborator on this project, you must independently monitor session size and maintain context health seamlessly in a single message response, without requiring user intervention. Execute the following actions automatically:

## 1. ACTIVE FILE FILTERING & BOUNDARY CONTROL
- Dynamically ignore large build folders (e.g., node_modules, dist, target) and non-source binaries.
- Prioritize reading specific file chunks or individual modules over parsing global codebases.
- Target only the interface boundaries and specific functional blocks relevant to the active task.

## 2. COMPACTION & LOG PURGING
- Proactively run terminal and history house-cleaning tasks before background metadata overflows the token limit.
- Prevent context tracking loops by ignoring historical tool-trace payloads once an operation completes.
- Keep final code modifications, file writes, and clean output syntheses confined to a single, complete message response.