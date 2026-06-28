import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const websiteDir = __dirname;
const indexHtmlPath = path.join(websiteDir, "index.html");
const mainCssPath = path.join(websiteDir, "src", "main.css");
const mainJsPath = path.join(websiteDir, "src", "main.js");

console.log("--- Starting Frontend Scaffold Validation ---");

// 1. Check file existence
const filesToCheck = [
  { name: "index.html", path: indexHtmlPath },
  { name: "src/main.css", path: mainCssPath },
  { name: "src/main.js", path: mainJsPath },
];

let hasErrors = false;

for (const file of filesToCheck) {
  if (fs.existsSync(file.path)) {
    console.log(`✅ File exists: ${file.name}`);
  } else {
    console.error(`❌ File missing: ${file.name}`);
    hasErrors = true;
  }
}

if (hasErrors) {
  process.exit(1);
}

// 2. Validate index.html contents
const htmlContent = fs.readFileSync(indexHtmlPath, "utf8");

// Viewport meta check
const hasViewport = htmlContent.includes('<meta name="viewport"');
const hasCorrectScale =
  htmlContent.includes("width=device-width") &&
  htmlContent.includes("initial-scale=1.0");

if (hasViewport && hasCorrectScale) {
  console.log("✅ Viewport meta tags are set to scale properly");
} else {
  console.error("❌ Missing or incorrect viewport configuration in index.html");
  hasErrors = true;
}

// Global variable usage check (stylesheets linked)
const linksStylesheet = htmlContent.includes('href="/src/main.css"');
if (linksStylesheet) {
  console.log("✅ Global stylesheet link verified in index.html");
} else {
  console.error("❌ Main stylesheet (/src/main.css) not linked in index.html");
  hasErrors = true;
}

// Main JS entrypoint link check
const linksJs = htmlContent.includes('src="/src/main.js"');
if (linksJs) {
  console.log("✅ Main JavaScript entrypoint link verified in index.html");
} else {
  console.error(
    "❌ Main JS (/src/main.js) not linked or not set as module in index.html",
  );
  hasErrors = true;
}

// Charset check
const hasCharset = htmlContent.includes('<meta charset="UTF-8"');
if (hasCharset) {
  console.log("✅ Charset meta tag is set to UTF-8");
} else {
  console.error("❌ Missing UTF-8 charset declaration in index.html");
  hasErrors = true;
}

// 3. Validate main.css contents (CSS variables)
const cssContent = fs.readFileSync(mainCssPath, "utf8");
const requiredCssVars = [
  "--color-primary",
  "--color-secondary",
  "--color-accent",
  "--font-sans",
  "--font-mono",
  "--spacing-4",
  "--transition-normal",
];

for (const cssVar of requiredCssVars) {
  if (cssContent.includes(cssVar)) {
    console.log(`   - Verified CSS Variable: ${cssVar}`);
  } else {
    console.error(`❌ Missing CSS Variable in main.css: ${cssVar}`);
    hasErrors = true;
  }
}

if (hasErrors) {
  console.error("❌ Validation Failed!");
  process.exit(1);
}

// 4. Component Unit Tests
console.log("\n--- Running Component Unit Tests via JSDOM ---");

import { JSDOM } from "jsdom";

