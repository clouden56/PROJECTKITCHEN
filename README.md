# Fridge Recipe Tracker (PROJECTKITCHEN)

An AI-powered recipe suggestion and food-waste prevention system built for **INF1009 Programming Fundamentals (Team Project)**.

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
| **`src/io_manager.py`** | **Input Layer** | • Collects structured terminal inputs.<br>• Re-prompts on invalid data (e.g. invalid date formats, non-numeric cook times).<br>• **100% of all `print()` calls in the application reside here and nowhere else.**<br>• Formats tables, recipe cards, and warning banners. |
| **`src/ai_manager.py`** | **AI Processing Layer** | • **Zero domain logic** (purely handles LLM interaction).<br>• Generates structured prompts and invokes Gemini API with structured JSON output schema.<br>• Validates output schema strictly; logs and retries with model cascades (`gemini-3.6-flash`, `gemini-flash-latest`, `gemini-2.5-flash-lite`).<br>• Never crashes on network or API failures. |
| **`src/logic_manager.py`** | **Logic Layer (Domain Brain)** | • **Allergen & Safety Gate**: Rejects recipes containing user allergens or synonyms.<br>• **Expiry Priority Scoring**: Rewards recipes that consume ingredients expiring in $\le 3$ days.<br>• **Multi-Condition Decision Rule**: Determines outcome (`ACCEPTED`, `FLAGGED`, `REJECTED`) based on allergen safety, ingredient match ratio ($\ge 50\%$), and cook time limits.<br>• **Waste Impact Calculation**: Estimates grams of food diverted from disposal. |
| **`src/data_manager.py`** | **Data Layer** | • Loads records on startup and persists inventory/recipes to flat JSON files (`data/`).<br>• Implements query and filter functions (`query_items_by_expiry`, `filter_recipes_by_meal_type`, `search_recipes_by_ingredient`).<br>• Handles missing, empty, or corrupt files gracefully without crashing. |
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
This runs 5 automated procedural test suites:
1. `test_zero_classes_in_codebase`: Scans all `.py` files to ensure zero class keywords.
2. `test_no_prints_outside_io_manager`: Scans all modules to ensure zero `print()` calls outside `io_manager`.
3. `test_data_manager_operations`: Tests saving, loading, queries, and corrupt-file fallback.
4. `test_ai_manager_schema_validation`: Tests schema validation for valid and malformed payloads.
5. `test_logic_manager_rules`: Tests allergen filters, expiry scoring, and multi-condition outcomes.

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

# 3. Run the automated test suite in container:
docker run --rm -e GEMINI_API_KEY="your_api_key" projectkitchen python tests/test_pipeline.py
```

