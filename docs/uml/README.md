# UML class diagrams

Rendered images are in this folder (`*.svg`, `*.png`); GitHub also renders the Mermaid source below.

**Notation**
- **Stereotypes:** `<<interface>>` marks an ABC with only abstract methods; `<<abstract>>` marks an ABC that also shares behaviour.
- **Visibility:** `+` public, `-` private (a Python `_name` attribute), `#` protected (a `_method` that subclasses override).
- **Members:** `*` marks an abstract method; `$` marks a static method or class constant.

**Relationship arrows**

| Arrow | Relationship |
|---|---|
| `<\|--` | inheritance |
| `<\|..` | realisation of an interface |
| `*--` | composition (the owner creates the part and controls its lifecycle) |
| `o--` | aggregation (the whole holds parts that exist independently) |
| `-->` | association (uses or refers to, no ownership) |
| `..>` | dependency (creates or returns) |

## 1. Architecture overview

```mermaid
classDiagram
  direction LR
  class Application
  class AppConfig
  class WebApp
  class IOManager
  class KitchenService
  class RecipeAIManager
  class AIManager~J, R~ {
    <<abstract>>
  }
  class AIClient {
    <<interface>>
  }
  class GeminiClient
  class LogicManager
  class BusinessRule {
    <<abstract>>
  }
  class DataManager
  class InventoryRepository
  class HistoryRepository
  class RecordComparison

  Application *-- AppConfig
  Application *-- WebApp
  Application *-- KitchenService
  Application ..> DataManager : creates
  Application ..> RecipeAIManager : creates
  Application ..> LogicManager : creates
  WebApp --> KitchenService : uses
  WebApp --> IOManager : uses
  KitchenService --> DataManager : uses
  KitchenService --> AIManager : uses
  KitchenService --> LogicManager : uses
  KitchenService ..> RecordComparison : returns
  AIManager <|-- RecipeAIManager
  AIManager --> AIClient : calls
  AIClient <|.. GeminiClient
  LogicManager o-- "1..*" BusinessRule : ordered rules
  DataManager *-- InventoryRepository
  DataManager *-- HistoryRepository
```

## 2. Domain model (`src/models.py`)

```mermaid
classDiagram
  direction TB
  class Outcome {
    <<enumeration>>
    ACCEPTED
    FLAGGED
    REJECTED
  }
  class Ingredient {
    -_id: str
    -_name: str
    -_quantity: float
    -_unit: str
    -_expiry_date: date
    -_location: str
    +days_until_expiry(today) int
    +expiry_status(today, soon_days) str
    +update_from(other: Ingredient)
    +to_dict() dict
    +from_dict(data)$ Ingredient
  }
  class Inventory {
    -_items: list~Ingredient~
    +add_or_update(ingredient) Ingredient
    +remove(name) Ingredient
    +find(name) Ingredient
    +expiring_within(days, today) list~Ingredient~
    -_next_id() str
  }
  class RecipeRequest {
    -_meal_type: str
    -_max_cook_time_mins: int
    -_allergies: tuple~str~
    -_mandatory_ingredients: tuple~str~
    -_notes: str
    +to_dict() dict
  }
  class RecipeJob {
    -_request: RecipeRequest
    -_inventory: Inventory
  }
  class Recipe {
    -_name: str
    -_cook_time_mins: int
    -_ingredients_used: tuple~str~
    -_missing_ingredients: tuple~str~
    -_steps: tuple~RecipeStep~
    -_required_tools: tuple~str~
    +all_ingredients() tuple~str~
    +to_dict() dict
  }
  class RecipeStep {
    -_number: int
    -_text: str
  }
  class Evaluation {
    -_outcome: Outcome
    -_status_code: str
    -_match_ratio: float
    -_expiry_priority_score: float
    -_waste_diverted_grams: int
    +match_percentage int
    +mandatory_met bool
  }
  class RuleResult {
    -_rule_name: str
    -_passed: bool
    -_outcome: Outcome
    -_message: str
  }
  class RescuedItem {
    -_name: str
    -_days_until_expiry: int
  }
  class HistoryRecord {
    -_id: str
    -_created_at: datetime
    -_request: RecipeRequest
    +to_dict() dict
    +from_dict(data)$ HistoryRecord
    +legacy_id(created_at, name)$ str
  }

  Inventory o-- "0..*" Ingredient : aggregation
  RecipeJob --> RecipeRequest : association
  RecipeJob --> Inventory : association
  Recipe *-- "1..*" RecipeStep : composition
  Evaluation *-- "0..*" RuleResult
  Evaluation *-- "0..*" RescuedItem
  Evaluation --> Outcome
  HistoryRecord *-- Recipe : composition
  HistoryRecord *-- Evaluation : composition
  HistoryRecord o-- "0..1" RecipeRequest : aggregation
```

