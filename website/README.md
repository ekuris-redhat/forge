# Forge Marketing Website

The marketing and landing page for **Forge**, the AI-powered SDLC orchestrator. This folder houses a clean, modern, ultra-performant, and responsive frontend implementation built with vanilla ES modules, custom CSS variables, and modern web APIs, fully optimized and bundled via Vite.

---

## 🚀 Tech Stack

- **Bundler & Dev Server:** [Vite](https://vite.dev/) (v6+) — provides lightning-fast Hot Module Replacement (HMR) and optimized rollup production builds.
- **Styling:** Vanilla CSS utilizing **CSS Custom Properties (Variables)** for modern, themeable, and responsive layouts with high maintainability.
- **JavaScript:** Vanilla ES Modules (ESM) — no bloated frameworks; utilizing pure modern JavaScript APIs.
- **Testing & DOM Simulation:** [JSDOM](https://github.com/jsdom/jsdom) — for robust frontend component validation and unit testing under a simulated browser environment inside Node.js.

---

## 📁 Directory Structure

```text
website/
├── src/
│   ├── components/
│   │   ├── WaitlistForm.js     # Form component with state-machine based validation
│   │   └── WaitlistSuccess.js  # Success screen rendering dynamic referrers & social sharing
│   ├── main.css                # Global styles, variables, fluid layouts, and component rules
│   ├── main.js                 # Frontend application bootstrap & layout interactivity
│   └── terminal.js             # TerminalSimulator component for realistic code execution animation
├── index.html                  # HTML entrypoint with metadata, OpenGraph tags, and layout shells
├── package.json                # Project dependencies and script commands
├── validate.js                 # Comprehensive JSDOM-based validation & component unit test runner
└── README.md                   # This documentation file
```

---

## 💻 Local Development Setup

To run and build the marketing website locally, make sure you have [Node.js](https://nodejs.org/) installed, then follow these steps:

### 1. Install Dependencies
Run the following command inside the `website/` directory to install Vite, JSDOM, and other development dependencies:
```bash
npm install
```

### 2. Start Local Development Server
Launch the development server with Hot Module Replacement (HMR):
```bash
npm run dev
```
By default, the website will be available at [http://localhost:5173/](http://localhost:5173/).

### 3. Build for Production
Generate optimized, minified, and bundled assets ready for production deployment:
```bash
npm run build
```
The output assets will be generated in the `website/dist/` directory.

### 4. Preview Production Build
Start a local web server to preview the built production assets in `website/dist/`:
```bash
npm run preview
```

---

## 🧪 Frontend Validation & Unit Tests

The frontend includes a comprehensive JSDOM-based validation script (`validate.js`) that performs:
1. **Scaffold Checks:** Verifies file existence, viewport scaling, UTF-8 charset declarations, and correct asset linking.
2. **CSS Variables Check:** Validates that required custom properties (e.g., color, fonts, transitions, and spacing) exist.
3. **Component Unit Testing:** Simulates user interaction, keyboard navigation, responsiveness, state transitions, validation logic, and async API calls (including 409 conflict, 422 validation, and 500 server errors).

### Running Tests
To run the automated validation tests, execute either of the following commands:
```bash
npm run test
```
or directly with Node.js:
```bash
node validate.js
```

---

## 🛠️ Core Interactive Components

### 1. `TerminalSimulator`
A high-observability component that renders a simulated terminal window detailing the step-by-step Forge orchestration process.
- **Customizable Pacing:** Configurable step-by-step (`minDelay`, `maxDelay`) and character typing delays (`charDelay`).
- **State Machine Loop:** Runs the typing animation sequentially and pauses with a specified delay before looping back.
- **Playback Controls:** Fully interactive playback buttons allow manual **Pause**, **Resume**, and **Restart** of the simulation.
- **Viewport Observer:** Uses `IntersectionObserver` with a debounced 100ms visibility check. The simulation automatically pauses when it is less than 10% visible in the viewport and resumes playing when it moves back into view.

### 2. `WaitlistForm`
A robust, accessible form for requesting early beta access.
- **State Machine Architecture:** Moves cleanly between strict states: `IDLE` -> `VALIDATING` -> `SUBMITTING` -> `SUCCESS` or `ERROR`.
- **Dynamic Input Validation:** Validates field completeness, restricts character lengths (e.g., max 100 characters on Name), and blocks personal email domains (like `gmail.com`, `outlook.com`) inline to ensure business-only signups.
- **Asynchronous Submit Handling:** Submits data via `POST` to `/api/v1/waitlist`. During submission, all form inputs are disabled and the button displays a loading spinner/text.
- **Error Mapping & Resilience:** Gracefully handles **409 Conflict** (duplicate registrations), **422 Validation** errors (mapping error payloads back to input fields), and **500 Server Errors** with clear user messaging and a **Retry** capability.
- **Accessibility (A11y):** Implements correct screen reader attributes (`aria-required`, `aria-labelledby`, `aria-describedby` mapping to live error spans, `aria-live="polite"`), and supports native focus management.

### 3. `WaitlistSuccess`
Renders rich user feedback once registration completes.
- **Dynamic Position Rendering:** Displays the applicant's unique waitlist number and referral reference ID retrieved from the API response.
- **Social Sharing Integration:** Pre-fills share buttons for **Twitter/X** and **LinkedIn** with promotional copy featuring their unique referral ID.
- **Clipboard Utility:** A "Copy Waitlist Link" button that copies the personalized referral link to the clipboard and shows a visual confirmation toast with interactive fallback options.
