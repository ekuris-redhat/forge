// Forge Marketing Website JavaScript Entrypoint
document.addEventListener("DOMContentLoaded", () => {
  console.log("Forge Marketing Website initialized successfully!");

  // Sticky header scroll detection
  const header = document.getElementById("site-header");
  if (header) {
    const handleScroll = () => {
      if (window.scrollY > 20) {
        header.classList.add("scrolled");
      } else {
        header.classList.remove("scrolled");
      }
    };

    // Initialize state on load
    handleScroll();
    window.addEventListener("scroll", handleScroll);
  }

  // Mobile Drawer Toggle
  const navToggle = document.getElementById("nav-toggle");
  const drawerClose = document.getElementById("drawer-close");
  const mobileDrawer = document.getElementById("mobile-drawer");
  const drawerBackdrop = document.getElementById("drawer-backdrop");

  const openDrawer = () => {
    if (!mobileDrawer) return;
    mobileDrawer.classList.add("is-open");
    mobileDrawer.setAttribute("aria-hidden", "false");

    if (drawerBackdrop) {
      drawerBackdrop.classList.add("is-active");
      drawerBackdrop.setAttribute("aria-hidden", "false");
    }

    if (navToggle) {
      navToggle.setAttribute("aria-expanded", "true");
      navToggle.setAttribute("aria-label", "Close menu");
    }

    document.body.style.overflow = "hidden";

    // Accessibility: Focus close button inside drawer when opened
    if (drawerClose) {
      drawerClose.focus();
    }
  };

  const closeDrawer = () => {
    if (!mobileDrawer) return;
    mobileDrawer.classList.remove("is-open");
    mobileDrawer.setAttribute("aria-hidden", "true");

    if (drawerBackdrop) {
      drawerBackdrop.classList.remove("is-active");
      drawerBackdrop.setAttribute("aria-hidden", "true");
    }

    if (navToggle) {
      navToggle.setAttribute("aria-expanded", "false");
      navToggle.setAttribute("aria-label", "Open menu");
      // Accessibility: return focus to hamburger button
      navToggle.focus();
    }

    document.body.style.overflow = "";
  };

  if (navToggle) {
    navToggle.addEventListener("click", () => {
      const isExpanded = navToggle.getAttribute("aria-expanded") === "true";
      if (isExpanded) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });

    // Support Space & Enter keys for full keyboard accessibility
    navToggle.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        const isExpanded = navToggle.getAttribute("aria-expanded") === "true";
        if (isExpanded) {
          closeDrawer();
        } else {
          openDrawer();
        }
      }
    });
  }

  if (drawerClose) {
    drawerClose.addEventListener("click", closeDrawer);
    drawerClose.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        closeDrawer();
      }
    });
  }

  if (drawerBackdrop) {
    drawerBackdrop.addEventListener("click", closeDrawer);
  }

  // Close drawer on Escape key press
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Escape" &&
      mobileDrawer &&
      mobileDrawer.classList.contains("is-open")
    ) {
      closeDrawer();
    }
  });

  // Setup smooth scrolling for navigation links
  const links = document.querySelectorAll(
    ".nav-link, .drawer-nav-link, .hero-actions a, .footer-link, .drawer-btn",
  );
  links.forEach((link) => {
    link.addEventListener("click", (e) => {
      const href = link.getAttribute("href");

      const wasDrawerOpen =
        mobileDrawer && mobileDrawer.classList.contains("is-open");
      if (wasDrawerOpen) {
        closeDrawer();
      }

      if (href && href.startsWith("#") && href.length > 1) {
        e.preventDefault();
        const targetElement = document.querySelector(href);
        if (targetElement) {
          // If drawer was open, delay scroll slightly to allow layout calculations to adjust
          const delay = wasDrawerOpen ? 50 : 0;
          setTimeout(() => {
            targetElement.scrollIntoView({
              behavior: "smooth",
              block: "start",
            });
          }, delay);
        }
      }
    });
  });

  // --- Interactive Workflow Visualization Logic ---
  const stepButtons = document.querySelectorAll(".workflow-step-btn");
  const visNodes = document.querySelectorAll(".vis-node");
  const visPaths = document.querySelectorAll(".vis-path");

  const activateStep = (stepNum) => {
    // Activate step button
    stepButtons.forEach((btn) => {
      if (btn.getAttribute("data-step") === stepNum) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // Activate node in visualization
    visNodes.forEach((node, index) => {
      const nodeIndex = index + 1;
      if (nodeIndex === parseInt(stepNum, 10)) {
        node.classList.add("active");
      } else {
        node.classList.remove("active");
      }
    });

    // Activate paths
    visPaths.forEach((path, index) => {
      const pathIndex = index + 1; // path 1 represents line-1-2
      if (pathIndex < parseInt(stepNum, 10)) {
        path.classList.add("active");
      } else {
        path.classList.remove("active");
      }
    });
  };

  stepButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const stepNum = btn.getAttribute("data-step");
      activateStep(stepNum);
    });
  });

  // --- Terminal Simulation Logic ---
  const terminalBody = document.getElementById("terminal-body");
  const terminalOutput = document.getElementById("terminal-output");
  const triggerSimBtn = document.getElementById("btn-trigger-simulation");
  const resetTerminalBtn = document.getElementById("terminal-reset");

  const simulationLogs = [
    { type: "log-info", text: "[INFO] Redis Streams consumer connected" },
    { type: "log-info", text: "[INFO] Queue worker active. Listening on stream: forge:events" },
    { type: "log-info", text: "[INFO] Received ticket: AISOS-1965 (Develop responsive section grids)" },
    { type: "log-info", text: "[INFO] Planning task: Develop responsive section grids..." },
    { type: "log-success", text: "[SUCCESS] Task plan generated successfully" },
    { type: "log-text", text: "[INFO] Spawning container sandbox (forge-AISOS-1965-sandbox)..." },
    { type: "log-text", text: "[INFO] Modifying index.html and main.css..." },
    { type: "log-text", text: "[INFO] Running validation tests (npm run test)..." },
    { type: "log-success", text: "[SUCCESS] All unit tests passed cleanly!" },
    { type: "log-success", text: "[SUCCESS] Task complete. Pull request #14 opened successfully! 🚀" }
  ];

  let simTimer = null;

  const runTerminalSimulation = () => {
    if (!terminalOutput) return;
    // Clear previous logs
    terminalOutput.innerHTML = "";
    if (simTimer) {
      clearTimeout(simTimer);
    }

    let currentLogIndex = 0;

    const printNextLog = () => {
      if (currentLogIndex < simulationLogs.length) {
        const log = simulationLogs[currentLogIndex];
        const logDiv = document.createElement("div");
        logDiv.className = log.type;
        logDiv.innerText = log.text;
        terminalOutput.appendChild(logDiv);
        currentLogIndex++;

        // Auto scroll terminal to bottom
        if (terminalBody) {
          terminalBody.scrollTop = terminalBody.scrollHeight;
        }

        // Schedule next log
        simTimer = setTimeout(printNextLog, 800 + Math.random() * 400);
      }
    };

    printNextLog();
  };

  if (triggerSimBtn) {
    triggerSimBtn.addEventListener("click", runTerminalSimulation);
  }
  if (resetTerminalBtn) {
    resetTerminalBtn.addEventListener("click", runTerminalSimulation);
  }

  // Auto run simulation once on load
  runTerminalSimulation();

  // --- Waitlist Form Logic ---
  const waitlistForm = document.getElementById("waitlist-form");
  const formSuccess = document.getElementById("form-success");
  const btnResetForm = document.getElementById("btn-reset-form");
  const submittedEmailEl = document.getElementById("submitted-email");

  const validateEmail = (email) => {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(String(email).toLowerCase());
  };

  if (waitlistForm) {
    waitlistForm.addEventListener("submit", (e) => {
      e.preventDefault();

      let hasError = false;

      // Validate Name
      const nameInput = document.getElementById("user-name");
      const nameGroup = nameInput ? nameInput.parentElement : null;
      if (nameInput && !nameInput.value.trim()) {
        if (nameGroup) nameGroup.classList.add("has-error");
        hasError = true;
      } else {
        if (nameGroup) nameGroup.classList.remove("has-error");
      }

      // Validate Email
      const emailInput = document.getElementById("user-email");
      const emailGroup = emailInput ? emailInput.parentElement : null;
      if (emailInput && !validateEmail(emailInput.value.trim())) {
        if (emailGroup) emailGroup.classList.add("has-error");
        hasError = true;
      } else {
        if (emailGroup) emailGroup.classList.remove("has-error");
      }

      // Validate Company
      const companyInput = document.getElementById("user-company");
      const companyGroup = companyInput ? companyInput.parentElement : null;
      if (companyInput && !companyInput.value.trim()) {
        if (companyGroup) companyGroup.classList.add("has-error");
        hasError = true;
      } else {
        if (companyGroup) companyGroup.classList.remove("has-error");
      }

      // Validate Role
      const roleInput = document.getElementById("user-role");
      const roleGroup = roleInput ? roleInput.parentElement : null;
      if (roleInput && !roleInput.value) {
        if (roleGroup) roleGroup.classList.add("has-error");
        hasError = true;
      } else {
        if (roleGroup) roleGroup.classList.remove("has-error");
      }

      if (!hasError && emailInput) {
        // Show success state
        if (submittedEmailEl) {
          submittedEmailEl.innerText = emailInput.value.trim();
        }
        waitlistForm.style.display = "none";
        if (formSuccess) {
          formSuccess.style.display = "flex";
          formSuccess.setAttribute("aria-hidden", "false");
        }
      }
    });

    // Dynamic clean-up error on input
    const inputs = waitlistForm.querySelectorAll(".form-input");
    inputs.forEach((input) => {
      input.addEventListener("input", () => {
        const group = input.parentElement;
        if (group) group.classList.remove("has-error");
      });
    });
  }

  if (btnResetForm) {
    btnResetForm.addEventListener("click", () => {
      if (waitlistForm) {
        waitlistForm.reset();
        waitlistForm.style.display = "block";
      }
      if (formSuccess) {
        formSuccess.style.display = "none";
        formSuccess.setAttribute("aria-hidden", "true");
      }
    });
  }
});
