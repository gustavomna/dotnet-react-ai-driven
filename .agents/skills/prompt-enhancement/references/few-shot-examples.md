# Few-Shot Examples by Task Type

Examples of transformation to guide the agent. Use as reference when the task fits the pattern.

---

## Type: Full-Stack Feature (API + UI)

**Typical input:** "Implement X that uses API Y. The frontend should..."

**Output pattern:**
- `<goals>`: Integrate API Y via backend, expose endpoint, display data in responsive UI
- `<workflow>`: 1) Create backend endpoint → 2) Integrate external API → 3) Consume in frontend → 4) Handle loading/errors
- `<output>`: React code + .NET endpoint + TypeScript types
- `<endpoints>`: External API + backend route
- `<tests>`: curl to validate endpoints

---

## Type: Refactoring / Improvement

**Typical input:** "Improve component X", "Refactor to use Y"

**Output pattern:**
- `<goals>`: Refactor preserving behavior, improve [performance/readability/UX]
- `<workflow>`: 1) Analyze current code → 2) Identify improvement points → 3) Apply changes → 4) Validate
- `<output>`: Refactored code with change comments (if applicable)
- `<critical>`: Out of scope — do not change [X, Y, Z]

---

## Type: UI / Isolated Component

**Typical input:** "Create a button that does X", "Build a product card"

**Output pattern:**
- `<goals>`: Reusable component with specified [props/variants]
- `<requirements>`: Detailed UI/UX (states, accessibility, responsiveness)
- `<output>`: React component + types + usage example
- Skills: frontend-design, shadcn, ui-ux-pro-max

---

## Type: Data Integration (CRUD, Form)

**Typical input:** "Registration form that saves to X"

**Output pattern:**
- `<workflow>`: 1) Define schema/validation → 2) Create endpoint → 3) Form with validation → 4) Success/error feedback
- `<output>`: Zod schema + endpoint + form component
- `<tests>`: Payload validation, error handling
