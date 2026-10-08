# Fridge Recipe Tracker (PROJECTKITCHEN)

[![CI](https://github.com/clouden56/PROJECTKITCHEN/actions/workflows/ci.yml/badge.svg)](https://github.com/clouden56/PROJECTKITCHEN/actions/workflows/ci.yml)

An AI-powered recipe suggestion and food-waste prevention system built for **INF1103 Programming Fundamentals (Team Project)**.

---

## 📌 Problem Statement

Every week, households discard large amounts of untouched or forgotten food due to expiration, causing:
1. **Food Wastage**: Ingredients rot before use.
2. **Unnecessary Grocery Spending**: Buying duplicates or takeaway instead of utilizing existing items.
3. **Decision Fatigue**: Difficulty figuring out what meals can be cooked with remaining ingredients.

**Fridge Recipe Tracker** acts as a kitchen co-pilot: it tracks your fridge and pantry inventory alongside expiration dates, and uses **Google Gemini AI** to craft tailored recipes that prioritize soon-to-expire ingredients, match meal constraints, and calculate waste diversion metrics.

---

## 🏛️ 4-Layer Architectural Design

The project strictly follows the 4-layer architecture required by the specification:

```text
User / Terminal
       ↓
  io_manager.py      [Input/Output Layer]  (ALL print() and terminal input calls live here)
       ↓
  ai_manager.py      [AI Processing Layer] (Gemini API calls & strict JSON schema validation)
       ↓
 logic_manager.py    [Logic Layer]         (Domain brain: multi-condition rules & allergen gate)
       ↓
 data_manager.py     [Data Layer]          (Flat-file JSON persistence, queries & fault-resilience)
```

### Module Responsibilities & Hard Constraints

| Module | Architectural Role | Constraints & Features |
| :--- | :--- | :--- |
| **`src/io_manager.py`** | **Input Layer** | • Collects structured terminal inputs.<br>• Re-prompts on invalid data (e.g. invalid date formats, non-numeric cook times).<br>• **Every `print()` and `input()` call in the codebase lives here and nowhere else** (enforced by a grep-strict test).<br>• Returns typed dicts (`prompt_recipe_generation_criteria`, `prompt_new_ingredient`, `prompt_history_filter`).<br>• Formats tables, recipe cards, and warning banners. |
| **`src/ai_manager.py`** | **AI Processing Layer** | • **Zero domain logic** (purely handles LLM interaction).<br>• Framework API: `build_prompt(record)`, `call_api(prompt)`, `parse_response(raw)`, `validate_response(data)`, orchestrated by `process(record)`.<br>• Requests JSON output (temperature 0 for repeatable results) and validates the schema strictly; logs and retries with model cascades (`gemini-3.6-flash`, `gemini-flash-latest`, `gemini-2.5-flash-lite`).<br>• Never crashes on network or API failures. |
| **`src/logic_manager.py`** | **Logic Layer (Domain Brain)** | • **Allergen & Safety Gate**: Rejects recipes containing user allergens or synonyms.<br>• **Expiry Priority Scoring**: Rewards recipes that consume ingredients expiring in $\le 3$ days.<br>• Framework API: `evaluate(record)`, `score(record)`, `route(evaluation)`.<br>• **Multi-Condition Decision Rule** (`route`): Determines outcome (`ACCEPTED`, `FLAGGED`, `REJECTED`) based on allergen safety, ingredient match ratio ($\ge 50\%$), and cook time limits.<br>• **Waste Impact Calculation**: Estimates grams of food diverted from disposal. |
| **`src/data_manager.py`** | **Data Layer** | • Framework API: `save(record)`, `load()` (called on startup), `query(filter_fn)` with filter builders `meal_type_filter` / `ingredient_filter`.<br>• Persists inventory and evaluated recipes to flat JSON files (`data/`); `query_items_by_expiry` finds urgent items.<br>• Handles missing, empty, or corrupt files gracefully without crashing. |
| **`main.py`** | **Application Coordinator** | • Orchestrates pipeline flow between the four managers with 100% procedural functions and zero `print()` statements. |

---

## 🔒 Hard Constraints Compliance

* **100% Procedural**: There are **zero `class` definitions** across the entire codebase (including the test suite). Verified via automated static scanning (`re.compile(r"^\s*class\s+")`).
* **AI as Core Engine**: Every recipe suggestion passes directly through the Gemini API.
* **Structured API Responses**: Gemini returns strictly valid JSON adhering to a validated schema.
* **Flat File Persistence**: Data is persisted in `data/inventory.json` and `data/recipe_history.json`.
* **Print Localization**: Only `src/io_manager.py` contains `print()` calls.

---

## 🚀 Setup & Execution

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12 / 3.14)
- (Optional) Docker

### 2. Environment Configuration
Create a `.env` file in the root directory (or set your environment variable):
```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Install Dependencies
No third-party packages are required (standard library only); this step is a no-op kept for convention.
```bash
pip install -r requirements.txt
```

### 4. Run Application
```bash
python main.py
```

### 5. Run Automated Tests
```bash
python tests/test_pipeline.py
```
The suite runs **fully offline**: no API key and no network are needed. It uses hardcoded sample Gemini responses from [tests/sample_ai_responses.py](tests/sample_ai_responses.py) and swaps the network call and `input()` for scripted stand-ins. It contains 12 procedural tests:

| # | Test | Covers |
|---|------|--------|
| 1 | `test_zero_classes_in_codebase` | No `class` definitions anywhere |
| 2 | `test_no_prints_outside_io_manager` | `print(` / `input(` appear only in `io_manager` (grep-strict) |
| 3 | `test_data_manager_operations` | Save/load, queries, corrupt-file fallback |
| 4 | `test_ai_manager_schema_validation` | Schema accepts valid / rejects malformed payloads |
| 5 | `test_logic_manager_rules` | Allergen gate, expiry scoring, multi-condition outcomes |
| 6 | `test_logic_manager_with_sample_ai_responses` | Sample AI responses → every ACCEPTED / FLAGGED / REJECTED branch |
| 7 | `test_logic_manager_helper_functions` | Expiry maths, fuzzy matching, staples, unit conversion |
| 8 | `test_ai_manager_rejects_malformed_responses` | 9 malformed envelopes rejected without exceptions |
| 9 | `test_ai_pipeline_offline_failure_handling` | Network down, timeout, invalid key, 404 cascade, 429 retry |
| 10 | `test_data_manager_corrupt_and_unwritable_files` | Corrupt-file quarantine, atomic saves, write failures |
| 11 | `test_io_manager_reprompts_bad_entries` | Every prompt re-asks on invalid input |
| 12 | `test_end_to_end_pipeline_offline` | Real CLI driven by scripted keystrokes through to the JSON files |

---

## 📄 Engineering Report

[docs/Engineering_Report.pdf](docs/Engineering_Report.pdf) (5 pages) contains the architecture, the **data flow diagram** (user input → AI payload → file storage) and the **exception handling matrix**. It is rendered from [docs/report/engineering_report.html](docs/report/engineering_report.html); to regenerate it after editing:
```powershell
& "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" --headless=new --no-pdf-header-footer --print-to-pdf="$PWD\docs\Engineering_Report.pdf" "$PWD\docs\report\engineering_report.html"
```

---

## 🔁 Continuous Integration

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push and on every pull request into `main`:
1. **Lint & test** on Python 3.10 and 3.12: `ruff` (syntax errors and undefined names), byte-compile, then the offline test suite.
2. **Docker**: builds the image, runs the test suite inside the container, and smoke-tests the CLI.

Workflow: branch from `main` → small, descriptive commits → open a pull request → merge once CI is green.

---

## 🐳 Docker Deployment

### Option A: Using Docker Compose (Recommended)
Make sure your `.env` file contains your `GEMINI_API_KEY`.

```bash
# 1. Run the interactive application (with data persistence):
docker compose run --rm app

# 2. Run the automated test suite inside Docker:
docker compose run --rm test
```

### Option B: Using Standalone Docker Commands

```bash
# 1. Build the Docker image
docker build -t projectkitchen .

# 2. Run the interactive terminal app (with mounted persistent data):
docker run --rm -it -v "$(pwd)/data:/app/data" -e GEMINI_API_KEY="your_api_key" projectkitchen

# 3. Run the automated test suite in container (no API key needed):
docker run --rm projectkitchen python tests/test_pipeline.py
```

---

## 📦 Submission Packaging (Part 1)

Builds `dist/[LabGroup]_[TeamNumber]_ProjectPart1Final.zip` with the five required folders: Engineering Report, Project Code, Test Script, Git Repository History, and Docker image. Commit your work first, because the code is exported from `HEAD`. Docker Desktop must be running.
```powershell
powershell -ExecutionPolicy Bypass -File scripts/package_submission.ps1 -LabGroup P1 -TeamNumber 07
```

