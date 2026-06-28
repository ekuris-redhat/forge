// Forge Marketing Website JavaScript Entrypoint
import { TerminalSimulator } from "./terminal.js";

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

  const phaseDetails = {
    "1": {
      phase: "Phase 1",
      title: "Jira Ticket",
      desc: "Forge listens for Jira issue events and automatically triggers when the <code>forge:managed</code> label is added. It parses the issue description and comments to initialize the development workflow."
    },
    "2": {
      phase: "Phase 2",
      title: "Human-Gated Plan",
      desc: "The system conducts a thorough root cause analysis and generates a step-by-step implementation plan. This plan remains gated, requiring explicit developer approval before any code is modified."
    },
    "3": {
      phase: "Phase 3",
      title: "Containerized Implementation",
      desc: "Forge executes agent instructions within completely isolated, sandboxed containers. This ensures untrusted code never runs directly on your primary systems."
    },
    "4": {
      phase: "Phase 4",
      title: "GitHub PR",
      desc: "After writing the code, the agent automatically runs code quality checks, lints files, and opens a pull request. The PR description is fully synchronized with Jira ticket context."
    },
    "5": {
      phase: "Phase 5",
      title: "CI Self-Healing",
      desc: "If CI/CD pipelines fail due to testing or compilation errors, Forge's self-healing agent acts. It analyzes the failure logs and pushes targeted hotfixes autonomously to recover the build."
    },
    "6": {
      phase: "Phase 6",
      title: "Human Review",
      desc: "The completed pull request undergoes thorough human review for security and style compliance. Merging the PR signals completion, closing out the issue and updating the status."
    }
  };

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
        node.setAttribute("aria-expanded", "true");
      } else {
        node.classList.remove("active");
        node.setAttribute("aria-expanded", "false");
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

    // Update node status labels dynamically
    visNodes.forEach((node) => {
      const currentStep = node.getAttribute("data-step");
      if (currentStep) {
        const statusElement = node.querySelector(".node-status");
        if (statusElement) {
          if (currentStep === stepNum) {
            statusElement.textContent = "Active";
            statusElement.className = "node-status status-active";
          } else if (parseInt(currentStep, 10) < parseInt(stepNum, 10)) {
            statusElement.textContent = "Completed";
            statusElement.className = "node-status status-completed";
          } else {
            statusElement.textContent = "Pending";
            statusElement.className = "node-status status-pending";
          }
        }
      }
    });

    // Update dynamic description block
    const descBlock = document.getElementById("workflow-description-block");
    if (descBlock && phaseDetails[stepNum]) {
      const details = phaseDetails[stepNum];
      descBlock.innerHTML = `
        <div class="description-card">
          <span class="description-badge">${details.phase}</span>
          <h3 class="description-title">${details.title}</h3>
          <p class="description-text">${details.desc}</p>
        </div>
      `;
    }
  };

  stepButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const stepNum = btn.getAttribute("data-step");
      activateStep(stepNum);
    });

    btn.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        const stepNum = btn.getAttribute("data-step");
        activateStep(stepNum);
      }
    });
  });

  // Highlight step 1 on load
  activateStep("1");

  // --- Terminal Simulation Logic ---
  const terminalSimulator = new TerminalSimulator({
    autoStart: true,
    minDelay: 800,
    maxDelay: 1200
  });

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