## 3. AI layer (`src/ai_manager.py`)

```mermaid
classDiagram
  direction TB
  class AIClient {
    <<interface>>
    +generate(prompt, model)* str
  }
  class GeminiClient {
    -_api_key: str
    -_base_url: str
    -_timeout_seconds: int
    -_temperature: float
    +generate(prompt, model) str
    -_post(url, payload) dict
    -_error_for_status(status, message)$ AIServiceError
    -_extract_text(body)$ str
  }
  class AIManager~J, R~ {
    <<abstract>>
    -_client: AIClient
    -_models: tuple~str~
    -_attempts_per_model: int
    +process(record: J) R
    +build_prompt(record: J)* str
    +call_api(prompt, model) str
    +parse_response(raw) Any
    +validate_response(data)* R
  }
  class RecipeAIManager {
    +REQUIRED_FIELDS: dict$
    +build_prompt(record: RecipeJob) str
    +validate_response(data) Recipe
  }
  class AIServiceError
  class AIConnectionError
  class AIAuthenticationError
  class AIRequestRejectedError
  class AIResponseError
  class AIProcessingError

  AIClient <|.. GeminiClient : implements
  AIManager <|-- RecipeAIManager : RecipeJob to Recipe
  AIManager --> AIClient : association
  RecipeAIManager ..> Recipe : creates
  AIServiceError <|-- AIConnectionError
  AIServiceError <|-- AIAuthenticationError
  AIServiceError <|-- AIRequestRejectedError
  AIServiceError <|-- AIResponseError
  AIServiceError <|-- AIProcessingError
  GeminiClient ..> AIServiceError : raises
```

## 4. Logic layer (`src/logic_manager.py`)

```mermaid
classDiagram
  direction TB
  class LogicManager {
    -_rules: tuple~BusinessRule~
    -_matcher: IngredientMatcher
    -_allergen_checker: AllergenChecker
    -_scorer: ExpiryScorer
    -_waste_estimator: WasteEstimator
    +evaluate(recipe, job, today) Evaluation
    +score(recipe, inventory, today) float
    +route(facts) Verdict
    +gather_facts(recipe, job) EvaluationFacts
    +default_rules(min_match_ratio)$ tuple
  }
  class BusinessRule {
    <<abstract>>
    +name: str$
    +status_code: str$
    +outcome* Outcome
    +check(facts) RuleResult
    #_find_problem(facts)* str
    #_describe_pass(facts) str
  }
  class RejectionRule {
    <<abstract>>
    +outcome Outcome
  }
  class WarningRule {
    <<abstract>>
    +outcome Outcome
  }
  class AllergenRule
  class IngredientMatchRule {
    -_min_ratio: float
  }
  class MandatoryIngredientRule
  class CookTimeRule
  class MissingIngredientRule
  class EvaluationFacts {
    -_recipe: Recipe
    -_request: RecipeRequest
    -_match: MatchResult
    -_allergen_hits: tuple~str~
    +within_time bool
  }
  class Verdict {
    -_outcome: Outcome
    -_status_code: str
    -_rule_results: tuple~RuleResult~
  }
  class IngredientMatcher {
    +matches(a, b) bool
    +match(recipe, inventory) MatchResult
  }
  class MatchResult {
    -_ratio: float
    -_matched: tuple~str~
    -_missing: tuple~str~
  }
  class AllergenChecker {
    +SYNONYMS: dict$
    +find(recipe, allergies) list
  }
  class ExpiryScorer {
    +score(recipe, inventory, today) float
    +rescued_items(recipe, inventory, today) list
    +points(days)$ int
  }
  class WasteEstimator {
    +estimate(rescued) int
  }

  BusinessRule <|-- RejectionRule
  BusinessRule <|-- WarningRule
  RejectionRule <|-- AllergenRule
  RejectionRule <|-- IngredientMatchRule
  WarningRule <|-- MandatoryIngredientRule
  WarningRule <|-- CookTimeRule
  WarningRule <|-- MissingIngredientRule
  LogicManager o-- "1..*" BusinessRule : aggregation
  LogicManager o-- IngredientMatcher
  LogicManager o-- AllergenChecker
  LogicManager o-- ExpiryScorer
  LogicManager o-- WasteEstimator
  LogicManager ..> EvaluationFacts : creates
  LogicManager ..> Verdict : creates
  BusinessRule --> EvaluationFacts : reads
  EvaluationFacts *-- MatchResult
  IngredientMatcher ..> MatchResult : creates
```

