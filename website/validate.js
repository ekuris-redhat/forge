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

try {
  const dom = new JSDOM(htmlContent, {
    url: "http://localhost",
    runScripts: "dangerously",
  });

  const { window } = dom;
  const { document } = window;

  // Mock scrollIntoView in JSDOM environment
  window.Element.prototype.scrollIntoView = function () {};

  // Read and execute main.js script in the JSDOM window context
  const jsCode = fs.readFileSync(mainJsPath, "utf8");
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
}