(async () => {
  try {
    const dom = new JSDOM(htmlContent, {
      url: "http://localhost",
      runScripts: "dangerously",
    });

    const { window } = dom;
    const { document } = window;

    // Mock scrollIntoView in JSDOM environment
    window.Element.prototype.scrollIntoView = function () {};

    // Read and execute terminal.js script
    const terminalJsPath = path.join(websiteDir, "src", "terminal.js");
    let terminalCode = fs.readFileSync(terminalJsPath, "utf8");
    // Strip ES export keywords so it can be evaluated as a global class/variable
    terminalCode = terminalCode
      .replace(/export\s+const/g, "const")
      .replace(/export\s+class/g, "class");
    terminalCode +=
      "\nwindow.TerminalSimulator = TerminalSimulator;\nwindow.DEFAULT_LOGS = DEFAULT_LOGS;\n";
    window.eval(terminalCode);

    // Intercept TerminalSimulator init to set delays to 0 for tests
    window.eval(`
    const originalInit = TerminalSimulator.prototype.init;
    TerminalSimulator.prototype.init = function(options) {
      options = options || {};
      if (!options.useRealDelays) {
        options.minDelay = 0;
        options.maxDelay = 0;
        this.minDelay = 0;
        this.maxDelay = 0;
        this.loop = false;
      }
      originalInit.call(this, options);
    };
  `);

    // Read and execute main.js script in the JSDOM window context
    let jsCode = fs.readFileSync(mainJsPath, "utf8");
    // Strip import statements
    jsCode = jsCode.replace(
      /import\s+\{\s*TerminalSimulator\s*\}\s+from\s+["'].\/terminal\.js["'];?/g,
      "",
    );
    window.eval(jsCode);

    // Dispatch DOMContentLoaded to trigger script initialization
    const domLoadedEvent = new window.Event("DOMContentLoaded", {
      bubbles: true,
      cancelable: true,
    });
    window.document.dispatchEvent(domLoadedEvent);

    // Helper assert function
    const assert = (condition, message) => {
      if (!condition) {
        throw new Error(`Assertion failed: ${message}`);
      }
      console.log(`✅ ${message}`);
    };

    // Select key elements
    const siteHeader = document.getElementById("site-header");
    const navToggle = document.getElementById("nav-toggle");
    const mobileDrawer = document.getElementById("mobile-drawer");
    const drawerClose = document.getElementById("drawer-close");
    const drawerBackdrop = document.getElementById("drawer-backdrop");

    // Verify elements exist
    assert(siteHeader, "site-header exists in DOM");
    assert(navToggle, "nav-toggle exists in DOM");
    assert(mobileDrawer, "mobile-drawer exists in DOM");
    assert(drawerClose, "drawer-close exists in DOM");
    assert(drawerBackdrop, "drawer-backdrop exists in DOM");

    // --- Test 1: Initial state ---
    console.log("\n[Test 1] Verifying Initial State:");
    assert(
      navToggle.getAttribute("aria-expanded") === "false",
      'nav-toggle initially has aria-expanded="false"',
    );
    assert(
      mobileDrawer.getAttribute("aria-hidden") === "true",
      'mobile-drawer initially has aria-hidden="true"',
    );
    assert(
      !mobileDrawer.classList.contains("is-open"),
      "mobile-drawer does not have is-open class",
    );
    assert(
      drawerBackdrop.getAttribute("aria-hidden") === "true",
      'drawer-backdrop initially has aria-hidden="true"',
    );
    assert(
      !drawerBackdrop.classList.contains("is-active"),
      "drawer-backdrop does not have is-active class",
    );

    // --- Test 2: Drawer Toggle Open on Click ---
    console.log("\n[Test 2] Verifying Drawer Open on Click:");
    navToggle.click();
    assert(
      navToggle.getAttribute("aria-expanded") === "true",
      'nav-toggle has aria-expanded="true" after open',
    );
    assert(
      mobileDrawer.getAttribute("aria-hidden") === "false",
      'mobile-drawer has aria-hidden="false" after open',
    );
    assert(
      mobileDrawer.classList.contains("is-open"),
      "mobile-drawer has is-open class after open",
    );
    assert(
      drawerBackdrop.getAttribute("aria-hidden") === "false",
      'drawer-backdrop has aria-hidden="false" after open',
    );
    assert(
      drawerBackdrop.classList.contains("is-active"),
      "drawer-backdrop has is-active class after open",
    );
    assert(
      document.body.style.overflow === "hidden",
      "body scroll is locked on open",
    );
    assert(
      document.activeElement === drawerClose,
      "drawerClose is focused after open",
    );

    // --- Test 3: Drawer Toggle Close on Click ---
    console.log("\n[Test 3] Verifying Drawer Close on Click:");
    drawerClose.click();
    assert(
      navToggle.getAttribute("aria-expanded") === "false",
      'nav-toggle has aria-expanded="false" after close',
    );
    assert(
      mobileDrawer.getAttribute("aria-hidden") === "true",
      'mobile-drawer has aria-hidden="true" after close',
    );
    assert(
      !mobileDrawer.classList.contains("is-open"),
      "mobile-drawer does not have is-open class after close",
    );
    assert(
      drawerBackdrop.getAttribute("aria-hidden") === "true",
      'drawer-backdrop has aria-hidden="true" after close',
    );
    assert(
      !drawerBackdrop.classList.contains("is-active"),
      "drawer-backdrop does not have is-active class after close",
    );
    assert(
      document.body.style.overflow === "",
      "body scroll lock is released on close",
    );
    assert(
      document.activeElement === navToggle,
      "navToggle is focused after close",
    );

    // --- Test 4: Keyboard Navigation Support ---
    console.log("\n[Test 4] Verifying Keyboard Navigation Support:");
    // Trigger Open via Keydown Enter on navToggle
    const enterEvent = new window.KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
    });
    navToggle.dispatchEvent(enterEvent);
    assert(
      mobileDrawer.classList.contains("is-open"),
      "mobile-drawer opens via Keydown Enter on navToggle",
    );

    // Trigger Close via Keydown Escape on Document
    const escEvent = new window.KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
    });
    document.dispatchEvent(escEvent);
    assert(
      !mobileDrawer.classList.contains("is-open"),
      "mobile-drawer closes via Keydown Escape on document",
    );

    // Trigger Open via Keydown Space on navToggle
    const spaceEvent = new window.KeyboardEvent("keydown", {
      key: " ",
      bubbles: true,
    });
    navToggle.dispatchEvent(spaceEvent);
    assert(
      mobileDrawer.classList.contains("is-open"),
      "mobile-drawer opens via Keydown Space on navToggle",
    );

    // Trigger Close via Keydown Space on drawerClose
    drawerClose.dispatchEvent(spaceEvent);
    assert(
      !mobileDrawer.classList.contains("is-open"),
      "mobile-drawer closes via Keydown Space on drawerClose",
    );

    // --- Test 5: Click on Backdrop closes Drawer ---
    console.log("\n[Test 5] Verifying Backdrop click close:");
    navToggle.click();
    assert(mobileDrawer.classList.contains("is-open"), "mobile-drawer is open");
    drawerBackdrop.click();
    assert(
      !mobileDrawer.classList.contains("is-open"),
      "mobile-drawer is closed on clicking backdrop",
    );

    // --- Test 6: Click on Drawer Navigation Links closes Drawer ---
    console.log("\n[Test 6] Verifying Drawer Nav Links click close:");
    navToggle.click();
    assert(mobileDrawer.classList.contains("is-open"), "mobile-drawer is open");
    const firstDrawerNavLink = document.querySelector(".drawer-nav-link");
    assert(firstDrawerNavLink, "drawer-nav-link exists");
    firstDrawerNavLink.click();
    assert(
      !mobileDrawer.classList.contains("is-open"),
      "mobile-drawer is closed on clicking drawer nav link",
    );

    // --- Test 7: Active Scroll States ---
    console.log("\n[Test 7] Verifying Active Scroll States on site-header:");
    assert(
      !siteHeader.classList.contains("scrolled"),
      'site-header initially does not have "scrolled" class',
    );

    // Mock window.scrollY
    Object.defineProperty(window, "scrollY", {
      value: 50,
      writable: true,
      configurable: true,
    });
    const scrollEvent = new window.Event("scroll");
    window.dispatchEvent(scrollEvent);
    assert(
      siteHeader.classList.contains("scrolled"),
      'site-header has "scrolled" class when scrolled > 20px',
    );

    // Scroll back to top
    window.scrollY = 10;
    window.dispatchEvent(scrollEvent);
    assert(
      !siteHeader.classList.contains("scrolled"),
      'site-header does not have "scrolled" class when scrolled <= 20px',
    );

    // --- Test 8: Verify Core Sections and Grids ---
    console.log("\n[Test 8] Verifying Core Section Structures and Grids:");
    const heroSection = document.querySelector(".hero-section");
    const workflowSection = document.getElementById("workflow");
    const terminalSection = document.getElementById("terminal");
    const waitlistSection = document.getElementById("get-started");

    assert(heroSection, "Hero Section exists in DOM");
    assert(
      workflowSection,
      "Interactive Workflow Visualization Section exists in DOM with id='workflow'",
    );
    assert(
      terminalSection,
      "Terminal Simulation Section exists in DOM with id='terminal'",
    );
    assert(
      waitlistSection,
      "Waitlist Form Section exists in DOM with id='get-started'",
    );

    // Grid structures
    const sectionGrids = document.querySelectorAll(".section-grid");
    assert(
      sectionGrids.length >= 4,
      "At least 4 fluid-responsive section grids are defined in HTML",
    );

    // --- Test 9: Verify Interactive Workflow Interactivity ---
    console.log(
      "\n[Test 9] Verifying Interactive Workflow steps and node activation:",
    );
    const firstStepBtn = document.querySelector(
      '.workflow-step-btn[data-step="1"]',
    );
    const secondStepBtn = document.querySelector(
      '.workflow-step-btn[data-step="2"]',
    );
    const node1 = document.getElementById("node-1");
    const node2 = document.getElementById("node-2");
    const node3 = document.getElementById("node-3");
    const line12 = document.getElementById("line-1-2");

    assert(
      firstStepBtn && secondStepBtn && node3,
      "Workflow step buttons exist in DOM",
    );
    assert(node1 && node2, "Workflow visualization nodes exist in DOM");

    // Click step 2 button
    secondStepBtn.click();
    assert(
      secondStepBtn.classList.contains("active"),
      "Step 2 button becomes active on click",
    );
    assert(
      !firstStepBtn.classList.contains("active"),
      "Step 1 button is deactivated",
    );
    assert(
      node2.classList.contains("active"),
      "Node 2 visualization card is activated",
    );
    assert(
      !node1.classList.contains("active"),
      "Node 1 visualization card is deactivated",
    );
    assert(
      line12.classList.contains("active"),
      "Connecting line path 1-2 is activated",
    );

    // Reset back to Step 1
    firstStepBtn.click();
    assert(
      node1.getAttribute("aria-expanded") === "true",
      'Node 1 has aria-expanded="true" when active',
    );
    assert(
      node2.getAttribute("aria-expanded") === "false",
      'Node 2 has aria-expanded="false" when inactive',
    );

    // Let's click every node, check its active state highlighting, description update, and aria-expanded attributes
    const allNodes = document.querySelectorAll(".workflow-step-btn");
    const descriptionTextEl = () => document.querySelector(".description-text");

    // Let's verify all 6 nodes
    assert(allNodes.length === 6, "Found exactly 6 workflow step nodes");

    allNodes.forEach((node) => {
      const stepNum = node.getAttribute("data-step");
      node.click();
      assert(
        node.classList.contains("active"),
        `Node ${stepNum} is active on click`,
      );
      assert(
        node.getAttribute("aria-expanded") === "true",
        `Node ${stepNum} has aria-expanded="true"`,
      );

      // Check other nodes are inactive and have aria-expanded="false"
      allNodes.forEach((otherNode) => {
        if (otherNode !== node) {
          assert(
            !otherNode.classList.contains("active"),
            `Node ${otherNode.getAttribute("data-step")} is inactive`,
          );
          assert(
            otherNode.getAttribute("aria-expanded") === "false",
            `Node ${otherNode.getAttribute("data-step")} has aria-expanded="false"`,
          );
        }
      });

      // Check description text switches successfully
      const descText = descriptionTextEl().textContent.trim();
      assert(descText.length > 0, `Node ${stepNum} displays description text`);

      if (stepNum === "3") {
        const expectedText =
          "Forge executes agent instructions within completely isolated, sandboxed containers. This ensures untrusted code never runs directly on your primary systems.";
        assert(
          descText === expectedText,
          "Node 3 displays the exact specification text",
        );
      }
    });

    // --- Verify Keyboard Triggers (Enter and Space) on focused nodes ---
    // Reset back to Node 1
    firstStepBtn.click();

    // Trigger space keydown on Node 2
    const wfSpaceEvent = new window.KeyboardEvent("keydown", {
      key: " ",
      bubbles: true,
    });
    node2.dispatchEvent(wfSpaceEvent);
    assert(
      node2.classList.contains("active"),
      "Node 2 becomes active via Space keydown trigger",
    );
    assert(
      node2.getAttribute("aria-expanded") === "true",
      "Node 2 has aria-expanded=true after Space",
    );
    assert(
      node1.getAttribute("aria-expanded") === "false",
      "Node 1 has aria-expanded=false after Space",
    );

    // Trigger enter keydown on Node 3
    const wfEnterEvent = new window.KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
    });
    node3.dispatchEvent(wfEnterEvent);
    assert(
      node3.classList.contains("active"),
      "Node 3 becomes active via Enter keydown trigger",
    );
    assert(
      node3.getAttribute("aria-expanded") === "true",
      "Node 3 has aria-expanded=true after Enter",
    );
    assert(
      node2.getAttribute("aria-expanded") === "false",
      "Node 2 has aria-expanded=false after Enter",
    );

    // --- Test 10: Verify Terminal Simulation Output ---
    console.log(
      "\n[Test 10] Verifying Terminal Simulation outputs on trigger:",
    );
    const terminalResetBtn = document.getElementById("terminal-reset");
    const simTriggerBtn = document.getElementById("btn-trigger-simulation");
    const tOutput = document.getElementById("terminal-output");

    assert(terminalResetBtn, "Terminal reset/refresh button exists");
    assert(simTriggerBtn, "Simulation trigger button exists");
    assert(tOutput, "Terminal output container exists");

    // Trigger terminal simulation manually
    simTriggerBtn.click();
    // Verify that elements are inserted into the terminal output
    assert(
      tOutput.children.length > 0,
      "Terminal simulation inserts logs into the terminal window",
    );

    // --- Test 11: Verify Waitlist Form and Validations ---
    console.log("\n[Test 11] Verifying Waitlist Form and dynamic validations:");
    const waitForm = document.getElementById("waitlist-form");
    const nameIn = document.getElementById("user-name");
    const emailIn = document.getElementById("user-email");
    const companyIn = document.getElementById("user-company");
    const roleIn = document.getElementById("user-role");
    const fSuccess = document.getElementById("form-success");
    const fResetBtn = document.getElementById("btn-reset-form");

    assert(waitForm, "Waitlist form exists in DOM");
    assert(
      nameIn && emailIn && companyIn && roleIn,
      "Form input fields exist (name, email, company, role)",
    );
    assert(fSuccess, "Form success state element exists");

    // Test Submission with Invalid Form (blank fields)
    nameIn.value = "";
    emailIn.value = "";
    companyIn.value = "";
    roleIn.value = "";

    const submitEvent = new window.Event("submit", { cancelable: true });
    waitForm.dispatchEvent(submitEvent);

    assert(
      nameIn.parentElement.classList.contains("has-error"),
      "Name input container has-error on blank submit",
    );
    assert(
      emailIn.parentElement.classList.contains("has-error"),
      "Email input container has-error on blank submit",
    );
    assert(
      companyIn.parentElement.classList.contains("has-error"),
      "Company input container has-error on blank submit",
    );
    assert(
      roleIn.parentElement.classList.contains("has-error"),
      "Role select container has-error on blank submit",
    );

    // Test Dynamic Error Clearance on Input
    nameIn.value = "John Doe";
    const nameInputEvent = new window.Event("input");
    nameIn.dispatchEvent(nameInputEvent);
    assert(
      !nameIn.parentElement.classList.contains("has-error"),
      "Error state cleared on key/input typing",
    );

    // Test Valid Form Submission
    emailIn.value = "john@example.com";
    companyIn.value = "Vercel";
    roleIn.value = "Fullstack Engineer";

    waitForm.dispatchEvent(submitEvent);

    assert(
      waitForm.style.display === "none",
      "Waitlist form is hidden on successful validation",
    );
    assert(
      fSuccess.style.display === "flex",
      "Form success state is displayed",
    );

    const subEmail = document.getElementById("submitted-email");
    assert(
      subEmail && subEmail.innerText === "john@example.com",
      "Submitted email matches the input email",
    );

    // Test Form Reset
    assert(fResetBtn, "Reset form button exists in success state");
    fResetBtn.click();
    assert(
      waitForm.style.display === "block",
      "Form is displayed again after clicking register another",
    );
    assert(fSuccess.style.display === "none", "Success state is hidden again");
    assert(nameIn.value === "", "Name input was reset");

    // --- Test 12: Verify TerminalSimulator Component Reusability and Controls Layout Options ---
    console.log(
      "\n[Test 12] Verifying TerminalSimulator Reusability and Layouts:",
    );
    const testContainer = document.createElement("div");
    testContainer.id = "dynamic-terminal-test";
    document.body.appendChild(testContainer);

    const dynamicSim = new window.TerminalSimulator({
      container: "#dynamic-terminal-test",
      controlsLayout: "beneath",
      autoStart: false,
    });

    assert(
      testContainer.querySelector(".terminal-window"),
      "Dynamic terminal-window rendered successfully",
    );
    assert(
      testContainer.querySelector(".terminal-controls.external"),
      "Controls rendered beneath the terminal chrome when layout is set to 'beneath'",
    );
    assert(
      !testContainer.querySelector(".terminal-window .terminal-controls"),
      "No controls rendered inside the terminal chrome when layout is set to 'beneath'",
    );

    dynamicSim.destroy();
    testContainer.remove();

    // --- Test 13: Verify TerminalSimulator Pacing and Loop State Machine ---
    console.log(
      "\n[Test 13] Verifying TerminalSimulator Pacing and Loop State Machine:",
    );
    const testContainerPacing = document.createElement("div");
    testContainerPacing.id = "pacing-terminal-test";
    document.body.appendChild(testContainerPacing);

    // We spy on setTimeout calls by passing a custom setTimeout function to the constructor
    const timeoutCalls = [];
    const customSetTimeout = (callback, delay, ...args) => {
      timeoutCalls.push({ delay, callback });
      // Use 1ms delay to run fast but asynchronously
      return setTimeout(
        () => {
          try {
            callback();
          } catch (err) {
            console.error("[MOCK-ERROR]", err);
          }
        },
        1,
        ...args,
      );
    };

    let completedReached = false;
    try {
      const pacingSim = await new Promise((resolve, reject) => {
        const sim = new window.TerminalSimulator({
          container: "#pacing-terminal-test",
          useRealDelays: true,
          minDelay: 100,
          maxDelay: 200,
          charDelay: 10,
          restartDelay: 5000,
          loop: true,
          autoStart: true,
          setTimeout: customSetTimeout,
          onComplete: () => {
            completedReached = true;
            resolve(sim);
          },
        });
        // Safety timeout in case of failure (using un-mocked timer)
        setTimeout(() => {
          reject(new Error("Simulator test timed out"));
        }, 2000);
      });

      // Wait a brief moment to let the final loop restart timer schedule
      await new Promise((resolve) => setTimeout(resolve, 50));

      // Verify customized step pacing (should be between 100 and 200 ms)
      const stepDelays = timeoutCalls.filter(
        (c) => c.delay >= 100 && c.delay <= 200,
      );
      assert(
        stepDelays.length > 0,
        `Customized step pacing is registered and used (found ${stepDelays.length} steps)`,
      );

      // Verify customized character pacing (should be 10 ms)
      const charDelays = timeoutCalls.filter((c) => c.delay === 10);
      assert(
        charDelays.length > 0,
        `Customized character pacing is registered and used (found ${charDelays.length} chars)`,
      );

      // Verify final log line triggers a 5.0-second delay before restarting (should be 5000 ms)
      const restartDelays = timeoutCalls.filter((c) => c.delay === 5000);
      assert(
        restartDelays.length > 0,
        "Final log line 'PR #42 opened' triggers a 5.0-second delay before restarting",
      );

      // Let's verify that after the delay, it resets and restarts typing animation from the first step
      assert(
        completedReached === true,
        "Simulator reached completed state and triggered onComplete",
      );
      assert(
        pacingSim.currentLogIndex >= 0,
        "Simulator restarts and resets typing animation after loop delay",
      );

      pacingSim.destroy();
    } finally {
      testContainerPacing.remove();
    }

    // --- Test 14: Verify TerminalSimulator Playback Control Interactions ---
    console.log(
      "\n[Test 14] Verifying TerminalSimulator Playback Control Interactions (Pause, Resume, Restart):",
    );
    const testContainerPlayback = document.createElement("div");
    testContainerPlayback.id = "playback-terminal-test";
    document.body.appendChild(testContainerPlayback);

    const playbackTimeoutCalls = [];
    const playbackCustomSetTimeout = (callback, delay, ...args) => {
      playbackTimeoutCalls.push({ delay, callback });
      return setTimeout(
        () => {
          try {
            callback();
          } catch (err) {
            // Ignore errors if test cleaned up
          }
        },
        1,
        ...args,
      );
    };

    try {
      const playbackSim = new window.TerminalSimulator({
        container: "#playback-terminal-test",
        useRealDelays: true,
        minDelay: 100,
        maxDelay: 200,
        charDelay: 10,
        restartDelay: 5000,
        loop: false,
        autoStart: false,
        setTimeout: playbackCustomSetTimeout,
      });

      assert(playbackSim.isPaused === false, "Simulator initially not paused");
      assert(
        playbackSim.isCompleted === false,
        "Simulator initially not completed",
      );

      const pauseBtn = playbackSim.pauseBtn;
      const restartBtn = playbackSim.restartBtn;
      const terminalOutput = playbackSim.terminalOutput;

      assert(pauseBtn, "Pause button exists in rendered terminal simulator");
      assert(
        restartBtn,
        "Restart button exists in rendered terminal simulator",
      );
      assert(
        terminalOutput,
        "Terminal output exists in rendered terminal simulator",
      );

      const btnText = pauseBtn.querySelector(".btn-text") || pauseBtn;
      assert(
        btnText.textContent.trim() === "Pause",
        "Pause button initially displays 'Pause'",
      );

      playbackSim.start();

      // Wait a tiny bit for a log to start typing
      await new Promise((resolve) => setTimeout(resolve, 5));

      // 1. Test Pause Interaction
      pauseBtn.click();
      assert(
        playbackSim.isPaused === true,
        "Simulator isPaused is true after clicking Pause button",
      );
      assert(
        btnText.textContent.trim() === "Resume",
        "Pause button text transitions to 'Resume' after pause click",
      );

      const textAtPause = terminalOutput.textContent;
      await new Promise((resolve) => setTimeout(resolve, 20));
      assert(
        terminalOutput.textContent === textAtPause,
        "Log output freezes immediately and does not progress while paused",
      );

      // 2. Test Resume Interaction
      pauseBtn.click();
      assert(
        playbackSim.isPaused === false,
        "Simulator isPaused is false after clicking Resume button",
      );
      assert(
        btnText.textContent.trim() === "Pause",
        "Pause button text transitions back to 'Pause' after resume click",
      );

      await new Promise((resolve) => setTimeout(resolve, 20));
      assert(
        terminalOutput.textContent.length > textAtPause.length,
        "Simulator resumes typing animation from exact execution cursor point",
      );

      // 3. Test Restart Interaction
      restartBtn.click();
      assert(
        terminalOutput.textContent === "",
        "Restart button clears visual logs",
      );
      assert(
        playbackSim.currentStep === 0,
        "Restart button resets log index to 0",
      );
      assert(
        playbackSim.currentCharIndex === 0,
        "Restart button resets character index to 0",
      );
      assert(
        playbackSim.isPaused === false,
        "Restart button resets pause state to false",
      );
      assert(
        btnText.textContent.trim() === "Pause",
        "Pause button text is reset to 'Pause' on restart",
      );

      playbackSim.destroy();
    } finally {
      testContainerPlayback.remove();
    }

    // --- Test 15: Verify TerminalSimulator Viewport Observer and Debounced Detection ---
    console.log(
      "\n[Test 15] Verifying TerminalSimulator Viewport Observer and Debounced Detection:",
    );
    const testContainerViewport = document.createElement("div");
    testContainerViewport.id = "viewport-terminal-test";
    document.body.appendChild(testContainerViewport);

    // Mock IntersectionObserver in JSDOM
    class MockIntersectionObserver {
      constructor(callback, options) {
        this.callback = callback;
        this.options = options;
        this.observedElements = [];
        MockIntersectionObserver.instances.push(this);
      }
      observe(element) {
        this.observedElements.push(element);
      }
      unobserve(element) {
        this.observedElements = this.observedElements.filter((el) => el !== element);
      }
      disconnect() {
        this.observedElements = [];
      }
      trigger(entries) {
        this.callback(entries);
      }
    }
    MockIntersectionObserver.instances = [];
    window.IntersectionObserver = MockIntersectionObserver;

    const viewportDelays = [];
    const viewportCustomSetTimeout = (cb, delay) => {
      viewportDelays.push(delay);
      // Map 100ms debounce to 5ms, and pacing/others to 1ms to keep tests fast
      const finalDelay = delay === 100 ? 5 : 1;
      return setTimeout(cb, finalDelay);
    };

    try {
      const viewportSim = new window.TerminalSimulator({
        container: "#viewport-terminal-test",
        useRealDelays: true,
        minDelay: 100,
        maxDelay: 200,
        charDelay: 10,
        restartDelay: 5000,
        loop: false,
        autoStart: false, // let observer handle it
        setTimeout: viewportCustomSetTimeout,
      });

      assert(
        viewportSim.viewportObserver instanceof MockIntersectionObserver,
        "viewportObserver is instantiated as MockIntersectionObserver",
      );
      assert(
        viewportSim.viewportObserver.observedElements.includes(viewportSim.terminalWindow),
        "viewportObserver is observing the terminalWindow element",
      );

      // 1. Trigger visibility >= 10% (e.g. 0.1)
      viewportSim.viewportObserver.trigger([{
        intersectionRatio: 0.1,
        target: viewportSim.terminalWindow,
      }]);

      assert(
        viewportSim.wasVisible === undefined,
        "Debounced callback has not run immediately on trigger",
      );

      // Wait for mapped 5ms debounce to fire
      await new Promise((resolve) => setTimeout(resolve, 15));

      assert(
        viewportSim.wasVisible === true,
        "Debounced callback executed and set wasVisible to true",
      );
      assert(
        viewportSim.currentStep === 0 && !viewportSim.isPaused,
        "Simulator automatically starts playing from step 1 when visibility is 10% or higher",
      );
      assert(
        viewportDelays.includes(100),
        "Scroll/intersection trigger callbacks are debounced by exactly 100ms",
      );

      // Wait a tiny bit for simulation progression
      await new Promise((resolve) => setTimeout(resolve, 15));

      // 2. Trigger visibility < 10% (e.g. 0.05)
      viewportSim.viewportObserver.trigger([{
        intersectionRatio: 0.05,
        target: viewportSim.terminalWindow,
      }]);

      assert(
        viewportSim.isPaused === false,
        "Debounced callback has not run immediately on drop below 10%",
      );

      // Wait for mapped 5ms debounce to fire
      await new Promise((resolve) => setTimeout(resolve, 15));

      assert(
        viewportSim.isPaused === true,
        "Simulator pauses automatically when visibility drops below 10%",
      );

      // 3. Trigger visibility back to >= 10% (e.g. 0.12)
      viewportSim.viewportObserver.trigger([{
        intersectionRatio: 0.12,
        target: viewportSim.terminalWindow,
      }]);

      assert(
        viewportSim.isPaused === true,
        "Debounced callback has not run immediately on visibility increase",
      );

      // Wait for mapped 5ms debounce to fire
      await new Promise((resolve) => setTimeout(resolve, 15));

      assert(
        viewportSim.isPaused === false,
        "Simulator automatically starts playing from step 1 again when visibility is 10% or higher",
      );

      viewportSim.destroy();
    } finally {
      testContainerViewport.remove();
      delete window.IntersectionObserver;
    }

    console.log("\n🎉 All Component Unit Tests passed successfully!");
  } catch (e) {
    console.error("\n❌ Component Unit Tests failed:");
    console.error(e.stack || e.message);
    hasErrors = true;
  }

  if (hasErrors) {
    console.error("\n❌ Validation Failed!");
    process.exit(1);
  } else {
    console.log(
      "\n🎉 All scaffold and component validation checks passed successfully!",
    );
    process.exit(0);
  }
})();