## 5. Data layer (`src/data_manager.py`)

```mermaid
classDiagram
  direction TB
  class Repository~T~ {
    <<interface>>
    +load()* list~T~
    +save(items)* bool
  }
  class JsonRepository~T~ {
    <<abstract>>
    -_store: JsonFileStore
    +load() list~T~
    +save(items) bool
    #_from_dict(row)* T
    #_to_dict(item)* dict
  }
  class InventoryRepository
  class HistoryRepository {
    +add(record) bool
  }
  class JsonFileStore {
    -_path: str
    +read_rows() list~dict~
    +write_rows(rows) bool
    -_quarantine()
  }
  class DataManager {
    -_inventory_repository: InventoryRepository
    -_history_repository: HistoryRepository
    +load_inventory() Inventory
    +save_inventory(inventory) bool
    +save(record) bool
    +load() list~HistoryRecord~
    +query(record_filter) list~HistoryRecord~
    +get(record_id) HistoryRecord
  }
  class RecordFilter {
    <<interface>>
    +matches(record)* bool
  }
  class MealTypeFilter
  class IngredientFilter
  class OutcomeFilter
  class AllFilters {
    -_filters: tuple~RecordFilter~
  }

  Repository <|.. JsonRepository
  JsonRepository <|-- InventoryRepository
  JsonRepository <|-- HistoryRepository
  JsonRepository *-- JsonFileStore : composition
  DataManager *-- InventoryRepository : composition
  DataManager *-- HistoryRepository : composition
  RecordFilter <|.. MealTypeFilter
  RecordFilter <|.. IngredientFilter
  RecordFilter <|.. OutcomeFilter
  RecordFilter <|.. AllFilters
  AllFilters o-- "0..*" RecordFilter : aggregation
  DataManager ..> RecordFilter : query uses
```

## 6. IO layer, web interface and application service

```mermaid
classDiagram
  direction TB
  class WebApp {
    -_flask: Flask
    -_service: KitchenService
    -_io: IOManager
    +dashboard()
    +inventory()
    +add_ingredient()
    +generate_recipe()
    +history()
    +history_detail(record_id)
  }
  class IOManager {
    -_ingredient_form: Form
    -_request_form: Form
    +parse_ingredient(form) FormResult~Ingredient~
    +parse_recipe_request(form) FormResult~RecipeRequest~
    +parse_history_filter(args) RecordFilter
    +expiry_badge(ingredient, today) tuple
  }
  class Form {
    -_fields: tuple~FormField~
    +clean(data) tuple
  }
  class FormField {
    <<abstract>>
    -_name: str
    -_label: str
    -_required: bool
    +clean(raw) Any
    #_convert(text)* Any
  }
  class TextField
  class NumberField
  class DateField
  class ChoiceField
  class ListField
  class FormResult~T~ {
    -_value: T
    -_errors: dict
    +ok bool
  }
  class KitchenService {
    -_data: DataManager
    -_ai: AIManager
    -_logic: LogicManager
    +generate_recipe(request) HistoryRecord
    +add_ingredient(ingredient) Ingredient
    +remove_ingredient(name) Ingredient
    +history(record_filter) list
    +compare_with_current(record_id) RecordComparison
  }
  class RecordComparison {
    -_record: HistoryRecord
    -_current: Evaluation
    +still_cookable bool
    +verdict_changed bool
    +newly_missing tuple
    +rule_changes() list
  }
  class KitchenError
  class InsufficientInventoryError
  class IngredientNotFoundError
  class RecordNotFoundError
  class StorageError

  WebApp --> IOManager : association
  WebApp --> KitchenService : association
  IOManager *-- "2" Form : composition
  Form *-- "1..*" FormField : composition
  FormField <|-- TextField
  FormField <|-- NumberField
  FormField <|-- DateField
  FormField <|-- ChoiceField
  FormField <|-- ListField
  IOManager ..> FormResult : returns
  KitchenService ..> RecordComparison : creates
  RecordComparison --> HistoryRecord : association
  KitchenError <|-- InsufficientInventoryError
  KitchenError <|-- IngredientNotFoundError
  KitchenError <|-- RecordNotFoundError
  KitchenError <|-- StorageError
  KitchenService ..> KitchenError : raises
```

## Where each OOP concept is demonstrated

| Concept | Where | Why it fits the domain |
|---|---|---|
| Classes and objects | `Ingredient`, `Recipe`, `HistoryRecord`, `LogicManager`, `WebApp`, … created by `Application` | Every record and manager is a live object in the running web app |
| Encapsulation | All attributes are `_private` and exposed through read-only `@property`; `Ingredient` and `RecipeRequest` validate in the constructor | An invalid ingredient or request cannot exist, so no layer re-checks |
| Abstract classes | `AIManager`, `BusinessRule`, `JsonRepository`, `FormField` | Share behaviour (retry loop, `check()`, file I/O, blank handling) and leave one step abstract |
| Inheritance | `RejectionRule`/`WarningRule` → five rules; `JsonRepository` → `InventoryRepository`/`HistoryRepository`; `RecipeAIManager`; field types; exception hierarchies | Subclasses specialise one step only |
| Interfaces | `AIClient`, `Repository`, `RecordFilter` | Contracts with several implementations (`GeminiClient` and the test `StubAIClient`; filters) |
| Association | `KitchenService` → managers; `AIManager` → `AIClient`; `RecipeJob` → `Inventory`; `WebApp` → `IOManager` | Collaborators are injected and outlive each other |
| Aggregation | `Inventory` ◇ `Ingredient`; `LogicManager` ◇ `BusinessRule`; `AllFilters` ◇ `RecordFilter` | Parts exist on their own (a removed ingredient still exists; rules are configured outside) |
| Composition | `Recipe` ◆ `RecipeStep`; `DataManager` ◆ repositories; `JsonRepository` ◆ `JsonFileStore`; `Form` ◆ `FormField`; `HistoryRecord` ◆ `Recipe`/`Evaluation` | The owner creates the part and the part has no life outside it |
| Polymorphism | `LogicManager.route()` calls `rule.check()` on every rule; `AIManager` calls `client.generate()`; `DataManager.query()` calls `filter.matches()` | No `isinstance` branching; new rules, clients or filters plug in unchanged |

## SOLID evidence

| Principle | Evidence |
|---|---|
| **S**ingle responsibility | `JsonFileStore` only does safe file I/O; `IngredientMatcher`, `AllergenChecker`, `ExpiryScorer` and `WasteEstimator` each own one calculation; `WebApp` only routes HTTP; `IOManager` only validates and formats |
| **O**pen/closed | A new rule (`BusinessRule` subclass), AI provider (`AIClient`), filter (`RecordFilter`) or field type (`FormField`) is added without editing `LogicManager`, `AIManager`, `DataManager` or `Form`. This is shown by `test_new_rule_plugs_in_without_changing_logic_manager` |
| **L**iskov substitution | Every rule is usable wherever a `BusinessRule` is expected and returns a `RuleResult` with its declared outcome (`test_every_rule_is_substitutable_for_business_rule`); `StubAIClient` replaces `GeminiClient` in all tests |
| **D**ependency inversion | `KitchenService` depends on the abstract `AIManager`/`AIClient`; `Application` wires the concrete classes in one place |
